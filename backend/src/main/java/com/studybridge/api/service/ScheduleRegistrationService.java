package com.studybridge.api.service;

import com.studybridge.api.entity.LearningEventType;
import com.studybridge.api.entity.LearningLoopEvent;
import com.studybridge.api.entity.LearningSourceType;
import com.studybridge.api.entity.Planner;
import com.studybridge.api.entity.ReviewNote;
import com.studybridge.api.entity.Todo;
import com.studybridge.api.entity.User;
import com.studybridge.api.repository.PlannerRepository;
import com.studybridge.api.repository.ReviewNoteRepository;
import com.studybridge.api.repository.TodoRepository;
import com.studybridge.api.repository.UserRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;

import java.time.DateTimeException;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.NoSuchElementException;
import java.util.Optional;

/**
 * 주간 일정 등록의 단일 소유자.
 *
 *  주간 일정 화면(/weekly-schedule)이 실제로 읽는 persistence 는 {@link Todo}(todos 테이블, GET /api/todos)다.
 *  복습 일정(오답노트)과 플래너 일정은 모두 이 테이블에 transaction 으로 기록되며,
 *  (user_id, source_type, source_id, schedule_date) 기준 idempotent 하다 — 반복 클릭은 기존 row 를 반환한다.
 *
 *  · 복습: ai07 를 다시 호출하지 않는다. review_notes.recommended_review_date(없으면 결정적 규칙으로 즉시 확정·저장)를 쓴다.
 *  · 플래너: 제목 = planners.title 그대로, 날짜 = LocalDate.of(year, month, day) (day_of_week/브라우저 날짜/로드맵 위치 미사용).
 *            time_table_json 이 있으면 응답에 실어 주지만, 없어도 등록은 가능하다(ai07 분석 성공 여부와 무관).
 *  · 성공 응답은 커밋 대상 row 를 재조회한 뒤에만 만든다. DB 오류/검증 실패는 예외 → rollback → 4xx/5xx (가짜 성공 없음).
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ScheduleRegistrationService {

    public static final String SOURCE_REVIEW_NOTE = "REVIEW_NOTE";
    public static final String SOURCE_PLANNER = "PLANNER";
    /** AI 학습 내비게이터가 제안하고 사용자가 승인한 학습 세션(source_id = plannerId, 같은 플래너·날짜는 1건). */
    public static final String SOURCE_ADAPTIVE_SESSION = "ADAPTIVE_SESSION";

    /** 학습 세션 등록 결과. state = CREATED | UPDATED(분 변경) | UNCHANGED(이미 같은 내용). */
    public record SessionResult(Long todoId, String title, LocalDate scheduleDate, String state) {}

    private final TodoRepository todoRepository;
    private final UserRepository userRepository;
    private final ReviewNoteRepository reviewNoteRepository;
    private final PlannerRepository plannerRepository;
    private final LearningLoopService learningLoopService;
    private final PlatformTransactionManager transactionManager;

    /**
     * 등록 트랜잭션은 명시적 TransactionTemplate(REQUIRES_NEW, read-write)로 연다.
     *  같은 클래스 내부 호출은 @Transactional 프록시를 타지 않으므로(self-invocation) 어노테이션 방식은 쓰지 않는다.
     *  learning_loop_events 기록은 커밋 이후 별도 트랜잭션(best-effort)으로 남겨 일정 등록 자체를 절대 오염시키지 않는다.
     */
    private TransactionTemplate readWriteTx() {
        TransactionTemplate t = new TransactionTemplate(transactionManager);
        t.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
        t.setReadOnly(false);
        return t;
    }

    /** 등록 결과. created=false 면 이미 존재하던 row(idempotent success). */
    public record Result(Long todoId, String title, LocalDate scheduledDate, boolean created,
                         String sourceType, Long sourceId, Boolean completed, Map<String, Object> extra) {
        public Map<String, Object> toMap() {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("todoId", todoId);
            m.put("title", title);
            m.put("scheduledDate", scheduledDate != null ? scheduledDate.toString() : null);
            m.put("created", created);
            m.put("alreadyRegistered", !created);
            m.put("sourceType", sourceType);
            m.put("sourceId", sourceId);
            m.put("completed", completed);
            m.put("message", created ? "주간 일정에 등록되었습니다." : "이미 등록되어 있습니다.");
            if (extra != null) m.putAll(extra);
            m.remove("materialId");
            return m;
        }
    }

    // ------------------------------------------------------------------
    // 복습 일정(오답노트) → todos
    // ------------------------------------------------------------------

    /** 외부 진입점: unique index 경합(DataIntegrityViolation)이 나면 기존 row 를 재조회해 idempotent 로 돌려준다. */
    public Result registerReviewNote(Long userId, Long reviewNoteId, String requestedTitle) {
        try {
            Result r = readWriteTx().execute(status -> registerReviewNoteTx(userId, reviewNoteId, requestedTitle));
            if (r != null && r.created()) {
                recordAfterCommit(r, userId, reviewNoteId);
            }
            return r;
        } catch (DataIntegrityViolationException dup) {
            log.info("[SCHEDULE] review-note 중복 등록 경합 userId={} reviewNoteId={} → 기존 row 반환", userId, reviewNoteId);
            ReviewNote note = reviewNoteRepository.findByReviewNoteIdAndUserId(reviewNoteId, userId)
                    .orElseThrow(() -> new NoSuchElementException("오답노트를 찾을 수 없습니다."));
            LocalDate date = note.getRecommendedReviewDate() != null ? note.getRecommendedReviewDate() : LocalDate.now();
            Todo existing = findExisting(userId, SOURCE_REVIEW_NOTE, reviewNoteId, date)
                    .orElseThrow(() -> dup);
            return toResult(existing, false, null);
        }
    }

    private Result registerReviewNoteTx(Long userId, Long reviewNoteId, String requestedTitle) {
        if (reviewNoteId == null) throw new IllegalArgumentException("wrongNoteId(오답노트 id)가 필요합니다.");
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new NoSuchElementException("사용자를 찾을 수 없습니다."));
        ReviewNote note = reviewNoteRepository.findByReviewNoteIdAndUserId(reviewNoteId, userId)
                .orElseThrow(() -> new SecurityException("해당 오답노트에 대한 권한이 없습니다."));

        // 추천 복습일이 아직 없으면(레거시 row) 같은 트랜잭션에서 결정적으로 확정·저장한다. ai07 호출 없음.
        if (note.getRecommendedReviewDate() == null) {
            int cnt = nz(note.getWrongCount()) + nz(note.getUnansweredCount());
            LocalDate base = note.getCreatedAt() != null ? note.getCreatedAt().toLocalDate() : LocalDate.now();
            LearningLoopService.ReviewRecommendation rec = LearningLoopService.computeReviewRecommendation(note.getDifficulty(), cnt, base);
            note.setRecommendReviewInDays(rec.days());
            note.setRecommendedReviewDate(rec.date());
            note.setReviewReason(rec.reason());
            reviewNoteRepository.save(note);
        }
        LocalDate date = note.getRecommendedReviewDate();
        String title = buildReviewTitle(requestedTitle, note);

        Optional<Todo> existing = findExisting(userId, SOURCE_REVIEW_NOTE, reviewNoteId, date);
        if (existing.isPresent()) {
            return toResult(existing.get(), false, reviewExtra(note));
        }
        Todo todo = Todo.builder()
                .user(user)
                .text(title)
                .completed(false)
                .startDate(LocalDateTime.of(date, LocalTime.MIDNIGHT))
                .endDate(LocalDateTime.of(date, LocalTime.of(23, 59, 59)))
                .sourceType(SOURCE_REVIEW_NOTE)
                .sourceId(reviewNoteId)
                .scheduleDate(date)
                .build();
        todo = todoRepository.saveAndFlush(todo);
        // 커밋 대상 row 재조회(실제 생성 확인) — 없으면 예외 → rollback.
        Todo persisted = todoRepository.findById(todo.getId())
                .orElseThrow(() -> new IllegalStateException("주간 일정 row 생성을 확인하지 못했습니다."));
        log.info("[SCHEDULE] review-note 등록 userId={} reviewNoteId={} todoId={} date={} title=\"{}\"",
                userId, reviewNoteId, persisted.getId(), date, title);
        Map<String, Object> extra = reviewExtra(note);
        extra.put("materialId", note.getSourceMaterialId());
        return toResult(persisted, true, extra);
    }

    /** 커밋 이후 학습 루프 이벤트(best-effort, REQUIRES_NEW read-write). 실패해도 등록 결과에 영향 없음. */
    private void recordAfterCommit(Result r, Long userId, Long reviewNoteId) {
        try {
            Object materialId = r.extra() != null ? r.extra().get("materialId") : null;
            Object days = r.extra() != null ? r.extra().get("recommendReviewInDays") : null;
            learningLoopService.record(LearningLoopEvent.builder()
                    .userId(userId)
                    .eventType(LearningEventType.PLANNER_REVIEW_CREATED)
                    .sourceType(LearningSourceType.WRONG_NOTE)
                    .sourceId(reviewNoteId)
                    .materialId(materialId instanceof Long l ? l : null)
                    .wrongNoteId(reviewNoteId)
                    .recommendReviewInDays(days instanceof Integer i ? i : null)
                    .recommendedReviewDate(r.scheduledDate())
                    .aiOutputSummary(r.title())
                    .userAction("REVIEW_SCHEDULED")
                    .build());
        } catch (Exception e) {
            log.warn("[SCHEDULE] learning-loop event skipped (todoId={}): {}", r.todoId(), e.getMessage());
        }
    }

    private Map<String, Object> reviewExtra(ReviewNote note) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("reviewNoteId", note.getReviewNoteId());
        m.put("recommendedReviewDate", note.getRecommendedReviewDate() != null ? note.getRecommendedReviewDate().toString() : null);
        m.put("recommendReviewInDays", note.getRecommendReviewInDays());
        m.put("reviewReason", note.getReviewReason());
        return m;
    }

    /** 복습 일정 제목. 교수명/연도/무의미 문자열을 임의로 넣지 않는다. */
    static String buildReviewTitle(String requested, ReviewNote note) {
        if (requested != null && !requested.isBlank()) {
            String t = requested.trim();
            return clip(t.startsWith("[복습]") ? t : "[복습] " + t);
        }
        String src = note != null ? note.getSourceTitle() : null;
        if (src == null || src.isBlank()) src = note != null && note.getTitle() != null ? note.getTitle() : "학습 내용";
        return clip("[복습] " + src.trim() + " 오답 복습");
    }

    // ------------------------------------------------------------------
    // 플래너 → todos
    // ------------------------------------------------------------------

    public Result registerPlanner(Long userId, Long plannerId) {
        try {
            return readWriteTx().execute(status -> registerPlannerTx(userId, plannerId));
        } catch (DataIntegrityViolationException dup) {
            log.info("[SCHEDULE] planner 중복 등록 경합 userId={} plannerId={} → 기존 row 반환", userId, plannerId);
            Planner planner = plannerRepository.findById(plannerId)
                    .orElseThrow(() -> new NoSuchElementException("플래너를 찾을 수 없습니다."));
            LocalDate date = plannerDate(planner);
            Todo existing = findExisting(userId, SOURCE_PLANNER, plannerId, date).orElseThrow(() -> dup);
            return toResult(existing, false, plannerExtra(planner, date));
        }
    }

    private Result registerPlannerTx(Long userId, Long plannerId) {
        if (plannerId == null) throw new IllegalArgumentException("plannerId 가 필요합니다.");
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new NoSuchElementException("사용자를 찾을 수 없습니다."));
        Planner planner = plannerRepository.findById(plannerId)
                .orElseThrow(() -> new NoSuchElementException("플래너를 찾을 수 없습니다."));
        if (!userId.equals(planner.getUserId())) {
            throw new SecurityException("해당 플래너에 대한 권한이 없습니다.");
        }
        // 날짜 source of truth = planners.year + month + day. 검증 실패(예: 2월 30일, null)는 400.
        LocalDate date = plannerDate(planner);
        String title = planner.getTitle() == null || planner.getTitle().isBlank()
                ? "플래너 " + planner.getId() : clip(planner.getTitle().trim());
        // planner_date 는 이 값과 동기화(날짜 원천은 뒤집지 않는다).
        if (planner.getPlannerDate() == null || !planner.getPlannerDate().equals(date)) {
            planner.setPlannerDate(date);
            plannerRepository.save(planner);
        }

        Optional<Todo> existing = findExisting(userId, SOURCE_PLANNER, plannerId, date);
        if (existing.isPresent()) {
            return toResult(existing.get(), false, plannerExtra(planner, date));
        }
        Todo todo = Todo.builder()
                .user(user)
                .text(title)
                .completed(false)
                .startDate(LocalDateTime.of(date, LocalTime.MIDNIGHT))
                .endDate(LocalDateTime.of(date, LocalTime.of(23, 59, 59)))
                .sourceType(SOURCE_PLANNER)
                .sourceId(plannerId)
                .scheduleDate(date)
                .build();
        todo = todoRepository.saveAndFlush(todo);
        Todo persisted = todoRepository.findById(todo.getId())
                .orElseThrow(() -> new IllegalStateException("주간 일정 row 생성을 확인하지 못했습니다."));
        log.info("[SCHEDULE] planner 등록 userId={} plannerId={} todoId={} date={} title=\"{}\"",
                userId, plannerId, persisted.getId(), date, title);
        return toResult(persisted, true, plannerExtra(planner, date));
    }

    /** planners.year/month/day → LocalDate. null/범위 밖 값은 IllegalArgumentException(400). */
    static LocalDate plannerDate(Planner planner) {
        Integer y = planner.getYear(), m = planner.getMonth(), d = planner.getDay();
        if (y == null || m == null || d == null) {
            throw new IllegalArgumentException("플래너의 년/월/일이 비어 있어 일정을 등록할 수 없습니다. (year=" + y + ", month=" + m + ", day=" + d + ")");
        }
        try {
            return LocalDate.of(y, m, d);
        } catch (DateTimeException e) {
            throw new IllegalArgumentException("플래너 날짜가 올바르지 않습니다: " + y + "-" + m + "-" + d);
        }
    }

    private Map<String, Object> plannerExtra(Planner planner, LocalDate date) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("plannerId", planner.getId());
        m.put("plannerTitle", planner.getTitle());
        m.put("year", planner.getYear());
        m.put("month", planner.getMonth());
        m.put("day", planner.getDay());
        m.put("plannerDate", date.toString());
        // 상세 시간표가 이미 있으면 그대로 실어 준다(없어도 등록은 성공).
        m.put("hasTimeTable", planner.getTimeTableJson() != null && !planner.getTimeTableJson().isBlank());
        m.put("timeTableJson", planner.getTimeTableJson());
        return m;
    }

    // ------------------------------------------------------------------
    // AI 학습 내비게이터 학습 세션 → todos
    // ------------------------------------------------------------------

    /**
     * 승인된 학습 세션 1건을 주간 일정에 기록한다. 호출자 트랜잭션 안에서만 실행한다(MANDATORY) — 여러 세션·플래너 변경을
     * 하나의 트랜잭션으로 묶어 일부만 저장되는 일이 없게 한다. (user, ADAPTIVE_SESSION, plannerId, date) 는 RDS 부분 unique index
     * uk_todos_source_schedule 로 중복이 막히며, 동시 경합은 호출자가 DataIntegrityViolation 을 받아 다시 시도한다.
     */
    @org.springframework.transaction.annotation.Transactional(propagation = org.springframework.transaction.annotation.Propagation.MANDATORY)
    public SessionResult upsertStudySession(Long userId, Planner planner, LocalDate date, int minutes) {
        if (planner == null || !userId.equals(planner.getUserId())) {
            throw new SecurityException("해당 플래너에 대한 권한이 없습니다.");
        }
        if (date == null || minutes < 1 || minutes > 240) {
            throw new IllegalArgumentException("학습 세션 날짜·시간이 올바르지 않습니다.");
        }
        String text = studySessionTitle(planner, minutes);
        Optional<Todo> existing = findExisting(userId, SOURCE_ADAPTIVE_SESSION, planner.getId(), date);
        if (existing.isPresent()) {
            Todo t = existing.get();
            if (text.equals(t.getText())) return new SessionResult(t.getId(), t.getText(), date, "UNCHANGED");
            t.setText(text);
            Todo saved = todoRepository.saveAndFlush(t);
            log.info("[SCHEDULE] adaptive session 갱신 userId={} plannerId={} todoId={} date={} minutes={}",
                    userId, planner.getId(), saved.getId(), date, minutes);
            return new SessionResult(saved.getId(), saved.getText(), date, "UPDATED");
        }
        User user = userRepository.findById(userId)
                .orElseThrow(() -> new NoSuchElementException("사용자를 찾을 수 없습니다."));
        Todo todo = todoRepository.saveAndFlush(Todo.builder()
                .user(user)
                .text(text)
                .completed(false)
                .startDate(LocalDateTime.of(date, LocalTime.MIDNIGHT))
                .endDate(LocalDateTime.of(date, LocalTime.of(23, 59, 59)))
                .sourceType(SOURCE_ADAPTIVE_SESSION)
                .sourceId(planner.getId())
                .scheduleDate(date)
                .build());
        log.info("[SCHEDULE] adaptive session 등록 userId={} plannerId={} todoId={} date={} minutes={}",
                userId, planner.getId(), todo.getId(), date, minutes);
        return new SessionResult(todo.getId(), todo.getText(), date, "CREATED");
    }

    /** 이미 같은 내용으로 등록돼 있는지(재반영 판정용, 쓰기 없음). */
    public boolean hasStudySession(Long userId, Planner planner, LocalDate date, int minutes) {
        return findExisting(userId, SOURCE_ADAPTIVE_SESSION, planner.getId(), date)
                .map(t -> studySessionTitle(planner, minutes).equals(t.getText()))
                .orElse(false);
    }

    /** "[AI 학습 30분] 플래너 제목". 제목은 planners.title 그대로(AI 가 만든 학습명을 쓰지 않는다). */
    public static String studySessionTitle(Planner planner, int minutes) {
        String t = planner.getTitle() == null || planner.getTitle().isBlank() ? "플래너 " + planner.getId() : planner.getTitle().trim();
        return clip("[AI 학습 " + minutes + "분] " + t);
    }

    // ------------------------------------------------------------------
    // 공통
    // ------------------------------------------------------------------

    public Optional<Todo> findExisting(Long userId, String sourceType, Long sourceId, LocalDate date) {
        return todoRepository.findFirstByUserIdAndSourceTypeAndSourceIdAndScheduleDateOrderByIdAsc(userId, sourceType, sourceId, date);
    }

    private static Result toResult(Todo t, boolean created, Map<String, Object> extra) {
        return new Result(t.getId(), t.getText(), t.getScheduleDate(), created, t.getSourceType(), t.getSourceId(), t.getCompleted(), extra);
    }

    private static int nz(Integer v) {
        return v == null ? 0 : v;
    }

    private static String clip(String s) {
        return s.length() > 250 ? s.substring(0, 250) : s;
    }
}
