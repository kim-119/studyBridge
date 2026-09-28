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
    private final GroupStudyQuizSessionRepository groupStudyQuizSessionRepository;
    private final GroupStudyQuizSessionAnswerRepository groupStudyQuizSessionAnswerRepository;
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

        // 그룹스터디 경로에서는 더미/placeholder/degraded 퀴즈를 절대 저장하지 않는다.
        // 판정은 AI07 의 구조화 상태(success/errorCode/status/degraded/fallbackUsed) 우선. 제목 문자열 판정은 마지막 안전망.
        if (aiResponse == null || aiResponse.getQuestions() == null || aiResponse.getQuestions().isEmpty()) {
            log.error("AI quiz generation returned empty result. Not persisting a quiz. materialId={} errorCode={} message={}",
                    material.getId(), aiResponse != null ? aiResponse.getErrorCode() : null,
                    aiResponse != null ? aiResponse.getMessage() : null);
            return null;
        }
        String unusable = unusableAiQuizReason(aiResponse);
        if (unusable != null) {
            log.error("AI quiz generation unusable(reason={}). Not persisting a quiz. materialId={}, status={}, errorCode={}, title={}",
                    unusable, material.getId(), aiResponse.getStatus(), aiResponse.getErrorCode(), aiResponse.getQuizTitle());
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

            int persisted = 0;
            for (GroupStudyQuizDTO.AIQuestion aiQ : aiResponse.getQuestions()) {
                Integer correct = resolveCorrectAnswer(aiQ);
                if (aiQ.getQuestion() == null || aiQ.getQuestion().isBlank() || aiQ.getOptions() == null
                        || aiQ.getOptions().size() < 2 || correct == null) {
                    // 정답 키가 없거나 보기 밖이면 그 문항은 저장하지 않는다(0 으로 위장 금지).
                    log.warn("Skipping ungradable AI question. materialId={} questionId={} correctAnswer={} correctOptionIds={}",
                            material.getId(), aiQ.getQuestionId(), aiQ.getCorrectAnswer(), aiQ.getCorrectOptionIds());
                    continue;
                }
                String optionsJsonStr = objectMapper.writeValueAsString(aiQ.getOptions());

                GroupStudyQuizQuestion question = GroupStudyQuizQuestion.builder()
                        .quiz(savedQuiz)
                        .question(aiQ.getQuestion())
                        .optionsJson(optionsJsonStr)
                        .correctAnswer(correct)
                        .timeLimitSeconds(perQuestionSeconds)
                        .build();

                groupStudyQuizQuestionRepository.save(question);
                persisted++;
            }
            if (persisted == 0) {
                log.error("No gradable question in AI quiz. Rolling back quiz. materialId={}", material.getId());
                groupStudyQuizRepository.delete(savedQuiz);
                return null;
            }

            log.info("Successfully persisted AI Quiz. quizId={}, questionsCount={}, schemaVersion={}",
                    savedQuiz.getId(), persisted, aiResponse.getSchemaVersion());

            return savedQuiz;

        } catch (Exception e) {
            log.error("Failed to persist generated quiz in Database: ", e);
            return null;
        }
    }

    /**
     * AI07 퀴즈 응답을 저장하면 안 되는 이유 코드(null 이면 사용 가능).
     *  1) 구조화 상태: success=false / errorCode / status∈{FAILED,DEGRADED,FALLBACK} / degraded / fallbackUsed.
     *  2) 마지막 안전망: 구조화 필드가 전부 비어 있는(구버전 AI07) 응답에서만 "기본 안내형" placeholder 마커를 본다.
     *     [AI07 FOLLOW-UP] 운영 AI07 이 quiz.v2(status/degraded) 를 내려주기 시작하면 2) 는 제거 가능.
     */
    static String unusableAiQuizReason(GroupStudyQuizDTO.AIQuizResponse aiResponse) {
        if (aiResponse == null) return "NULL_RESPONSE";
        if (Boolean.FALSE.equals(aiResponse.getSuccess())) return "SUCCESS_FALSE";
        if (aiResponse.getErrorCode() != null && !aiResponse.getErrorCode().isBlank()) return "ERROR_CODE:" + aiResponse.getErrorCode();
        String status = aiResponse.getStatus() == null ? "" : aiResponse.getStatus().trim().toUpperCase();
        if (status.equals("FAILED") || status.equals("FAIL") || status.equals("ERROR")) return "STATUS_FAILED";
        if (status.equals("DEGRADED") || status.equals("FALLBACK")) return "STATUS_DEGRADED";
        if (Boolean.TRUE.equals(aiResponse.getDegraded())) return "DEGRADED_FLAG";
        if (Boolean.TRUE.equals(aiResponse.getFallbackUsed())) return "FALLBACK_USED";

        boolean hasStructuredSignals = aiResponse.getSuccess() != null || aiResponse.getStatus() != null
                || aiResponse.getDegraded() != null || aiResponse.getFallbackUsed() != null
                || aiResponse.getSchemaVersion() != null;
        if (!hasStructuredSignals && isLegacyPlaceholderQuiz(aiResponse)) return "LEGACY_PLACEHOLDER_MARKER";
        return null;
    }

    // 구버전 AI07(구조화 상태 없음) 전용 안전망. 새 응답에는 적용되지 않는다.
    private static final List<String> PLACEHOLDER_QUESTION_MARKERS = Arrays.asList(
            "다음 중 효과적인 학습 방법으로 알려진 것은",
            "학습 내용을 장기 기억으로 전환하는 데 가장 효과적인 방법",
            "포모도로 기법에서 기본 집중 시간");

    private static boolean isLegacyPlaceholderQuiz(GroupStudyQuizDTO.AIQuizResponse aiResponse) {
        String title = aiResponse.getQuizTitle();
        if (title != null && title.contains("기본 안내형")) return true;
        if (aiResponse.getQuestions() == null) return false;
        return aiResponse.getQuestions().stream()
                .map(GroupStudyQuizDTO.AIQuestion::getQuestion)
                .filter(q -> q != null)
                .anyMatch(q -> PLACEHOLDER_QUESTION_MARKERS.stream().anyMatch(q::contains));
    }

    /**
     * 정답 인덱스(0-based). 기존 correctAnswer 우선, 없으면 quiz.v2 correctOptionIds[0] 을 optionIds 에서 찾는다.
     * 보기 범위 밖이면 null(문항 저장 안 함).
     */
    static Integer resolveCorrectAnswer(GroupStudyQuizDTO.AIQuestion q) {
        if (q == null || q.getOptions() == null) return null;
        int size = q.getOptions().size();
        Integer idx = q.getCorrectAnswer();
        if (idx == null && q.getCorrectOptionIds() != null && !q.getCorrectOptionIds().isEmpty()) {
            String target = q.getCorrectOptionIds().get(0);
            if (q.getOptionIds() != null && q.getOptionIds().contains(target)) {
                idx = q.getOptionIds().indexOf(target);
            } else if (q.getOptions().contains(target)) {
                idx = q.getOptions().indexOf(target);
            }
        }
        if (idx == null || idx < 0 || idx >= size) return null;
        return idx;
    }

    // ── 방장 전용 삭제 ─────────────────────────────────────────────────────

    /**
     * 그룹 자료 삭제(방장만). 검증 순서: 그룹 404 → 방장 403 → 자료 404 → 그룹 소속(IDOR) 404.
     * DB 삭제 후 커밋되면 S3 객체를 best-effort 삭제한다. GroupStudyQuiz 는 자료와 링크가 없어 함께 지우지 않는다.
     */
    @Transactional
    public void deleteMaterial(Long userId, Long groupId, Long materialId) {
        GroupStudy groupStudy = requireLeader(userId, groupId);
        GroupStudyMaterial material = groupStudyMaterialRepository.findById(materialId)
                .orElseThrow(() -> new NoSuchElementException("Material not found with ID: " + materialId));
        if (material.getGroupStudy() == null || !material.getGroupStudy().getId().equals(groupStudy.getId())) {
            throw new NoSuchElementException("이 그룹스터디에 속한 자료가 아닙니다.");
        }
        String s3Key = material.getS3Key();
        groupStudyMaterialRepository.delete(material);
        if (s3Key != null && !s3Key.isBlank()) {
            runAfterCommit(() -> {
                try {
                    s3Service.deleteFile(s3Key);
                } catch (Exception e) {
                    log.error("[GROUP_MATERIAL_DELETE] S3 삭제 실패(DB 는 삭제됨, 고아 객체) groupId={} materialId={} key={}",
                            groupId, materialId, s3Key, e);
                }
            });
        }
        log.info("Group material deleted. groupId={} materialId={} by userId={}", groupId, materialId, userId);
    }

    /**
     * 그룹 퀴즈 삭제(방장만). 진행 중(QUESTION/REVEALING) 세션이 있으면 409. 완료 세션은 답변→세션 순으로 정리 후 퀴즈 삭제
     * (문항은 cascade). Redis 랭킹은 groupId 단위 누적이라 퀴즈 삭제로 건드리지 않는다(퀴즈별 Redis 키 없음).
     */
    @Transactional
    public void deleteQuiz(Long userId, Long groupId, Long quizId) {
        GroupStudy groupStudy = requireLeader(userId, groupId);
        GroupStudyQuiz quiz = groupStudyQuizRepository.findById(quizId)
                .orElseThrow(() -> new NoSuchElementException("Quiz not found with ID: " + quizId));
        if (quiz.getGroupStudy() == null || !quiz.getGroupStudy().getId().equals(groupStudy.getId())) {
            throw new NoSuchElementException("이 그룹스터디에 속한 퀴즈가 아닙니다.");
        }
        if (groupStudyQuizSessionRepository.existsByQuizIdAndStatusIn(quizId,
                List.of(GroupStudyQuizSessionStatus.QUESTION, GroupStudyQuizSessionStatus.REVEALING))) {
            throw new IllegalStateException("진행 중인 퀴즈 세션이 있어 삭제할 수 없습니다. 세션이 끝난 뒤 다시 시도해주세요.");
        }
        List<Long> sessionIds = groupStudyQuizSessionRepository.findIdsByQuizId(quizId);
        if (!sessionIds.isEmpty()) {
            groupStudyQuizSessionAnswerRepository.deleteBySessionIdIn(sessionIds);
            groupStudyQuizSessionRepository.deleteByQuizId(quizId);
        }
        groupStudyQuizRepository.delete(quiz);
        log.info("Group quiz deleted. groupId={} quizId={} sessionsPurged={} by userId={}", groupId, quizId, sessionIds.size(), userId);
    }

    /** 그룹 존재(404) + 방장(GroupStudy.leader 가 authoritative, 403). 브라우저가 보낸 role/isHost 는 사용하지 않는다. */
    private GroupStudy requireLeader(Long userId, Long groupId) {
        GroupStudy groupStudy = groupStudyRepository.findById(groupId)
                .orElseThrow(() -> new NoSuchElementException("Group study not found with ID: " + groupId));
        if (userId == null || groupStudy.getLeader() == null || !groupStudy.getLeader().getId().equals(userId)) {
            throw new SecurityException("방장만 삭제할 수 있습니다.");
        }
        return groupStudy;
    }

    private static void runAfterCommit(Runnable task) {
        if (org.springframework.transaction.support.TransactionSynchronizationManager.isSynchronizationActive()) {
            org.springframework.transaction.support.TransactionSynchronizationManager.registerSynchronization(
                    new org.springframework.transaction.support.TransactionSynchronization() {
                        @Override
                        public void afterCommit() { task.run(); }
                    });
        } else {
            task.run();
        }
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
