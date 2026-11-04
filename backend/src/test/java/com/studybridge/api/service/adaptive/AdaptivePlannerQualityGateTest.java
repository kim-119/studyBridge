package com.studybridge.api.service.adaptive;

import static com.studybridge.api.service.adaptive.AdaptiveFixtures.TODAY;
import static com.studybridge.api.service.adaptive.AdaptiveFixtures.USER;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.studybridge.api.ai.quality.GateEvidence;
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
import com.studybridge.api.service.support.ChatGateStubServer;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.transaction.PlatformTransactionManager;

/**
 * AI 학습 내비게이터 품질 게이트(PLANNER_COACHING/text): 79 거절 → 80 승인분만 응답 + 승인 표식 토큰, 전부 거절·평가기 503 은
 * 422/503(토큰 없음), ai07 오류는 기존 계약, 게이트 ON 반영 API 는 승인 표식 없는 토큰 거부(쓰기 0), 게이트 OFF 회귀 없음.
 */
class AdaptivePlannerQualityGateTest {

    private static final Map<String, String> MANUAL_IDS = Map.of("\\b9001\\b", "21", "\\b9002\\b", "22", "\\b9003\\b", "23", "\\b9004\\b", "24");
    private final ObjectMapper om = new ObjectMapper();
    private ChatGateStubServer stub;
    private AdaptiveFixtures f;
    private AdaptivePlannerClient client;
    private AdaptiveProposalSigner signer;
    private final List<Todo> todos = new ArrayList<>();
    private final AtomicLong todoIds = new AtomicLong(5000);
    private final AtomicInteger todoWrites = new AtomicInteger();
    private final AtomicInteger aiCalls = new AtomicInteger();
    private ScheduleRegistrationService schedule;
    private PlannerService plannerService;

    @BeforeEach
    void setUp() throws Exception {
        stub = new ChatGateStubServer();
        f = new AdaptiveFixtures();
        when(f.plannerRepository.save(any(Planner.class))).thenAnswer(inv -> {
            Planner p = inv.getArgument(0);
            f.planners.put(p.getId(), p);
            return p;
        });
        client = mock(AdaptivePlannerClient.class);
        signer = new AdaptiveProposalSigner("test-secret", Duration.ofMinutes(30), om, AdaptivePlannerServiceTest.CLOCK);
        TodoRepository todoRepository = mock(TodoRepository.class);
        when(todoRepository.findFirstByUserIdAndSourceTypeAndSourceIdAndScheduleDateOrderByIdAsc(anyLong(), anyString(), anyLong(), any()))
                .thenAnswer(inv -> todos.stream().filter(t -> t.getUser().getId().equals(inv.getArgument(0))
                        && t.getSourceType().equals(inv.getArgument(1)) && t.getSourceId().equals(inv.getArgument(2))
                        && t.getScheduleDate().equals(inv.getArgument(3))).findFirst());
        when(todoRepository.saveAndFlush(any(Todo.class))).thenAnswer(inv -> {
            Todo t = inv.getArgument(0);
            if (t.getId() == null) {
                t.setId(todoIds.incrementAndGet());
                todos.add(t);
            }
            todoWrites.incrementAndGet();
            return t;
        });
        UserRepository users = mock(UserRepository.class);
        when(users.findById(anyLong())).thenAnswer(inv -> Optional.of(User.builder().id(inv.getArgument(0)).build()));
        schedule = new ScheduleRegistrationService(todoRepository, users, mock(ReviewNoteRepository.class), f.plannerRepository,
                mock(LearningLoopService.class), mock(PlatformTransactionManager.class));
        plannerService = new PlannerService(f.plannerRepository, mock(MaterialRepository.class), mock(S3Service.class), om, mock(FolderRepository.class));
        f.userPlanner(21, USER, "Java 예외 처리 복습", TODAY.plusDays(1), "보통", "2026-10-31");
        f.userPlanner(22, USER, "SQLD 기출문제 풀이", TODAY, "높음", "2026-10-29");
        f.checklist(f.userPlanner(23, USER, "네트워크 OSI 7계층", TODAY.minusDays(1), "보통", null), true);
        f.userPlanner(24, USER, "미적분 문제 풀이", TODAY.minusDays(3), null, "2026-10-27");
        f.checklist(f.planners.get(22L), false, false);
        // 시도마다 추천 사유가 달라지는 실제 ai07 응답(초안 번호)
        when(client.recommend(any(), anyString())).thenAnswer(inv -> {
            int n = aiCalls.incrementAndGet();
            ObjectNode r = AdaptivePlannerServiceTest.real(om, "manual30", MANUAL_IDS);
            ((ObjectNode) r.get("recommendation")).put("reason", "초안 " + n + ": 마감이 가까운 SQLD 기출문제 풀이를 먼저 하세요.");
            return r;
        });
    }

    @AfterEach
    void down() {
        stub.close();
    }

    AdaptivePlannerService service(boolean gateOn) {
        AdaptivePlannerService s = new AdaptivePlannerService(f.builder, client, signer, mock(PlatformTransactionManager.class),
                AdaptivePlannerServiceTest.CLOCK);
        s.setQualityGate(stub.gate(gateOn));
        return s;
    }

    AdaptivePlannerApplyService apply(AdaptivePlannerService s) {
        return new AdaptivePlannerApplyService(signer, f.builder, s, schedule, plannerService, f.plannerRepository,
                mock(PlatformTransactionManager.class));
    }

    @SuppressWarnings("unchecked")
    static List<String> ids(Map<String, Object> rec) {
        return ((List<Map<String, Object>>) rec.get("changes")).stream().map(c -> (String) c.get("id")).toList();
    }

    @GateEvidence({"POST /api/planners/{plannerId}/adaptive"})
    @Test
    void rejected79ThenApproved80IsServedWithApprovedToken() {
        stub.policy = (n, in) -> n == 1 ? ChatGateStubServer.out(79, "REJECTED", false) : ChatGateStubServer.out(80, "APPROVED", false);
        Map<String, Object> out = service(true).recommend(USER, 21L, 30, true, null);
        assertEquals("APPROVED", out.get("qualityStatus"));
        assertEquals(80.0, out.get("qualityScore"));
        JsonNode result = (JsonNode) out.get("result");
        assertTrue(result.path("recommendation").path("reason").asText().startsWith("초안 2"), "재생성된 두 번째 추천만 노출");
        assertEquals(2, aiCalls.get());
        AdaptiveProposalSigner.Payload p = signer.verify((String) out.get("proposalToken"), USER, 21L);
        assertEquals("APPROVED", p.quality(), "승인된 추천에서만 승인 표식 토큰");
        JsonNode ev = stub.evaluations.get(0);
        assertEquals("PLANNER_COACHING", ev.get("taskType").asText());
        assertEquals("text", ev.get("outputKind").asText());
        String proposed = ev.get("proposedOutput").asText();
        assertTrue(proposed.contains("초안 1") && proposed.contains("학습 세션: SQLD 기출문제 풀이"), "추천 본문 + 반영 후보 일정 평가");
        assertFalse(proposed.contains("adaptive-planner.v1"), "전송 필드는 평가 대상이 아니다");
        assertEquals("PLANNER_RECORD", ev.get("groundingEvidence").get(0).get("sourceType").asText());
    }

    @GateEvidence({"POST /api/planners/{plannerId}/adaptive"})
    @Test
    void threeRejectionsAreExplicitFailureWithoutToken() {
        stub.policy = (n, in) -> ChatGateStubServer.out(70, "REJECTED", false);
        AdaptivePlannerException e = assertThrows(AdaptivePlannerException.class, () -> service(true).recommend(USER, 21L, 30, true, null));
        assertEquals(HttpStatus.UNPROCESSABLE_ENTITY, e.getStatus());
        assertEquals("AI_QUALITY_REJECTED", e.getCode());
        assertTrue(e.isRetryable());
        assertEquals(3, aiCalls.get(), "최초 1 + 재생성 2");
        assertFalse(e.getMessage().contains("초안"));
    }

    @Test
    void evaluatorDownIsUnavailable() {
        stub.policy = (n, in) -> null;
        AdaptivePlannerException e = assertThrows(AdaptivePlannerException.class, () -> service(true).recommend(USER, 21L, 30, true, null));
        assertEquals(HttpStatus.SERVICE_UNAVAILABLE, e.getStatus());
        assertEquals("AI_QUALITY_UNAVAILABLE", e.getCode());
        assertEquals(1, aiCalls.get());
    }

    @Test
    void upstreamErrorKeepsLegacyContractWithoutEvaluation() {
        when(client.recommend(any(), anyString())).thenThrow(new AdaptivePlannerException(HttpStatus.GATEWAY_TIMEOUT, "ADAPTIVE_TIMEOUT",
                "시간 초과", true, null, null));
        AdaptivePlannerException e = assertThrows(AdaptivePlannerException.class, () -> service(true).recommend(USER, 21L, 30, true, null));
        assertEquals("ADAPTIVE_TIMEOUT", e.getCode());
        assertEquals(0, stub.evaluations.size());
        verify(client, times(1)).recommend(any(), anyString());
    }

    @GateEvidence({"POST /api/planners/{plannerId}/adaptive/apply"})
    @Test
    void gateOnApplyRejectsUnmarkedTokenAndAppliesApprovedOne() {
        AdaptivePlannerService on = service(true);
        // 게이트 OFF 시절(또는 전환 직전)에 발급된 토큰 = 승인 표식 없음
        Map<String, Object> legacy = service(false).recommend(USER, 21L, 30, true, null);
        assertNull(signer.verify((String) legacy.get("proposalToken"), USER, 21L).quality());
        AdaptivePlannerException e = assertThrows(AdaptivePlannerException.class,
                () -> apply(on).apply(USER, 21L, (String) legacy.get("proposalToken"), ids(legacy)));
        assertEquals("ADAPTIVE_PROPOSAL_NOT_VERIFIED", e.getCode());
        assertEquals(HttpStatus.CONFLICT, e.getStatus());
        assertEquals(0, todoWrites.get(), "미검증 제안은 쓰기 0");
        assertTrue(todos.isEmpty());
        // 승인된 추천의 토큰은 반영된다(평가기 실제 호출 후)
        Map<String, Object> approved = on.recommend(USER, 21L, 30, true, null);
        assertTrue(stub.evaluations.size() >= 1);
        Map<String, Object> res = apply(on).apply(USER, 21L, (String) approved.get("proposalToken"), ids(approved));
        assertEquals(false, res.get("alreadyApplied"));
        assertEquals("[AI 학습 30분] SQLD 기출문제 풀이", todos.get(0).getText(), "todo 제목은 결정적(플래너 제목)");
        assertTrue(todoWrites.get() > 0);
    }

    @Test
    void gateOffIsLegacyBehaviour() {
        AdaptivePlannerService off = service(false);
        Map<String, Object> out = off.recommend(USER, 21L, 30, true, null);
        assertFalse(out.containsKey("qualityStatus"));
        assertEquals(0, stub.evaluations.size(), "게이트 OFF: 평가기 호출 0");
        assertNull(signer.verify((String) out.get("proposalToken"), USER, 21L).quality());
        Map<String, Object> res = apply(off).apply(USER, 21L, (String) out.get("proposalToken"), ids(out));
        assertEquals(false, res.get("alreadyApplied"), "게이트 OFF 반영 API 는 기존대로 동작");
    }
}
