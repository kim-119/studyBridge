package com.studybridge.api.service;

import com.studybridge.api.entity.LearningEventOrigin;
import com.studybridge.api.entity.LearningEventType;
import com.studybridge.api.entity.LearningLoopEvent;
import com.studybridge.api.entity.LearningSourceType;
import com.studybridge.api.entity.Material;
import com.studybridge.api.entity.Planner;
import com.studybridge.api.entity.ReviewNote;
import com.studybridge.api.repository.LearningLoopEventRepository;
import com.studybridge.api.repository.MaterialRepository;
import com.studybridge.api.repository.PlannerRepository;
import com.studybridge.api.repository.ReviewNoteRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.EnumSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

/**
 * 학습 왕복 루프(Learning Loop)의 중심 서비스.
 *
 *  1) record / recordSafe : 학습·AI 행동을 LearningLoopEvent 로 영속화한다(best-effort, 쓰기는 LearningLoopEventWriter).
 *     recordClientEvent     : 사용자가 직접 보낸 이벤트(허용 타입·소유권·크기 검증, origin=CLIENT).
 *  2) queryEvents         : materialId/documentId/source 기준으로 이벤트 이력을 조회한다.
 *  3) assembleContext     : 다음 AI 호출에 붙일 learningLoopContext 패키지를 구성한다.
 *  4) recommendReview     : 난이도/오답 수 기반으로 복습 추천일을 결정적으로 계산한다.
 *  5) (복습 일정 등록은 ScheduleRegistrationService 로 이관 — 주간 일정 = todos 테이블)
 *
 * 모든 기록은 본래 학습 기능을 깨뜨리지 않도록 best-effort 로 동작한다.
 */
@Slf4j
@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class LearningLoopService {

    private static final int CONTEXT_LIMIT = 5;

    private final LearningLoopEventRepository eventRepository;
    private final LearningLoopEventWriter eventWriter;
    private final PlannerRepository plannerRepository;
    private final MaterialRepository materialRepository;
    private final ReviewNoteRepository reviewNoteRepository;

    // ------------------------------------------------------------------
    // 1) 이벤트 기록
    // ------------------------------------------------------------------

    /**
     * 독립(REQUIRES_NEW, read-write) 트랜잭션에서 즉시 저장한다. 검증/DB 오류는 호출자에게 그대로 던진다.
     * 호출자가 커밋 이후(afterCommit)에서 부를 때 쓴다(ScheduleRegistrationService).
     */
    @Transactional(propagation = Propagation.NOT_SUPPORTED)
    public LearningLoopEvent record(LearningLoopEvent event) {
        validateServerEvent(event);
        if (event.getOrigin() == null) {
            event.setOrigin(LearningEventOrigin.SERVER);
        }
        return eventWriter.write(event);
    }

    /**
     * 이벤트 기록 실패가 본래 기능을 절대 깨뜨리지 않도록 감싼 버전(다른 서비스에서 호출).
     *  · 호출자 트랜잭션이 있으면 그 트랜잭션이 커밋된 뒤에 독립 트랜잭션으로 기록한다 → 반환값 null.
     *    (본기능이 롤백되면 "요약을 생성했다" 같은 유령 이벤트가 남지 않고, 이벤트 INSERT 실패가 본기능을 rollback-only 로 만들지 않는다.)
     *  · 호출자 트랜잭션이 없으면 즉시 독립 트랜잭션으로 기록하고 id 를 돌려준다.
     *  · SUPPORTS: 클래스 기본 readOnly 트랜잭션을 새로 열지 않고, 있으면 호출자 트랜잭션의 동기화에만 붙는다.
     */
    @Transactional(propagation = Propagation.SUPPORTS)
    public Long recordSafe(LearningLoopEvent event) {
        try {
            validateServerEvent(event);
        } catch (Exception e) {
            logSkip(event, e);
            return null;
        }
        if (event.getOrigin() == null) {
            event.setOrigin(LearningEventOrigin.SERVER);
        }
        if (TransactionSynchronizationManager.isActualTransactionActive()
                && TransactionSynchronizationManager.isSynchronizationActive()) {
            java.util.concurrent.atomic.AtomicBoolean done = new java.util.concurrent.atomic.AtomicBoolean();
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                @Override
                public void afterCommit() {
                    if (done.compareAndSet(false, true)) {
                        writeSafely(event);
                    }
                }

                @Override
                public void afterCompletion(int status) {
                    // 다른 afterCommit 콜백 안에서 등록되면 afterCommit 은 호출되지 않는다 → 커밋 완료 시점에 한 번 보장.
                    if (status == STATUS_COMMITTED && done.compareAndSet(false, true)) {
                        writeSafely(event);
                    }
                }
            });
            return null;
        }
        return writeSafely(event);
    }

    private Long writeSafely(LearningLoopEvent event) {
        try {
            return eventWriter.write(event).getId();
        } catch (Exception e) {
            logSkip(event, e);
            return null;
        }
    }

    private void validateServerEvent(LearningLoopEvent event) {
        if (event == null || event.getUserId() == null || event.getEventType() == null) {
            throw new IllegalArgumentException("userId, eventType 은 필수입니다.");
        }
    }

    private void logSkip(LearningLoopEvent event, Exception e) {
        // 원문(inputText/aiOutput*/userMemo)은 로그에 남기지 않는다.
        log.warn("[LEARNING_LOOP] record skipped userId={} type={} cause={}",
                event != null ? event.getUserId() : null,
                event != null ? event.getEventType() : null,
                e.getClass().getSimpleName());
    }

    // ------------------------------------------------------------------
    // 1-b) 클라이언트 이벤트 (사용자 주장 — 서버 사실로 승격 금지)
    // ------------------------------------------------------------------

    /** 클라이언트가 직접 기록할 수 있는 타입. AI 생성/퀴즈 결과/오답/일정 등 서버만 아는 사실은 주장할 수 없다. */
    public static final Set<LearningEventType> CLIENT_WRITABLE_TYPES =
            EnumSet.of(LearningEventType.USER_FEEDBACK_SAVED, LearningEventType.STUDY_LOG_CREATED);
    public static final int CLIENT_MAX_TEXT_CHARS = 4000;
    public static final int CLIENT_MAX_ACTION_CHARS = 100;

    /** 클라이언트 이벤트 검증 실패(HTTP 4xx + errorCode). */
    public static class ClientEventRejected extends RuntimeException {
        private final int status;
        private final String errorCode;

        public ClientEventRejected(int status, String errorCode, String message) {
            super(message);
            this.status = status;
            this.errorCode = errorCode;
        }

        public int status() { return status; }

        public String errorCode() { return errorCode; }
    }

    /** POST /api/learning-loop/events 요청(서버가 신뢰하지 않는 입력). */
    public record ClientEventRequest(String eventType, Long materialId, Long plannerId, Long wrongNoteId,
                                     String userMemo, String userAction, Set<String> fields) { }

    // 클라이언트가 보내면 거부하는 필드: AI 출력·채점 결과·출처 id 는 서버만 쓴다.
    private static final Set<String> CLIENT_FORBIDDEN_FIELDS = Set.of(
            "aiOutputSummary", "aiOutputJson", "inputText", "score", "isCorrect", "difficulty",
            "sourceType", "sourceId", "documentId", "quizId", "questionId", "roomId", "userId", "origin",
            "recommendedReviewDate", "recommendReviewInDays");

    @Transactional(propagation = Propagation.NOT_SUPPORTED)
    public LearningLoopEvent recordClientEvent(Long userId, ClientEventRequest req) {
        if (userId == null) {
            throw new ClientEventRejected(401, "AUTH_REQUIRED", "로그인이 필요합니다.");
        }
        if (req.fields() != null) {
            for (String f : req.fields()) {
                if (CLIENT_FORBIDDEN_FIELDS.contains(f)) {
                    throw new ClientEventRejected(400, "CLIENT_FIELD_NOT_ALLOWED", "클라이언트가 기록할 수 없는 필드입니다: " + f);
                }
            }
        }
        LearningEventType type;
        try {
            type = LearningEventType.valueOf(Objects.requireNonNull(req.eventType()).trim().toUpperCase());
        } catch (Exception e) {
            throw new ClientEventRejected(400, "EVENT_TYPE_INVALID", "eventType 이 올바르지 않습니다.");
        }
        if (!CLIENT_WRITABLE_TYPES.contains(type)) {
            throw new ClientEventRejected(403, "EVENT_TYPE_NOT_CLIENT_WRITABLE", "이 이벤트는 서버만 기록할 수 있습니다.");
        }
        String memo = req.userMemo();
        if (memo != null && memo.length() > CLIENT_MAX_TEXT_CHARS) {
            throw new ClientEventRejected(413, "EVENT_TEXT_TOO_LARGE", "메모가 너무 깁니다.");
        }
        String action = req.userAction();
        if (action != null && (action.length() > CLIENT_MAX_ACTION_CHARS || !action.matches("[A-Za-z0-9_\\-]+"))) {
            throw new ClientEventRejected(400, "USER_ACTION_INVALID", "userAction 형식이 올바르지 않습니다.");
        }
        if (req.materialId() != null && !ownsMaterial(userId, req.materialId())) {
            throw new ClientEventRejected(403, "MATERIAL_FORBIDDEN", "자료에 접근할 권한이 없습니다.");
        }
        if (req.plannerId() != null && !plannerRepository.findById(req.plannerId())
                .map(p -> userId.equals(p.getUserId())).orElse(false)) {
            throw new ClientEventRejected(403, "PLANNER_FORBIDDEN", "플래너에 접근할 권한이 없습니다.");
        }
        if (req.wrongNoteId() != null && reviewNoteRepository.findByReviewNoteIdAndUserId(req.wrongNoteId(), userId).isEmpty()) {
            throw new ClientEventRejected(403, "WRONG_NOTE_FORBIDDEN", "오답노트에 접근할 권한이 없습니다.");
        }
        LearningLoopEvent event = LearningLoopEvent.builder()
                .userId(userId)
                .eventType(type)
                .origin(LearningEventOrigin.CLIENT)
                .materialId(req.materialId())
                .plannerId(req.plannerId())
                .wrongNoteId(req.wrongNoteId())
                .userMemo(memo == null || memo.isBlank() ? null : memo)
                .userAction(action)
                .build();
        return eventWriter.write(event);
    }

    /** 학습일지 연결 기록. 제목+본문은 사용자 메모(사용자 주장)로만 저장하고, 원 이벤트·자료는 본인 것만 연결한다. */
    @Transactional(propagation = Propagation.NOT_SUPPORTED)
    public LearningLoopEvent recordStudyLog(Long userId, Long sourceEventId, Long materialId, String title, String content) {
        if (userId == null) {
            throw new ClientEventRejected(401, "AUTH_REQUIRED", "로그인이 필요합니다.");
        }
        String memo = ((title != null ? title.trim() : "") + (content != null && !content.isBlank() ? "\n" + content.trim() : "")).trim();
        if (memo.length() > CLIENT_MAX_TEXT_CHARS) {
            throw new ClientEventRejected(413, "EVENT_TEXT_TOO_LARGE", "학습일지 내용이 너무 깁니다.");
        }
        if (materialId != null && !ownsMaterial(userId, materialId)) {
            throw new ClientEventRejected(403, "MATERIAL_FORBIDDEN", "자료에 접근할 권한이 없습니다.");
        }
        if (sourceEventId != null && !eventRepository.findById(sourceEventId).map(e -> userId.equals(e.getUserId())).orElse(false)) {
            throw new ClientEventRejected(403, "EVENT_FORBIDDEN", "연결할 학습 이벤트에 접근할 권한이 없습니다.");
        }
        return eventWriter.write(LearningLoopEvent.builder()
                .userId(userId)
                .eventType(LearningEventType.STUDY_LOG_CREATED)
                .origin(LearningEventOrigin.CLIENT)
                .sourceType(LearningSourceType.STUDY_LOG)
                .sourceId(sourceEventId)
                .materialId(materialId)
                .userMemo(memo.isEmpty() ? null : memo)
                .userAction("STUDY_LOG_LINKED")
                .build());
    }

    private boolean ownsMaterial(Long userId, Long materialId) {
        return materialRepository.findById(materialId).map(m -> userId.equals(m.getUserId())).orElse(false);
    }

    // ------------------------------------------------------------------
    // 2) 이벤트 조회
    // ------------------------------------------------------------------

    public List<Map<String, Object>> queryEvents(Long userId, Long materialId, Long documentId,
                                                 LearningSourceType sourceType, Long sourceId, int limit) {
        PageRequest page = PageRequest.of(0, Math.max(1, Math.min(100, limit)));
        List<LearningLoopEvent> rows;
        if (sourceType != null && sourceId != null) {
            rows = eventRepository.findByUserIdAndSourceTypeAndSourceIdOrderByCreatedAtDesc(userId, sourceType, sourceId, page);
        } else if (materialId != null) {
            rows = eventRepository.findByUserIdAndMaterialIdOrderByCreatedAtDesc(userId, materialId, page);
        } else if (documentId != null) {
            rows = eventRepository.findByUserIdAndDocumentIdOrderByCreatedAtDesc(userId, documentId, page);
        } else {
            rows = eventRepository.findByUserIdOrderByCreatedAtDesc(userId, page);
        }
        List<Map<String, Object>> out = new ArrayList<>();
        for (LearningLoopEvent e : rows) out.add(toMap(e));
        return out;
    }

    // ------------------------------------------------------------------
    // 3) 컨텍스트 패키지 구성 (다음 AI 호출 근거)
    //    기록된 이벤트만 근거로 사용한다. 실제 참고할 내용이 없으면 빈 배열을 돌려준다(거짓 표시 방지).
    // ------------------------------------------------------------------

    /**
     * 범위 규칙:
     *  · materialId 와 documentId 는 서로 다른 식별자다 — documentId 를 materialId 로 바꿔 조회하지 않는다.
     *  · materialId 가 있으면 그 자료의 이벤트만, 없고 documentId 만 있으면 그 문서의 이벤트만, 둘 다 없으면 최근 이벤트.
     *  · 둘 다 오면 materialId 이벤트 중 documentId 가 다른(값이 있는) 행은 제외한다.
     *  · materialId 는 호출자 소유여야 한다(아니면 SecurityException → 403). 조회는 항상 userId 범위라 타 사용자 이벤트는 섞이지 않는다.
     *  · CLIENT 기록은 사용자 메모(사용자 주장)로만 쓰고 요약/오답/대화 같은 AI·시스템 기록 칸에 넣지 않는다.
     */
    public Map<String, Object> assembleContext(Long userId, Long materialId, Long documentId) {
        if (materialId != null && !ownsMaterial(userId, materialId)) {
            throw new SecurityException("자료에 접근할 권한이 없습니다.");
        }
        PageRequest page = PageRequest.of(0, 40);
        List<LearningLoopEvent> rows;
        if (materialId != null) {
            rows = eventRepository.findByUserIdAndMaterialIdOrderByCreatedAtDesc(userId, materialId, page);
            if (documentId != null) {
                rows = rows.stream().filter(e -> e.getDocumentId() == null || documentId.equals(e.getDocumentId())).toList();
            }
        } else if (documentId != null) {
            rows = eventRepository.findByUserIdAndDocumentIdOrderByCreatedAtDesc(userId, documentId, page);
        } else {
            rows = eventRepository.findByUserIdOrderByCreatedAtDesc(userId, page);
        }

        List<Map<String, Object>> summaries = new ArrayList<>();
        List<Map<String, Object>> wrongNotes = new ArrayList<>();
        List<Map<String, Object>> quizResults = new ArrayList<>();
        List<Map<String, Object>> plannerReviews = new ArrayList<>();
        List<String> userMemos = new ArrayList<>();
        List<Map<String, Object>> recentChatHistory = new ArrayList<>();

        for (LearningLoopEvent e : rows) {
            if (e.getOrigin() == LearningEventOrigin.CLIENT) {
                if (e.getUserMemo() != null && !e.getUserMemo().isBlank() && userMemos.size() < CONTEXT_LIMIT) {
                    userMemos.add(clip(e.getUserMemo()));
                }
                continue;
            }
            switch (e.getEventType()) {
                case MATERIAL_SUMMARY_GENERATED:
                    if (summaries.size() < CONTEXT_LIMIT) summaries.add(textItem("content", firstText(e)));
                    break;
                case WRONG_NOTE_CREATED:
                case QUIZ_WRONG_ANSWERED:
                case AI_EXPLANATION_GENERATED:
                    if (wrongNotes.size() < CONTEXT_LIMIT) wrongNotes.add(textItem("content", firstText(e)));
                    break;
                case QUIZ_SUBMITTED:
                    if (quizResults.size() < CONTEXT_LIMIT) {
                        Map<String, Object> q = new LinkedHashMap<>();
                        q.put("score", e.getScore());
                        q.put("difficulty", e.getDifficulty());
                        q.put("summary", firstText(e));
                        quizResults.add(q);
                    }
                    break;
                case PLANNER_REVIEW_CREATED:
                case REVIEW_SCHEDULE_RECOMMENDED:
                    if (plannerReviews.size() < CONTEXT_LIMIT) {
                        Map<String, Object> p = new LinkedHashMap<>();
                        p.put("title", firstText(e));
                        p.put("scheduledDate", e.getRecommendedReviewDate() != null ? e.getRecommendedReviewDate().toString() : null);
                        plannerReviews.add(p);
                    }
                    break;
                case AI_CHAT_ASKED:
                case AI_CHAT_ANSWERED:
                    if (recentChatHistory.size() < CONTEXT_LIMIT) recentChatHistory.add(textItem("text", firstText(e)));
                    break;
                default:
                    break;
            }
            if (e.getUserMemo() != null && !e.getUserMemo().isBlank() && userMemos.size() < CONTEXT_LIMIT) {
                userMemos.add(clip(e.getUserMemo()));
            }
        }

        Map<String, Object> ctx = new LinkedHashMap<>();
        ctx.put("recentSummaries", summaries);
        ctx.put("recentWrongNotes", wrongNotes);
        ctx.put("recentQuizResults", quizResults);
        ctx.put("recentPlannerReviews", plannerReviews);
        ctx.put("userMemos", userMemos);
        ctx.put("recentChatHistory", recentChatHistory);

        // 프론트 "이 답변은 ...을 참고했습니다" 표시를 위해 실제 참고 가능 여부를 같이 내려준다.
        boolean hasAny = !summaries.isEmpty() || !wrongNotes.isEmpty() || !quizResults.isEmpty()
                || !plannerReviews.isEmpty() || !userMemos.isEmpty() || !recentChatHistory.isEmpty();
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("learningLoopContext", ctx);
        out.put("hasContext", hasAny);
        out.put("usedSources", buildUsedSources(summaries, wrongNotes, userMemos, plannerReviews));
        Map<String, Object> scope = new LinkedHashMap<>();
        scope.put("materialId", materialId);
        scope.put("documentId", documentId);
        out.put("scope", scope);
        return out;
    }

    private List<String> buildUsedSources(List<?> summaries, List<?> wrongNotes, List<?> memos, List<?> plannerReviews) {
        List<String> used = new ArrayList<>();
        if (!summaries.isEmpty()) used.add("최근 요약");
        if (!wrongNotes.isEmpty()) used.add("최근 오답");
        if (!memos.isEmpty()) used.add("내 메모");
        if (!plannerReviews.isEmpty()) used.add("복습 일정");
        return used;
    }

    // ------------------------------------------------------------------
    // 4) 복습 추천일 계산 (결정적)
    // ------------------------------------------------------------------

    /** 결정적 복습 추천(난이도/오답수 → 간격·날짜·근거). ReviewNoteService/ScheduleRegistrationService 와 공유하는 단일 규칙. */
    public record ReviewRecommendation(int days, LocalDate date, String reason) {}

    public static ReviewRecommendation computeReviewRecommendation(String difficulty, Integer wrongCount, LocalDate base) {
        String diff = difficulty == null ? "" : difficulty.trim().toLowerCase();
        int days;
        String reason;
        // 어려울수록·오답이 많을수록 더 빨리 복습한다(망각곡선 단순화).
        if (diff.contains("hard") || diff.contains("어려") || diff.equals("상")) {
            days = 1;
        } else if (diff.contains("easy") || diff.contains("쉬") || diff.equals("하")) {
            days = 7;
        } else {
            days = 3;
        }
        if (wrongCount != null && wrongCount >= 5 && days > 1) days -= 1;

        if (days <= 1) reason = "틀린 문항이 많거나 난이도가 높아 빠른 복습이 필요합니다.";
        else if (days >= 7) reason = "비교적 쉬운 내용이라 일주일 뒤 가볍게 다시 확인하면 좋습니다.";
        else reason = "기억이 흐려지기 전, 며칠 안에 한 번 더 복습하면 정착에 효과적입니다.";

        LocalDate from = base != null ? base : LocalDate.now();
        return new ReviewRecommendation(days, from.plusDays(days), reason);
    }

    public Map<String, Object> recommendReview(Long userId, Long materialId, Long wrongNoteId, String difficulty,
                                               Integer wrongCount) {
        // 오답노트가 지정됐고 DB 에 추천일이 이미 있으면 그 값을 그대로 돌려준다(DB 가 source of truth).
        ReviewNote stored = wrongNoteId != null
                ? reviewNoteRepository.findByReviewNoteIdAndUserId(wrongNoteId, userId).orElse(null) : null;
        ReviewRecommendation rec;
        if (stored != null && stored.getRecommendedReviewDate() != null) {
            rec = new ReviewRecommendation(
                    stored.getRecommendReviewInDays() != null ? stored.getRecommendReviewInDays() : 0,
                    stored.getRecommendedReviewDate(),
                    stored.getReviewReason() != null ? stored.getReviewReason() : "");
        } else {
            rec = computeReviewRecommendation(difficulty, wrongCount, LocalDate.now());
        }
        int days = rec.days();
        String reason = rec.reason();
        LocalDate date = rec.date();

        // 추천 자체도 이벤트로 남긴다(루프 추적).
        recordSafe(LearningLoopEvent.builder()
                .userId(userId)
                .eventType(LearningEventType.REVIEW_SCHEDULE_RECOMMENDED)
                .sourceType(wrongNoteId != null ? LearningSourceType.WRONG_NOTE : LearningSourceType.MATERIAL)
                .sourceId(wrongNoteId != null ? wrongNoteId : materialId)
                .materialId(materialId)
                .wrongNoteId(wrongNoteId)
                .difficulty(difficulty)
                .recommendReviewInDays(days)
                .recommendedReviewDate(date)
                .aiOutputSummary(reason)
                .userAction("REVIEW_RECOMMENDED")
                .build());

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("recommendReviewInDays", days);
        out.put("recommendedReviewDate", date.toString());
        out.put("reviewReason", reason);
        return out;
    }

    // ------------------------------------------------------------------
    // 5) 복습 일정 → 플래너(주간일정) 등록
    // ------------------------------------------------------------------

    // 5) 복습 일정 → 주간 일정(todos) 등록은 ScheduleRegistrationService 가 소유한다(LearningLoopController 가 직접 호출).
    //    (과거엔 여기서 planners 에 REVIEW_AUTO 행을 만들어 주간 일정 화면(todos)에 나타나지 않았다.)

    // ------------------------------------------------------------------
    // 헬퍼
    // ------------------------------------------------------------------

    private String firstText(LearningLoopEvent e) {
        if (e.getAiOutputSummary() != null && !e.getAiOutputSummary().isBlank()) return clip(e.getAiOutputSummary());
        if (e.getInputText() != null && !e.getInputText().isBlank()) return clip(e.getInputText());
        if (e.getAiOutputJson() != null && !e.getAiOutputJson().isBlank()) return clip(e.getAiOutputJson());
        return "";
    }

    private String clip(String s) {
        s = s.trim();
        return s.length() <= 800 ? s : s.substring(0, 800);
    }

    private Map<String, Object> textItem(String key, String value) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put(key, value);
        return m;
    }

    private Map<String, Object> toMap(LearningLoopEvent e) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", e.getId());
        m.put("eventType", e.getEventType() != null ? e.getEventType().name() : null);
        m.put("sourceType", e.getSourceType() != null ? e.getSourceType().name() : null);
        m.put("sourceId", e.getSourceId());
        m.put("materialId", e.getMaterialId());
        m.put("documentId", e.getDocumentId());
        m.put("wrongNoteId", e.getWrongNoteId());
        m.put("quizId", e.getQuizId());
        m.put("plannerId", e.getPlannerId());
        m.put("aiOutputSummary", e.getAiOutputSummary());
        m.put("userAction", e.getUserAction());
        m.put("userMemo", e.getUserMemo());
        m.put("isCorrect", e.getIsCorrect());
        m.put("score", e.getScore());
        m.put("difficulty", e.getDifficulty());
        m.put("recommendedReviewDate", e.getRecommendedReviewDate() != null ? e.getRecommendedReviewDate().toString() : null);
        m.put("createdAt", e.getCreatedAt() != null ? e.getCreatedAt().toString() : null);
        return m;
    }
}
