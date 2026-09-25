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

    // 생성 옵션 기본값/보정 상수 (문제 수 1~20, 문제당 시간 5~120초)
    private static final int DEFAULT_QUESTION_COUNT = 5;
    private static final int DEFAULT_QUESTION_SECONDS = 15;

    private int clampQuestionCount(Integer count) {
        if (count == null) return DEFAULT_QUESTION_COUNT;
        return Math.max(1, Math.min(20, count));
    }

    private int clampQuestionSeconds(Integer seconds) {
        if (seconds == null) return DEFAULT_QUESTION_SECONDS;
        return Math.max(5, Math.min(120, seconds));
    }

    @Transactional
    public GroupStudyMaterialDTO uploadMaterialAndGenerateQuiz(Long userId, Long groupId, String title,
            MultipartFile file, Integer questionCount, Integer perQuestionSeconds) throws IOException {
        log.info("Group study material upload and quiz generation start. userId={}, groupId={}, title={}", userId,
                groupId, title);

        User uploader = userRepository.findById(userId)
                .orElseThrow(() -> new NoSuchElementException("User not found with ID: " + userId));

        GroupStudy groupStudy = groupStudyRepository.findById(groupId)
                .orElseThrow(() -> new NoSuchElementException("Group study not found with ID: " + groupId));

        // 1. 그룹 멤버 권한 체크
        if (!groupStudyMemberRepository.existsByGroupStudyIdAndUserIdAndStatus(groupId, userId,
                GroupStudyMemberStatus.JOINED)) {
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
                .contentType(file.getContentType())
                .build();

        GroupStudyMaterial savedMaterial = groupStudyMaterialRepository.save(material);
        log.info("Group study material saved in DB. materialId={}, s3Key={}", savedMaterial.getId(), s3Key);

        // 4. FastAPI AI 연동 자동 퀴즈 생성
        generateAIQuiz(groupStudy, uploader, savedMaterial, s3Key, file.getOriginalFilename(),
                clampQuestionCount(questionCount), clampQuestionSeconds(perQuestionSeconds));

        return toDTO(savedMaterial);
    }

    // 특정 스터디 룸 내부의 모든 공유 자료 목록을 조회합니다.

    public List<GroupStudyMaterialDTO> getMaterials(Long userId, Long groupId) {
        if (!groupStudyMemberRepository.existsByGroupStudyIdAndUserIdAndStatus(groupId, userId,
                GroupStudyMemberStatus.JOINED)) {
            throw new SecurityException("그룹 멤버만 자료 목록을 조회할 수 있습니다.");
        }

        return groupStudyMaterialRepository.findByGroupStudyIdOrderByCreatedAtDesc(groupId).stream()
                .map(this::toDTO)
                .collect(Collectors.toList());
    }

    public List<GroupStudyQuizDTO.QuizResponse> getGroupQuizzes(Long userId, Long groupId) {
        if (!groupStudyMemberRepository.existsByGroupStudyIdAndUserIdAndStatus(groupId, userId,
                GroupStudyMemberStatus.JOINED)) {
            throw new SecurityException("그룹 멤버만 퀴즈 목록을 조회할 수 있습니다.");
        }

        return groupStudyQuizRepository.findByGroupStudyIdOrderByCreatedAtDesc(groupId).stream()
                .map(quiz -> GroupStudyQuizDTO.QuizResponse.builder()
                        .id(quiz.getId())
                        .groupStudyId(quiz.getGroupStudy().getId())
                        .title(quiz.getTitle())
                        .rewardPoints(quiz.getRewardPoints())
                        .creatorId(quiz.getCreator().getId())
                        .creatorName(quiz.getCreator().getDisplayName())
                        .createdAt(quiz.getCreatedAt())
                        .questionCount(quiz.getQuestions() != null ? quiz.getQuestions().size() : 0)
                        .build())
                .collect(Collectors.toList());
    }

    // 자료 다운로드를 위해 안전한 1회용 Presigned URL을 발급받습니다.

    public String downloadMaterialUrl(Long userId, Long materialId) {
        GroupStudyMaterial material = groupStudyMaterialRepository.findById(materialId)
                .orElseThrow(() -> new NoSuchElementException("Material not found with ID: " + materialId));

        Long groupId = material.getGroupStudy().getId();
        if (!groupStudyMemberRepository.existsByGroupStudyIdAndUserIdAndStatus(groupId, userId,
                GroupStudyMemberStatus.JOINED)) {
            throw new SecurityException("그룹 멤버만 자료 다운로드 URL을 발급받을 수 있습니다.");
        }

        return s3Service.getPresignedUrl(material.getS3Key(), material.getOriginalFileName());
    }

    // 이미 업로드된 그룹스터디 자료를 기준으로 퀴즈를 재생성한다. (S3에 저장된 PDF의 s3Key/fileName 재사용)
    @Transactional
    public GroupStudyQuizDTO.QuizResponse generateQuizForMaterial(Long userId, Long groupId, Long materialId,
            Integer questionCount, Integer perQuestionSeconds) {
        User creator = userRepository.findById(userId)
                .orElseThrow(() -> new NoSuchElementException("User not found with ID: " + userId));

        // 1. 그룹 멤버 권한 체크
        if (!groupStudyMemberRepository.existsByGroupStudyIdAndUserIdAndStatus(groupId, userId,
                GroupStudyMemberStatus.JOINED)) {
            throw new SecurityException("그룹 멤버만 퀴즈를 생성할 수 있습니다.");
        }

        // 2. 자료 조회 + 그룹 소속 검증 (다른 그룹 자료로 생성 방지)
        GroupStudyMaterial material = groupStudyMaterialRepository.findById(materialId)
                .orElseThrow(() -> new NoSuchElementException("Material not found with ID: " + materialId));
        if (!material.getGroupStudy().getId().equals(groupId)) {
            throw new SecurityException("해당 그룹스터디의 자료가 아닙니다.");
        }

        // 3. 기존 자료 기반 퀴즈 생성 (업로드 경로와 동일 로직 재사용)
        GroupStudyQuiz quiz = generateAIQuiz(material.getGroupStudy(), creator, material,
                material.getS3Key(), material.getOriginalFileName(),
                clampQuestionCount(questionCount), clampQuestionSeconds(perQuestionSeconds));
        if (quiz == null) {
            throw new IllegalStateException("퀴즈 생성에 실패했습니다. 잠시 후 다시 시도해주세요.");
        }

        return GroupStudyQuizDTO.QuizResponse.builder()
                .id(quiz.getId())
                .groupStudyId(quiz.getGroupStudy().getId())
                .title(quiz.getTitle())
                .rewardPoints(quiz.getRewardPoints())
                .creatorId(quiz.getCreator().getId())
                .creatorName(quiz.getCreator().getDisplayName())
                .createdAt(quiz.getCreatedAt())
                .questionCount(quiz.getQuestions() != null ? quiz.getQuestions().size() : 0)
                .build();
    }

    // FastAPI AI 연동을 이용해 퀴즈 세트를 생성하는 메서드 (실패 시 Fallback 제공). 저장된 퀴즈를 반환.
    private GroupStudyQuiz generateAIQuiz(GroupStudy groupStudy, User creator, GroupStudyMaterial material, String s3Key,
            String fileName, int questionCount, int perQuestionSeconds) {
        log.info("Requesting AI quiz generation from FastAPI. materialId={}, questionCount={}, perQuestionSeconds={}",
                material.getId(), questionCount, perQuestionSeconds);

        GroupStudyQuizDTO.AIQuizRequest requestPayload = GroupStudyQuizDTO.AIQuizRequest.builder()
                .materialId(material.getId())
                .s3Key(s3Key)
                .fileName(fileName)
                .numQuestions(questionCount)
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
            log.error("FastAPI AI quiz generation communication failed. materialId={}. Error: ", material.getId(), e);
        }

        // 그룹스터디 경로에서는 더미/placeholder 퀴즈를 절대 만들지 않는다.
        // ai07(FastAPI)이 PDF 처리에 실패하면 자체 "기본 안내형" placeholder 세트를 HTTP 200으로 돌려준다.
        // 이를 정상 퀴즈로 저장하면 사용자가 시작 시 PDF가 아닌 더미 문제를 보게 되므로, 저장하지 않고 실패 처리한다.
        if (aiResponse == null || aiResponse.getQuestions() == null || aiResponse.getQuestions().isEmpty()) {
            log.error("AI quiz generation returned empty result. Not persisting a quiz. materialId={}", material.getId());
            return null;
        }
        if (isPlaceholderAiQuiz(aiResponse)) {
            log.error("AI quiz generation returned a non-PDF placeholder (기본 안내형). Not persisting a quiz. materialId={}, title={}",
                    material.getId(), aiResponse.getQuizTitle());
            return null;
        }

        // 퀴즈 저장
        try {
            GroupStudyQuiz quiz = GroupStudyQuiz.builder()
                    .groupStudy(groupStudy)
                    .creator(creator)
                    .title(aiResponse.getQuizTitle())
                    .rewardPoints(10) // 맞출 때 마다 10점 지급
                    .build();

            GroupStudyQuiz savedQuiz = groupStudyQuizRepository.save(quiz);

            for (GroupStudyQuizDTO.AIQuestion aiQ : aiResponse.getQuestions()) {
                String optionsJsonStr = objectMapper.writeValueAsString(aiQ.getOptions());

                GroupStudyQuizQuestion question = GroupStudyQuizQuestion.builder()
                        .quiz(savedQuiz)
                        .question(aiQ.getQuestion())
                        .optionsJson(optionsJsonStr)
                        .correctAnswer(aiQ.getCorrectAnswer())
                        .timeLimitSeconds(perQuestionSeconds)
                        .build();

                groupStudyQuizQuestionRepository.save(question);
            }

            log.info("Successfully persisted AI/Fallback Quiz. quizId={}, questionsCount={}",
                    savedQuiz.getId(), aiResponse.getQuestions().size());

            return savedQuiz;

        } catch (Exception e) {
            log.error("Failed to persist generated quiz in Database: ", e);
            return null;
        }
    }

    // ai07(FastAPI)이 PDF 처리에 실패했을 때 돌려주는 자체 placeholder("기본 안내형") 응답인지 판별한다.
    // 이 응답은 PDF와 무관한 일반 학습법 문제이므로 그룹스터디 퀴즈로 사용하면 안 된다.
    private static final List<String> PLACEHOLDER_QUESTION_MARKERS = Arrays.asList(
            "다음 중 효과적인 학습 방법으로 알려진 것은",
            "학습 내용을 장기 기억으로 전환하는 데 가장 효과적인 방법",
            "포모도로 기법에서 기본 집중 시간");

    private boolean isPlaceholderAiQuiz(GroupStudyQuizDTO.AIQuizResponse aiResponse) {
        String title = aiResponse.getQuizTitle();
        if (title != null && title.contains("기본 안내형")) {
            return true;
        }
        if (aiResponse.getQuestions() == null) {
            return false;
        }
        return aiResponse.getQuestions().stream()
                .map(GroupStudyQuizDTO.AIQuestion::getQuestion)
                .filter(q -> q != null)
                .anyMatch(q -> PLACEHOLDER_QUESTION_MARKERS.stream().anyMatch(q::contains));
    }

    private GroupStudyMaterialDTO toDTO(GroupStudyMaterial material) {
        return GroupStudyMaterialDTO.builder()
                .id(material.getId())
                .groupStudyId(material.getGroupStudy().getId())
                .title(material.getTitle())
                .fileSize(material.getFileSize())
                .originalFileName(material.getOriginalFileName())
                .contentType(material.getContentType())
                .uploaderId(material.getUploader().getId())
                .uploaderName(material.getUploader().getDisplayName())
                .createdAt(material.getCreatedAt())
                .build();
    }
}
