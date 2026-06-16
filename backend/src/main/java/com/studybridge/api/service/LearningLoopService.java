package com.studybridge.api.service;

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

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 학습 왕복 루프(Learning Loop)의 중심 서비스.
 *
 *  1) record / recordSafe : 학습·AI 행동을 LearningLoopEvent 로 영속화한다(best-effort).
 *  2) queryEvents         : materialId/documentId/source 기준으로 이벤트 이력을 조회한다.
 *  3) assembleContext     : 다음 AI 호출에 붙일 learningLoopContext 패키지를 구성한다.
 *  4) recommendReview     : 난이도/오답 수 기반으로 복습 추천일을 결정적으로 계산한다.
 *  5) registerReviewSchedule : 추천 복습일을 플래너(주간일정)에 등록한다(+이벤트 기록).
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
    private final PlannerRepository plannerRepository;
    private final MaterialRepository materialRepository;
    private final ReviewNoteRepository reviewNoteRepository;

    // ------------------------------------------------------------------
    // 1) 이벤트 기록
    // ------------------------------------------------------------------

    /** 새 트랜잭션에서 이벤트를 저장한다(호출자 트랜잭션이 readOnly여도 안전). */
    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public LearningLoopEvent record(LearningLoopEvent event) {
        if (event.getUserId() == null || event.getEventType() == null) {
            throw new IllegalArgumentException("userId, eventType 은 필수입니다.");
        }
        return eventRepository.save(event);
    }

    /**
     * 이벤트 기록 실패가 본래 기능을 절대 깨뜨리지 않도록 감싼 버전.
     * 다른 서비스(오답노트/플래너/채팅 등)에서 호출한다.
     */
    public Long recordSafe(LearningLoopEvent event) {
        try {
            return record(event).getId();
        } catch (Exception e) {
            log.warn("[LEARNING_LOOP] record skipped userId={} type={} cause={}",
                    event != null ? event.getUserId() : null,
                    event != null ? event.getEventType() : null,
                    e.getClass().getSimpleName() + ": " + e.getMessage());
            return null;
        }
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

    public Map<String, Object> assembleContext(Long userId, Long materialId, Long documentId) {
        Long mid = materialId != null ? materialId : documentId;
        PageRequest page = PageRequest.of(0, 40);
        List<LearningLoopEvent> rows = mid != null
                ? eventRepository.findByUserIdAndMaterialIdOrderByCreatedAtDesc(userId, mid, page)
                : eventRepository.findByUserIdOrderByCreatedAtDesc(userId, page);

        List<Map<String, Object>> summaries = new ArrayList<>();
        List<Map<String, Object>> wrongNotes = new ArrayList<>();
        List<Map<String, Object>> quizResults = new ArrayList<>();
        List<Map<String, Object>> plannerReviews = new ArrayList<>();
        List<String> userMemos = new ArrayList<>();
        List<Map<String, Object>> recentChatHistory = new ArrayList<>();

        for (LearningLoopEvent e : rows) {
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
                userMemos.add(e.getUserMemo());
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

    public Map<String, Object> recommendReview(Long userId, Long materialId, Long wrongNoteId, String difficulty,
                                               Integer wrongCount) {
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

        LocalDate date = LocalDate.now().plusDays(days);

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

    @Transactional
    public Map<String, Object> registerReviewSchedule(Long userId, Long materialId, Long wrongNoteId,
                                                      String title, LocalDate scheduledDate, String reason) {
        // 소유권 검증
        if (materialId != null) {
            Material m = materialRepository.findById(materialId).orElse(null);
            if (m != null && !userId.equals(m.getUserId())) {
                throw new SecurityException("해당 자료에 대한 권한이 없습니다.");
            }
        }
        ReviewNote note = null;
        if (wrongNoteId != null) {
            note = reviewNoteRepository.findByReviewNoteIdAndUserId(wrongNoteId, userId)
                    .orElseThrow(() -> new SecurityException("해당 오답노트에 대한 권한이 없습니다."));
            if (materialId == null) materialId = note.getSourceMaterialId();
        }

        LocalDate date = scheduledDate != null ? scheduledDate : LocalDate.now().plusDays(3);
        String safeTitle = buildReviewTitle(title, note);
        String content = (reason != null && !reason.isBlank())
                ? reason
                : "이전 학습 내용을 복습합니다.";

        Planner planner = Planner.builder()
                .userId(userId)
                .title(safeTitle)
                .year(date.getYear())
                .month(date.getMonthValue())
                .day(date.getDayOfMonth())
                .plannerDate(date)
                .dayOfWeek(koreanDayOfWeek(date))
                .studyType("강의 복습")
                .priority("높음")
                .content(content)
                .materialId(materialId)
                .sourceType("REVIEW_AUTO")
                .sourceMaterialId(materialId)
                .build();
        planner = plannerRepository.save(planner);

        recordSafe(LearningLoopEvent.builder()
                .userId(userId)
                .eventType(LearningEventType.PLANNER_REVIEW_CREATED)
                .sourceType(LearningSourceType.PLANNER)
                .sourceId(planner.getId())
                .materialId(materialId)
                .wrongNoteId(wrongNoteId)
                .plannerId(planner.getId())
                .recommendedReviewDate(date)
                .aiOutputSummary(safeTitle)
                .userAction("REVIEW_SCHEDULED")
                .build());

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("plannerId", planner.getId());
        out.put("title", safeTitle);
        out.put("scheduledDate", date.toString());
        return out;
    }

    /** 복습 일정 제목. 교수명/연도/무의미 문자열을 임의로 넣지 않는다. */
    private String buildReviewTitle(String requested, ReviewNote note) {
        if (requested != null && !requested.isBlank()) {
            String t = requested.trim();
            return t.startsWith("[복습]") ? t : "[복습] " + t;
        }
        String src = note != null ? note.getSourceTitle() : null;
        if (src == null || src.isBlank()) src = "학습 내용";
        return "[복습] " + src.trim() + " 복습";
    }

    private String koreanDayOfWeek(LocalDate date) {
        switch (date.getDayOfWeek()) {
            case MONDAY: return "월";
            case TUESDAY: return "화";
            case WEDNESDAY: return "수";
            case THURSDAY: return "목";
            case FRIDAY: return "금";
            case SATURDAY: return "토";
            default: return "일";
        }
    }

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
