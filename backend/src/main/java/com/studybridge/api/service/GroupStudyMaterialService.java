package com.studybridge.api.service;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.dto.GroupStudyMaterialDTO;
import com.studybridge.api.dto.GroupStudyQuizDTO;
import com.studybridge.api.entity.*;
import com.studybridge.api.repository.*;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.reactive.function.client.WebClient;

import java.io.IOException;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.NoSuchElementException;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
@Slf4j
@Transactional(readOnly = true)
public class GroupStudyMaterialService {

    private final GroupStudyMaterialRepository groupStudyMaterialRepository;
    private final GroupStudyRepository groupStudyRepository;
    private final GroupStudyMemberRepository groupStudyMemberRepository;
    private final GroupStudyQuizRepository groupStudyQuizRepository;
    private final GroupStudyQuizQuestionRepository groupStudyQuizQuestionRepository;
    private final UserRepository userRepository;
    private final S3Service s3Service;
    private final WebClient fastApiWebClient;
    private final ObjectMapper objectMapper;

    /**
     * 그룹원 전용 PDF 학습 자료를 업로드하고, S3 업로드 성공 시 FastAPI AI 엔진을 호출하여 퀴즈를 자동으로 생성합니다.
     */
    @Transactional
    public GroupStudyMaterialDTO uploadMaterialAndGenerateQuiz(Long userId, Long groupId, String title, MultipartFile file) throws IOException {
        log.info("Group study material upload and quiz generation start. userId={}, groupId={}, title={}", userId, groupId, title);

        User uploader = userRepository.findById(userId)
                .orElseThrow(() -> new NoSuchElementException("User not found with ID: " + userId));

        GroupStudy groupStudy = groupStudyRepository.findById(groupId)
                .orElseThrow(() -> new NoSuchElementException("Group study not found with ID: " + groupId));

        // 1. 그룹 멤버 권한 체크
        if (!groupStudyMemberRepository.existsByGroupStudyIdAndUserIdAndStatus(groupId, userId, GroupStudyMemberStatus.JOINED)) {
            throw new SecurityException("해당 그룹스터디방의 정식 멤버만 자료를 업로드할 수 있습니다.");
        }

        // 2. S3 업로드
        String s3Key = s3Service.uploadFile(file, userId);

        // 3. DB 자료 메타데이터 저장
        GroupStudyMaterial material = GroupStudyMaterial.builder()
                .groupStudy(groupStudy)
                .uploader(uploader)
                .title(title)
                .s3Key(s3Key)
                .fileSize(file.getSize())
                .originalFileName(file.getOriginalFilename())
                .build();

        GroupStudyMaterial savedMaterial = groupStudyMaterialRepository.save(material);
        log.info("Group study material saved in DB. materialId={}, s3Key={}", savedMaterial.getId(), s3Key);

        // 4. FastAPI AI 연동 자동 퀴즈 생성
        generateAIQuiz(groupStudy, uploader, savedMaterial, s3Key, file.getOriginalFilename());

        return toDTO(savedMaterial);
    }

    /**
     * 특정 스터디 룸 내부의 모든 공유 자료 목록을 조회합니다. (정식 회원만 조회 가능, 1회용 Presigned Url 포함)
     */
    public List<GroupStudyMaterialDTO> getMaterials(Long userId, Long groupId) {
        if (!groupStudyMemberRepository.existsByGroupStudyIdAndUserIdAndStatus(groupId, userId, GroupStudyMemberStatus.JOINED)) {
            throw new SecurityException("그룹 멤버만 자료 목록을 조회할 수 있습니다.");
        }

        return groupStudyMaterialRepository.findByGroupStudyIdOrderByCreatedAtDesc(groupId).stream()
                .map(this::toDTO)
                .collect(Collectors.toList());
    }

    /**
     * 자료 다운로드를 위해 안전한 1회용 Presigned URL을 발급받습니다. (정식 회원만 가능)
     */
    public String downloadMaterialUrl(Long userId, Long materialId) {
        GroupStudyMaterial material = groupStudyMaterialRepository.findById(materialId)
                .orElseThrow(() -> new NoSuchElementException("Material not found with ID: " + materialId));

        Long groupId = material.getGroupStudy().getId();
        if (!groupStudyMemberRepository.existsByGroupStudyIdAndUserIdAndStatus(groupId, userId, GroupStudyMemberStatus.JOINED)) {
            throw new SecurityException("그룹 멤버만 자료 다운로드 URL을 발급받을 수 있습니다.");
        }

        return s3Service.getPresignedUrl(material.getS3Key());
    }

    /**
     * FastAPI AI 연동을 이용해 비동기로 퀴즈 세트를 생성하는 메서드 (실패 시 Fallback 제공)
     */
    private void generateAIQuiz(GroupStudy groupStudy, User creator, GroupStudyMaterial material, String s3Key, String fileName) {
        log.info("Requesting AI quiz generation from FastAPI. materialId={}", material.getId());

        GroupStudyQuizDTO.AIQuizRequest requestPayload = GroupStudyQuizDTO.AIQuizRequest.builder()
                .materialId(material.getId())
                .s3Key(s3Key)
                .fileName(fileName)
                .build();

        GroupStudyQuizDTO.AIQuizResponse aiResponse = null;

        try {
            aiResponse = fastApiWebClient.post()
                    .uri("/api/ai/quiz/generate")
                    .bodyValue(requestPayload)
                    .retrieve()
                    .bodyToMono(GroupStudyQuizDTO.AIQuizResponse.class)
                    .block(); // 동기식 대기
        } catch (Exception e) {
            log.error("FastAPI AI quiz generation communication failed. Initiating standard welcome quiz fallback. Error: ", e);
        }

        // AI 서버 응답이 없거나 예외 발생 시, 학습용 룰 기반 기본 퀴즈 3문제를 생성해 주는 Fallback 메커니즘
        if (aiResponse == null || aiResponse.getQuestions() == null || aiResponse.getQuestions().isEmpty()) {
            aiResponse = createFallbackQuiz(material.getTitle());
        }

        // 퀴즈 영속화 저장
        try {
            GroupStudyQuiz quiz = GroupStudyQuiz.builder()
                    .groupStudy(groupStudy)
                    .creator(creator)
                    .title(aiResponse.getQuizTitle())
                    .rewardPoints(10) // 맞출 때 마다 10점 지급 기본설정
                    .build();

            GroupStudyQuiz savedQuiz = groupStudyQuizRepository.save(quiz);

            for (GroupStudyQuizDTO.AIQuestion aiQ : aiResponse.getQuestions()) {
                String optionsJsonStr = objectMapper.writeValueAsString(aiQ.getOptions());

                GroupStudyQuizQuestion question = GroupStudyQuizQuestion.builder()
                        .quiz(savedQuiz)
                        .question(aiQ.getQuestion())
                        .optionsJson(optionsJsonStr)
                        .correctAnswer(aiQ.getCorrectAnswer())
                        .timeLimitSeconds(aiQ.getTimeLimitSeconds() != null ? aiQ.getTimeLimitSeconds() : 30)
                        .build();

                groupStudyQuizQuestionRepository.save(question);
            }

            log.info("Successfully persisted AI/Fallback Quiz. quizId={}, questionsCount={}", 
                    savedQuiz.getId(), aiResponse.getQuestions().size());

        } catch (Exception e) {
            log.error("Failed to persist generated quiz in Database: ", e);
        }
    }

    private GroupStudyQuizDTO.AIQuizResponse createFallbackQuiz(String materialTitle) {
        log.info("Creating default study fallback quiz for material={}", materialTitle);

        List<GroupStudyQuizDTO.AIQuestion> questions = new ArrayList<>();

        questions.add(GroupStudyQuizDTO.AIQuestion.builder()
                .question("학습 계획을 수립할 때 가장 효과적인 목표 설정 기법은 무엇일까요?")
                .options(Arrays.asList("SMART 기법 (구체적, 측정가능, 달성가능, 현실적, 시간제한)", "무조건 많이 공부하기", "남의 계획 그대로 따라하기", "계획 세우지 않기"))
                .correctAnswer(0)
                .timeLimitSeconds(20)
                .build());

        questions.add(GroupStudyQuizDTO.AIQuestion.builder()
                .question("StudyBridge에서 학습 능률 향상을 위해 권장하는 집중 기법은 무엇인가요?")
                .options(Arrays.asList("벼락치기 기법", "뽀모도로 기법 (25분 집중, 5분 휴식)", "밤샘 기법", "멀티태스킹 기법"))
                .correctAnswer(1)
                .timeLimitSeconds(20)
                .build());

        questions.add(GroupStudyQuizDTO.AIQuestion.builder()
                .question("스터디 중 모르는 내용이 생겼을 때 가장 바람직한 행동은 무엇일까요?")
                .options(Arrays.asList("그냥 넘어가기", "포기하고 놀기", "그룹원들과 실시간 채팅/화상으로 공유하고 토론하기", "책 덮고 자기"))
                .correctAnswer(2)
                .timeLimitSeconds(20)
                .build());

        return GroupStudyQuizDTO.AIQuizResponse.builder()
                .quizTitle("[" + materialTitle + "] 자료 기반 학습 퀴즈")
                .questions(questions)
                .build();
    }

    private GroupStudyMaterialDTO toDTO(GroupStudyMaterial material) {
        String presignedUrl = null;
        try {
            presignedUrl = s3Service.getPresignedUrl(material.getS3Key());
        } catch (Exception e) {
            log.warn("Failed to generate presignedUrl for group study material ID={}: {}", material.getId(), e.getMessage());
        }

        return GroupStudyMaterialDTO.builder()
                .id(material.getId())
                .groupStudyId(material.getGroupStudy().getId())
                .title(material.getTitle())
                .s3Key(material.getS3Key())
                .fileSize(material.getFileSize())
                .originalFileName(material.getOriginalFileName())
                .presignedUrl(presignedUrl)
                .uploaderId(material.getUploader().getId())
                .uploaderName(material.getUploader().getDisplayName())
                .createdAt(material.getCreatedAt())
                .build();
    }
}
