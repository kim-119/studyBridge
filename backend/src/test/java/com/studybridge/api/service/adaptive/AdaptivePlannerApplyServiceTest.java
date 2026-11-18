package com.studybridge.api.service.adaptive;

import static com.studybridge.api.service.adaptive.AdaptiveFixtures.OTHER;
import static com.studybridge.api.service.adaptive.AdaptiveFixtures.TODAY;
import static com.studybridge.api.service.adaptive.AdaptiveFixtures.USER;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.entity.Planner;
import com.studybridge.api.entity.Todo;
import com.studybridge.api.entity.User;
import com.studybridge.api.repository.FolderRepository;
import com.studybridge.api.repository.MaterialRepository;
import com.studybridge.api.repository.ReviewNoteRepository;
import com.studybridge.api.repository.TodoRepository;
import com.studybridge.api.repository.UserRepository;
import com.studybridge.api.service.LearningLoopService;
import com.studybridge.api.service.PlannerService;
import com.studybridge.api.service.S3Service;
import com.studybridge.api.service.ScheduleRegistrationService;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.HttpStatus;
import org.springframework.transaction.PlatformTransactionManager;

/**
 * "일정에 반영": 토큰 안의 승인된 후보만, 최신 DB 재검증 뒤, 주간 일정(todos)·기존 플래너 수정 경로로 저장하고 다시 읽는다.
 * 중복 반영 멱등·stale/날짜 경과 409·변조/타인 토큰 400·unique 경합 재시도.
 */
class AdaptivePlannerApplyServiceTest {

    private final ObjectMapper om = new ObjectMapper();
    private AdaptiveFixtures f;
    private AdaptivePlannerClient client;
    private AdaptiveProposalSigner signer;
    private AdaptivePlannerService service;
    private AdaptivePlannerApplyService apply;
    private final List<Todo> todos = new ArrayList<>();
    private final AtomicLong todoIds = new AtomicLong(5000);
    private final AtomicInteger todoWrites = new AtomicInteger();
    private final AtomicBoolean raceOnce = new AtomicBoolean(false);
    private ScheduleRegistrationService schedule;
    private PlannerService plannerService;

    @BeforeEach
    void setUp() {
        f = new AdaptiveFixtures();
        when(f.plannerRepository.save(any(Planner.class))).thenAnswer(inv -> {
            Planner p = inv.getArgument(0);
            f.planners.put(p.getId(), p);
            return p;
        });
        client = mock(AdaptivePlannerClient.class);
        signer = new AdaptiveProposalSigner("test-secret", Duration.ofMinutes(30), om, AdaptivePlannerServiceTest.CLOCK);
        service = new AdaptivePlannerService(f.builder, client, signer, mock(PlatformTransactionManager.class), AdaptivePlannerServiceTest.CLOCK);

        TodoRepository todoRepository = mock(TodoRepository.class);
        when(todoRepository.findFirstByUserIdAndSourceTypeAndSourceIdAndScheduleDateOrderByIdAsc(anyLong(), anyString(), anyLong(), any()))
                .thenAnswer(inv -> todos.stream().filter(t -> t.getUser().getId().equals(inv.getArgument(0))
                        && t.getSourceType().equals(inv.getArgument(1)) && t.getSourceId().equals(inv.getArgument(2))
                        && t.getScheduleDate().equals(inv.getArgument(3))).findFirst());
        when(todoRepository.saveAndFlush(any(Todo.class))).thenAnswer(inv -> {
            Todo t = inv.getArgument(0);
            if (t.getId() == null) {
                boolean dup = todos.stream().anyMatch(o -> o.getUser().getId().equals(t.getUser().getId()) && o.getSourceType().equals(t.getSourceType())
                        && o.getSourceId().equals(t.getSourceId()) && o.getScheduleDate().equals(t.getScheduleDate()));
                if (dup) throw new DataIntegrityViolationException("uk_todos_source_schedule");
                t.setId(todoIds.incrementAndGet());
                todos.add(t);
                if (raceOnce.compareAndSet(true, false)) {
                    throw new DataIntegrityViolationException("uk_todos_source_schedule (동시 요청)");
                }
            }
            todoWrites.incrementAndGet();
            return t;
        });
        UserRepository users = mock(UserRepository.class);
        when(users.findById(anyLong())).thenAnswer(inv -> Optional.of(User.builder().id(inv.getArgument(0)).build()));
        schedule = new ScheduleRegistrationService(todoRepository, users, mock(ReviewNoteRepository.class), f.plannerRepository,
                mock(LearningLoopService.class), mock(PlatformTransactionManager.class));
        plannerService = new PlannerService(f.plannerRepository, mock(MaterialRepository.class), mock(S3Service.class), om, mock(FolderRepository.class));
        apply = new AdaptivePlannerApplyService(signer, f.builder, service, schedule, plannerService, f.plannerRepository,
                mock(PlatformTransactionManager.class));
    }

    private void manual() {
        f.userPlanner(21, USER, "Java 예외 처리 복습", TODAY.plusDays(1), "보통", "2026-10-31");
        f.userPlanner(22, USER, "SQLD 기출문제 풀이", TODAY, "높음", "2026-10-29");
        f.checklist(f.userPlanner(23, USER, "네트워크 OSI 7계층", TODAY.minusDays(1), "보통", null), true);
        Planner p24 = f.userPlanner(24, USER, "미적분 문제 풀이", TODAY.minusDays(3), null, "2026-10-27");
        p24.setGoalTime("1시간");
        p24.setTmi("메모 유지");
        p24.setDayOfWeek("일");
        f.checklist(f.planners.get(22L), false, false);
    }

    private static final Map<String, String> MANUAL_IDS = Map.of("\\b9001\\b", "21", "\\b9002\\b", "22", "\\b9003\\b", "23", "\\b9004\\b", "24");
    private static final Map<String, String> ROADMAP_IDS = Map.of("\"cnn-3\"", "13", "\"cnn-2\"", "12", "\"cnn-1\"", "11", "\"cnn-4\"", "14");

    private Map<String, Object> recommendManual() throws Exception {
        manual();
        when(client.recommend(any(), anyString())).thenReturn(AdaptivePlannerServiceTest.real(om, "manual30", MANUAL_IDS));
        return service.recommend(USER, 21L, 30, true, null);
    }

    @SuppressWarnings("unchecked")
    private static List<String> ids(Map<String, Object> rec) {
        return ((List<Map<String, Object>>) rec.get("changes")).stream().map(c -> (String) c.get("id")).toList();
    }

    @Test
    @SuppressWarnings("unchecked")
    void applyAll_createsWeeklySessions_reschedulesViaPlannerUpdate_andRereads() throws Exception {
        Map<String, Object> rec = recommendManual();
        Map<String, Object> out = apply.apply(USER, 21L, (String) rec.get("proposalToken"), ids(rec));

        assertEquals(false, out.get("alreadyApplied"));
        assertEquals(true, out.get("refreshRequired"));
        assertEquals(3, todos.size());
        Todo first = todos.get(0);
        assertEquals("ADAPTIVE_SESSION", first.getSourceType());
        assertEquals(22L, first.getSourceId());
        assertEquals(LocalDate.of(2026, 10, 28), first.getScheduleDate());
        assertEquals("[AI 학습 30분] SQLD 기출문제 풀이", first.getText());
        assertFalse(first.getCompleted());

        Planner p24 = f.planners.get(24L);
        assertEquals(LocalDate.of(2026, 10, 29), p24.getPlannerDate());
        assertEquals(10, p24.getMonth());
        assertEquals(29, p24.getDay());
        assertEquals("목", p24.getDayOfWeek());
        assertEquals("미적분 문제 풀이", p24.getTitle(), "날짜 외 필드는 그대로");
        assertEquals("2026-10-27", p24.getDDay(), "마감일은 바꾸지 않는다");
        assertEquals("1시간", p24.getGoalTime());
        assertEquals("메모 유지", p24.getTmi());

        List<Map<String, Object>> applied = (List<Map<String, Object>>) out.get("applied");
        assertEquals(List.of("CREATED", "CREATED", "CREATED", "RESCHEDULED"), applied.stream().map(a -> a.get("state")).toList());
        assertEquals("2026-10-29", applied.get(3).get("toDate"));
        assertEquals(first.getId(), applied.get(0).get("todoId"));
    }

    @Test
    void replay_isIdempotent_noDuplicateRowsOrWrites() throws Exception {
        Map<String, Object> rec = recommendManual();
        String token = (String) rec.get("proposalToken");
        apply.apply(USER, 21L, token, ids(rec));
        int writes = todoWrites.get();
        Map<String, Object> again = apply.apply(USER, 21L, token, ids(rec));
        assertEquals(true, again.get("alreadyApplied"));
        assertEquals(3, todos.size());
        assertEquals(writes, todoWrites.get(), "재반영은 쓰지 않는다");
    }

    @Test
    void subset_appliesOnlySelected() throws Exception {
        Map<String, Object> rec = recommendManual();
        apply.apply(USER, 21L, (String) rec.get("proposalToken"), List.of("S:22:2026-10-28"));
        assertEquals(1, todos.size());
        assertEquals(LocalDate.of(2026, 10, 25), f.planners.get(24L).getPlannerDate(), "고르지 않은 예정일 변경은 하지 않는다");
    }

    @Test
    void dbChangedSinceProposal_isStale409_andWritesNothing() throws Exception {
        Map<String, Object> rec = recommendManual();
        f.items.stream().filter(i -> i.getText().equals("과제 22-1")).findFirst().orElseThrow().setCompleted(true);
        AdaptivePlannerException e = assertThrows(AdaptivePlannerException.class,
                () -> apply.apply(USER, 21L, (String) rec.get("proposalToken"), ids(rec)));
        assertEquals("ADAPTIVE_STALE", e.getCode());
        assertEquals(HttpStatus.CONFLICT, e.getStatus());
        assertTrue(todos.isEmpty());
        assertEquals(LocalDate.of(2026, 10, 25), f.planners.get(24L).getPlannerDate());
    }

    @Test
    void proposalDatePassed_is409() throws Exception {
        Map<String, Object> rec = recommendManual();
        Clock later = Clock.fixed(Instant.parse("2026-10-29T03:00:00Z"), ZoneId.of("Asia/Seoul"));
        AdaptivePlannerService laterService = new AdaptivePlannerService(f.builder, client, signer, mock(PlatformTransactionManager.class), later);
        AdaptivePlannerApplyService laterApply = new AdaptivePlannerApplyService(signer, f.builder, laterService, schedule, plannerService,
                f.plannerRepository, mock(PlatformTransactionManager.class));
        AdaptivePlannerException e = assertThrows(AdaptivePlannerException.class,
                () -> laterApply.apply(USER, 21L, (String) rec.get("proposalToken"), List.of("S:22:2026-10-28")));
        assertTrue(List.of("ADAPTIVE_PROPOSAL_DATE_PASSED", "ADAPTIVE_STALE").contains(e.getCode()));
        assertTrue(todos.isEmpty());
    }

    @Test
    void tamperedOrForeignOrUnknownSelections_areRejected400() throws Exception {
        Map<String, Object> rec = recommendManual();
        String token = (String) rec.get("proposalToken");
        String tampered = token.substring(0, token.length() - 2) + (token.endsWith("A") ? "BB" : "AA");
        assertEquals("ADAPTIVE_PROPOSAL_INVALID",
                assertThrows(AdaptivePlannerException.class, () -> apply.apply(USER, 21L, tampered, ids(rec))).getCode());
        assertEquals("ADAPTIVE_PROPOSAL_INVALID",
                assertThrows(AdaptivePlannerException.class, () -> apply.apply(OTHER, 21L, token, ids(rec))).getCode());
        assertEquals("ADAPTIVE_PROPOSAL_INVALID",
                assertThrows(AdaptivePlannerException.class, () -> apply.apply(USER, 22L, token, ids(rec))).getCode());
        assertEquals("ADAPTIVE_PROPOSAL_INVALID",
                assertThrows(AdaptivePlannerException.class, () -> apply.apply(USER, 21L, token, List.of("S:22:2026-11-30"))).getCode(),
                "토큰에 없는 날짜·대상은 반영할 수 없다");
        assertEquals("ADAPTIVE_NO_CHANGE_SELECTED",
                assertThrows(AdaptivePlannerException.class, () -> apply.apply(USER, 21L, token, List.of())).getCode());
        assertTrue(todos.isEmpty());
    }

    @Test
    void expiredToken_is409() throws Exception {
        Map<String, Object> rec = recommendManual();
        AdaptiveProposalSigner later = new AdaptiveProposalSigner("test-secret", Duration.ofMinutes(30), om,
                Clock.fixed(Instant.parse("2026-10-28T03:31:00Z"), ZoneId.of("Asia/Seoul")));
        AdaptivePlannerApplyService laterApply = new AdaptivePlannerApplyService(later, f.builder, service, schedule, plannerService,
                f.plannerRepository, mock(PlatformTransactionManager.class));
        AdaptivePlannerException e = assertThrows(AdaptivePlannerException.class,
                () -> laterApply.apply(USER, 21L, (String) rec.get("proposalToken"), ids(rec)));
        assertEquals("ADAPTIVE_PROPOSAL_EXPIRED", e.getCode());
    }

    @Test
    void concurrentDuplicateInsert_retriesOnce_andReportsExistingRows() throws Exception {
        Map<String, Object> rec = recommendManual();
        raceOnce.set(true);
        Map<String, Object> out = apply.apply(USER, 21L, (String) rec.get("proposalToken"), List.of("S:22:2026-10-28"));
        assertEquals(1, todos.size(), "경합 뒤에도 행은 1개");
        assertEquals(true, out.get("alreadyApplied"));
    }

    @Test
    void roadmapSessions_areRecordedForCurrentStepOnly_withoutTouchingStepDates() throws Exception {
        f.roadmapStep(11, USER, 1, 1, TODAY.minusDays(2));
        f.roadmapStep(12, USER, 1, 2, TODAY.minusDays(1));
        f.roadmapStep(13, USER, 1, 3, TODAY);
        f.roadmapStep(14, USER, 2, 1, TODAY.plusDays(1));
        f.checklist(f.planners.get(11L), true);
        f.checklist(f.planners.get(12L), true);
        when(client.recommend(any(), anyString())).thenReturn(AdaptivePlannerServiceTest.real(om, "roadmap30", ROADMAP_IDS));
        Map<String, Object> rec = service.recommend(USER, 13L, 30, true, null);
        apply.apply(USER, 13L, (String) rec.get("proposalToken"), ids(rec));
        assertEquals(2, todos.size());
        assertTrue(todos.stream().allMatch(t -> t.getSourceId() == 13L && t.getText().equals("[AI 학습 30분] [로드맵 1주차 3일] 단계 1-3")));
        assertEquals(TODAY, f.planners.get(13L).getPlannerDate());
    }
}
