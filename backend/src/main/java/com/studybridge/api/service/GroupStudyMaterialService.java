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
import com.studybridge.api.ai.AiFailoverExecutor;
import com.studybridge.api.ai.contract.v1.ResponseQualityV1;
import com.studybridge.api.ai.quality.AiResponseQualityGate;
import com.studybridge.api.ai.quality.GateDecision;
import com.studybridge.api.exception.AiUpstreamException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.JsonNodeFactory;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpStatus;

import java.io.IOException;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.NoSuchElementException;
import java.util.UUID;
import java.util.function.Supplier;
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
    // PRIMARY(ai07) → SECONDARY(EC2 hot-standby) 공통 failover(/api/ai/quiz/generate). 기존 fastApiWebClient 는 executor 의 primary 와 동일.
    private final AiFailoverExecutor aiFailoverExecutor;
    private final ObjectMapper objectMapper;

    // Global Response Quality Gate(기본 OFF). 생성자 시그니처를 바꾸지 않도록 선택 주입(null = OFF).
    private AiResponseQualityGate qualityGate;

    @Autowired(required = false)
    public void setQualityGate(AiResponseQualityGate qualityGate) {
        this.qualityGate = qualityGate;
    }

    private boolean gateOn() {
        return qualityGate != null && qualityGate.enabled();
    }

    /** 게이트 ON 에서 미검증(quality_status≠APPROVED) 저장 그룹 퀴즈의 AI 생성 제목 대신 내보내는 고정 문구. */
    public static final String REDACTED_QUIZ_TITLE = "AI 품질 검증 전 퀴즈(내용 비공개)";
    static final String APPROVED = "APPROVED";
    static final int EVIDENCE_CHUNK_CHARS = 4000;
    static final int EVIDENCE_MAX_CHARS = 48000;

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
        try {
            generateAIQuiz(groupStudy, uploader, savedMaterial, s3Key, file.getOriginalFilename(),
                    clampQuestionCount(questionCount), clampQuestionSeconds(perQuestionSeconds), () -> bytesOf(file));
        } catch (AiUpstreamException qualityFailure) {
            // 게이트 ON 품질 거절/평가 불가: "자료 등록 + 퀴즈 생성" 을 성공으로 위장하지 않는다. 자료 행은 롤백되고
            // 방금 올린 S3 객체는 롤백 뒤 best-effort 삭제(고아 방지). 사용자는 같은 파일로 다시 시도할 수 있다(retryable).
            runAfterRollback(() -> {
                try {
                    s3Service.deleteFile(s3Key);
                } catch (Exception e) {
                    log.error("[GROUP_QUIZ_GATE] 롤백 후 S3 삭제 실패(고아 객체) groupId={} key={}", groupId, s3Key, e);
                }
            });
            throw qualityFailure;
        }

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

        boolean gate = gateOn();
        return groupStudyQuizRepository.findByGroupStudyIdOrderByCreatedAtDesc(groupId).stream()
                .map(quiz -> {
                    // 게이트 ON: 승인 기록이 없는 저장 퀴즈(레거시/게이트 OFF 시기)는 AI 생성 제목을 가린다. id·생성자·개수는 유지.
                    boolean hide = gate && !APPROVED.equals(quiz.getQualityStatus());
                    return GroupStudyQuizDTO.QuizResponse.builder()
                            .id(quiz.getId())
                            .groupStudyId(quiz.getGroupStudy().getId())
                            .title(hide ? REDACTED_QUIZ_TITLE : quiz.getTitle())
                            .rewardPoints(quiz.getRewardPoints())
                            .creatorId(quiz.getCreator().getId())
                            .creatorName(quiz.getCreator().getDisplayName())
                            .createdAt(quiz.getCreatedAt())
                            .questionCount(quiz.getQuestions() != null ? quiz.getQuestions().size() : 0)
                            // 게이트 OFF: 전부 null(기존 응답과 동일)
                            .qualityStatus(gate ? quiz.getQualityStatus() : null)
                            .qualityScore(gate && !hide ? quiz.getQualityScore() : null)
                            .verified(gate ? !hide : null)
                            .qualityRedacted(hide ? Boolean.TRUE : null)
                            .build();
                })
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
                clampQuestionCount(questionCount), clampQuestionSeconds(perQuestionSeconds),
                () -> s3Service.downloadBytes(material.getS3Key()));
        if (quiz == null) {
            throw new IllegalStateException("퀴즈 생성에 실패했습니다. 잠시 후 다시 시도해주세요.");
        }
        boolean approved = gateOn() && APPROVED.equals(quiz.getQualityStatus());

        return GroupStudyQuizDTO.QuizResponse.builder()
                .id(quiz.getId())
                .groupStudyId(quiz.getGroupStudy().getId())
                .title(quiz.getTitle())
                .rewardPoints(quiz.getRewardPoints())
                .creatorId(quiz.getCreator().getId())
                .creatorName(quiz.getCreator().getDisplayName())
                .createdAt(quiz.getCreatedAt())
                .questionCount(quiz.getQuestions() != null ? quiz.getQuestions().size() : 0)
                // 게이트 OFF: null(기존 응답과 동일). ON: 여기까지 왔으면 승인본만 저장됐다.
                .qualityStatus(approved ? APPROVED : null)
                .qualityScore(approved ? quiz.getQualityScore() : null)
                .verified(approved ? Boolean.TRUE : null)
                .build();
    }

    // FastAPI AI 연동을 이용해 퀴즈 세트를 생성하는 메서드 (실패 시 Fallback 제공). 저장된 퀴즈를 반환.
    // sourceBytes = 품질 게이트 근거용 원본 파일(게이트 ON 일 때만 읽는다).
    private GroupStudyQuiz generateAIQuiz(GroupStudy groupStudy, User creator, GroupStudyMaterial material, String s3Key,
            String fileName, int questionCount, int perQuestionSeconds, Supplier<byte[]> sourceBytes) {
        log.info("Requesting AI quiz generation from FastAPI. materialId={}, questionCount={}, perQuestionSeconds={}",
                material.getId(), questionCount, perQuestionSeconds);

        GroupStudyQuizDTO.AIQuizRequest requestPayload = GroupStudyQuizDTO.AIQuizRequest.builder()
                .materialId(material.getId())
                .s3Key(s3Key)
                .fileName(fileName)
                .numQuestions(questionCount)
                .build();

        if (gateOn()) {
            return generateAIQuizGated(groupStudy, creator, material, requestPayload, questionCount, perQuestionSeconds, sourceBytes);
        }

        GroupStudyQuizDTO.AIQuizResponse aiResponse = requestAiQuiz(requestPayload, material.getId());

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

    /** 저장할 수 있는(정답 키가 보기 안에 있는) 문항 + 0-based 정답. */
    record GradableQuestion(GroupStudyQuizDTO.AIQuestion q, int correct) { }

    record GroupQuizDraft(String title, List<GradableQuestion> questions) { }

    /**
     * 게이트 경로(PDF_QUIZ / quiz_json): 생성 → 저장·노출될 제목·문항·보기·정답·해설 전부를 평가 → 거절 시 최대 2회 재생성 → 승인분만 저장
     * (quality_status=APPROVED). 근거 = Spring 이 가진 원본 파일에서 결정적으로 뽑은 원문(GroupStudyQuizSourceText, documentId 범위).
     * 생성 자체가 처음부터 실패하면 재생성하지 않고 기존 계약(null = 퀴즈 미저장)을 따른다. 거절/평가 불가는 AiUpstreamException
     * (422 AI_QUALITY_REJECTED / 503 AI_QUALITY_UNAVAILABLE, retryable)로 명시 실패 — 저장 0, 기존 퀴즈는 그대로. failover 는 매 시도 동일.
     */
    private GroupStudyQuiz generateAIQuizGated(GroupStudy groupStudy, User creator, GroupStudyMaterial material,
            GroupStudyQuizDTO.AIQuizRequest basePayload, int questionCount, int perQuestionSeconds, Supplier<byte[]> sourceBytes) {
        Long gmId = material.getId();
        String docId = GroupStudyQuizSourceText.documentId(gmId);
        String rid = "gquiz-" + gmId + "-" + UUID.randomUUID().toString().substring(0, 8);
        byte[] bytes = null;
        try {
            bytes = sourceBytes != null ? sourceBytes.get() : null;
        } catch (Exception e) {
            log.warn("[GROUP_QUIZ_GATE] 근거 원본 읽기 실패 materialId={} rid={} error={} → 근거 없이 평가", gmId, rid, e.getClass().getSimpleName());
        }
        String text = GroupStudyQuizSourceText.extract(bytes, material.getContentType(), material.getOriginalFileName(), EVIDENCE_MAX_CHARS);
        ResponseQualityV1.Constraints constraints = new ResponseQualityV1.Constraints(null, List.of(docId), questionCount, null, null,
                null, null, false, false, null, null, null, null, null, null);
        AiResponseQualityGate.Spec spec = new AiResponseQualityGate.Spec(rid, ResponseQualityV1.TaskType.PDF_QUIZ,
                ResponseQualityV1.OutputKind.QUIZ_JSON,
                "다음 그룹 스터디 자료 원문에 근거한 객관식 퀴즈 " + questionCount + "문항(제목·정답 포함)을 만들어 주세요: "
                        + (material.getTitle() != null ? material.getTitle() : ""),
                GroupStudyQuizSourceText.evidence(docId, text, EVIDENCE_CHUNK_CHARS, EVIDENCE_MAX_CHARS), constraints, null);
        final boolean[] upstreamFailed = {false};
        AiResponseQualityGate.Outcome<GroupQuizDraft> outcome = qualityGate.generateApproved(spec, (attempt, previous) -> {
            GroupStudyQuizDTO.AIQuizRequest payload = attempt == 0 ? basePayload : GroupStudyQuizDTO.AIQuizRequest.builder()
                    .materialId(basePayload.getMaterialId()).s3Key(basePayload.getS3Key()).fileName(basePayload.getFileName())
                    .numQuestions(basePayload.getNumQuestions()).strictGrounding(basePayload.getStrictGrounding())
                    .regenerationAttempt(attempt).regenerationHints(previous != null ? previous.reasonCodes() : List.of())
                    .build();
            GroupStudyQuizDTO.AIQuizResponse ai = requestAiQuiz(payload, gmId);
            String unusable = ai == null || ai.getQuestions() == null || ai.getQuestions().isEmpty() ? "EMPTY" : unusableAiQuizReason(ai);
            List<GradableQuestion> gradable = unusable == null ? gradableQuestions(ai, gmId) : List.of();
            if (unusable != null || gradable.isEmpty()) {
                log.error("[GROUP_QUIZ_GATE] AI quiz unusable(reason={}) materialId={} rid={} attempt={} → 재생성하지 않음",
                        unusable != null ? unusable : "NO_GRADABLE_QUESTION", gmId, rid, attempt);
                upstreamFailed[0] = true;
                throw new AiResponseQualityGate.StopGeneration("GENERATION_FAILED");
            }
            return new GroupQuizDraft(ai.getQuizTitle(), gradable);
        }, GroupStudyMaterialService::proposedOutput);

        if (outcome.approved()) {
            return persistApprovedQuiz(groupStudy, creator, outcome.value(), perQuestionSeconds, outcome.decision(), gmId);
        }
        GateDecision d = outcome.decision();
        if (upstreamFailed[0] && d.attempts() <= 1) {
            return null; // 첫 생성부터 실패 — 평가할 초안이 없었다(기존 계약: 퀴즈 미저장)
        }
        log.warn("[GROUP_QUIZ_GATE] quality gate not approved materialId={} rid={} status={} codes={} attempts={} evidenceChunks={} → 저장하지 않음",
                gmId, rid, d.qualityStatus(), d.reasonCodes(), d.attempts(), spec.evidence().size());
        boolean rejected = GateDecision.REJECTED.equals(d.errorCode());
        throw new AiUpstreamException(rejected ? HttpStatus.UNPROCESSABLE_ENTITY : HttpStatus.SERVICE_UNAVAILABLE,
                rejected ? GateDecision.REJECTED : GateDecision.UNAVAILABLE, GateDecision.userMessage(d.errorCode()), rid, true, null, null);
    }

    /** 평가 대상(quiz_json) = 저장·노출될 AI 생성 문자열 전부: 퀴즈 제목, 문항, 보기, 정답(0-based answerIndex), 해설(정답키 교차검증용). */
    static JsonNode proposedOutput(GroupQuizDraft draft) {
        ObjectNode root = JsonNodeFactory.instance.objectNode();
        root.put("title", draft.title() != null ? draft.title() : "");
        ArrayNode qs = root.putArray("questions");
        for (GradableQuestion g : draft.questions()) {
            ObjectNode n = qs.addObject();
            n.put("question", g.q().getQuestion());
            ArrayNode opts = n.putArray("options");
            g.q().getOptions().forEach(opts::add);
            n.put("answerIndex", g.correct());
            n.put("explanation", g.q().getExplanation() != null ? g.q().getExplanation() : "");
        }
        return root;
    }

    private List<GradableQuestion> gradableQuestions(GroupStudyQuizDTO.AIQuizResponse ai, Long materialId) {
        List<GradableQuestion> out = new ArrayList<>();
        for (GroupStudyQuizDTO.AIQuestion aiQ : ai.getQuestions()) {
            Integer correct = resolveCorrectAnswer(aiQ);
            if (aiQ.getQuestion() == null || aiQ.getQuestion().isBlank() || aiQ.getOptions() == null
                    || aiQ.getOptions().size() < 2 || correct == null) {
                log.warn("Skipping ungradable AI question. materialId={} questionId={} correctAnswer={} correctOptionIds={}",
                        materialId, aiQ.getQuestionId(), aiQ.getCorrectAnswer(), aiQ.getCorrectOptionIds());
                continue;
            }
            out.add(new GradableQuestion(aiQ, correct));
        }
        return out;
    }

    /** 승인된 초안만 저장(평가한 문항 그대로 — 저장 단계에서 문항을 더하거나 바꾸지 않는다). 저장 실패는 기존 계약대로 null. */
    private GroupStudyQuiz persistApprovedQuiz(GroupStudy groupStudy, User creator, GroupQuizDraft draft, int perQuestionSeconds,
            GateDecision approval, Long materialId) {
        try {
            GroupStudyQuiz savedQuiz = groupStudyQuizRepository.save(GroupStudyQuiz.builder()
                    .groupStudy(groupStudy)
                    .creator(creator)
                    .title(draft.title())
                    .rewardPoints(10)
                    .qualityStatus(APPROVED)
                    .qualityScore(approval.score())
                    .build());
            for (GradableQuestion g : draft.questions()) {
                groupStudyQuizQuestionRepository.save(GroupStudyQuizQuestion.builder()
                        .quiz(savedQuiz)
                        .question(g.q().getQuestion())
                        .optionsJson(objectMapper.writeValueAsString(g.q().getOptions()))
                        .correctAnswer(g.correct())
                        .timeLimitSeconds(perQuestionSeconds)
                        .build());
            }
            log.info("Successfully persisted AI Quiz(gated). quizId={}, questionsCount={}, score={} attempts={}",
                    savedQuiz.getId(), draft.questions().size(), approval.score(), approval.attempts());
            return savedQuiz;
        } catch (Exception e) {
            log.error("Failed to persist gated quiz in Database. materialId={}", materialId, e);
            return null;
        }
    }

    private static byte[] bytesOf(MultipartFile file) {
        try {
            return file.getBytes();
        } catch (IOException e) {
            return null;
        }
    }

    private static void runAfterRollback(Runnable task) {
        if (org.springframework.transaction.support.TransactionSynchronizationManager.isSynchronizationActive()) {
            org.springframework.transaction.support.TransactionSynchronizationManager.registerSynchronization(
                    new org.springframework.transaction.support.TransactionSynchronization() {
                        @Override
                        public void afterCompletion(int status) {
                            if (status == STATUS_ROLLED_BACK) {
                                task.run();
                            }
                        }
                    });
        } else {
            task.run();
        }
    }

    /**
     * FastAPI {@code POST /api/ai/quiz/generate} 호출(PRIMARY → SECONDARY failover).
     * 전송 실패/timeout/404/5xx 만 다음 업스트림으로 넘기고, 4xx 검증 오류는 failover 없이 실패(null) 로 끝낸다.
     * 응답 본문의 success/status 판정은 기존대로 {@link #unusableAiQuizReason} 이 담당한다(session lifecycle 불변).
     * @return 실패 시 null (기존 계약: null → 퀴즈 미저장)
     */
    GroupStudyQuizDTO.AIQuizResponse requestAiQuiz(GroupStudyQuizDTO.AIQuizRequest requestPayload, Long materialId) {
        try {
            AiFailoverExecutor.Result<GroupStudyQuizDTO.AIQuizResponse> picked = aiFailoverExecutor.execute("/api/ai/quiz/generate",
                    up -> up.client().post()
                            .uri("/api/ai/quiz/generate")
                            .bodyValue(requestPayload)
                            .retrieve()
                            .bodyToMono(GroupStudyQuizDTO.AIQuizResponse.class)
                            .block()); // 동기식 대기
            if (picked.attempts() > 1) {
                log.info("AI quiz generation served by upstream={} after failover. materialId={}", picked.upstreamName(), materialId);
            }
            return picked.value();
        } catch (Exception e) {
            log.error("FastAPI AI quiz generation communication failed. materialId={}. Error: ", materialId, e);
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
