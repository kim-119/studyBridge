package com.studybridge.api.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyMap;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.ai.quality.QualityStreamGate;
import com.studybridge.api.dto.ChatDTO;
import com.studybridge.api.dto.IntentDTO;
import com.studybridge.api.dto.QuizDTO;
import com.studybridge.api.dto.RedisChatMessage;
import com.studybridge.api.entity.Agent;
import com.studybridge.api.entity.ChatMessage;
import com.studybridge.api.entity.User;
import com.studybridge.api.service.support.ChatGateStubServer;
import com.studybridge.api.service.support.ChatServiceTestFactory;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.Mockito;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.test.util.ReflectionTestUtils;
import reactor.core.publisher.Mono;

/**
 * 개인 학습메이트 non-stream(POST /api/agent-rooms/{roomId}/chat) 품질 게이트(Phase D):
 *  QualityStreamGate 의 all_complete 규칙으로 answers/messages 를 메시지 단위 평가 → 승인분만 응답·DB·Redis.
 *  거절(79)·평가기 503 은 명시적 실패(AI_QUALITY_REJECTED/UNAVAILABLE, retryable), 80 승인 경계, 부분 승인, 게이트 OFF 회귀 없음.
 *  + 의도 라우터 파이프라인: 퀴즈는 생성 경로가 GATED 라 게이트 ON 에서도 실행(미승인 퀴즈는 실패 안내), 로드맵은 여전히 차단.
 */
class ChatServiceNonStreamQualityGateTest {

    static final long ROOM = 9L;
    static final long OWNER = 77L;
    static final ObjectMapper M = new ObjectMapper();
    ChatGateStubServer stub;

    @BeforeEach
    void up() throws Exception {
        stub = new ChatGateStubServer();
    }

    @AfterEach
    void down() {
        stub.close();
    }

    static Map<String, Object> aiResponse() throws Exception {
        return M.readValue("""
                {"mode":"multi_agent_discussion","learningMode":"basic","turnId":"t9","status":"COMPLETED",
                 "messages":[{"agentId":"1","agentName":"에이전트 1","content":"CANARYA 객체는 상태와 행동을 가진다.","round":1,"sequence":1},
                             {"agentId":"2","agentName":"에이전트 2","content":"CANARYB 클래스는 객체의 설계도다.","round":1,"sequence":2}],
                 "answers":[{"agentId":1,"agentName":"에이전트 1","answer":"CANARYA 객체는 상태와 행동을 가진다."},
                            {"agentId":2,"agentName":"에이전트 2","answer":"CANARYB 클래스는 객체의 설계도다."}],
                 "processSteps":{"first":"CANARYP 1차 초안"},
                 "finalSynthesis":"CANARYF 종합 정리"}
                """, Map.class);
    }

    ChatServiceTestFactory factory(QualityStreamGate gate) throws Exception {
        ChatServiceTestFactory f = new ChatServiceTestFactory(ROOM, List.of(Agent.builder().id(1L).name("에이전트 1").build(),
                Agent.builder().id(2L).name("에이전트 2").build()), gate);
        User u = new User();
        u.setId(OWNER);
        f.room.setUser(u);
        Map<String, Object> resp = aiResponse();
        when(f.failover.callMultiChat(eq(ROOM), anyString(), any(), any())).thenReturn(Mono.just(resp));
        return f;
    }

    static ChatDTO.MultiChatResponse ask(ChatServiceTestFactory f) {
        return f.service.chatWithRoom(OWNER, ROOM, ChatDTO.MultiChatRequest.builder().message("객체지향이 뭐야?").messageId("req-ns-0001").build());
    }

    static String json(Object o) throws Exception {
        return M.writeValueAsString(o);
    }

    static List<RedisChatMessage> redisAssistant(ChatServiceTestFactory f) {
        ArgumentCaptor<RedisChatMessage> rc = ArgumentCaptor.forClass(RedisChatMessage.class);
        Mockito.verify(f.redis, Mockito.atLeast(0)).savePersonalMessage(anyLong(), rc.capture());
        return rc.getAllValues().stream().filter(m -> "ASSISTANT".equals(m.getRole())).toList();
    }

    @com.studybridge.api.ai.quality.GateEvidence({"POST /api/agent-rooms/{roomId}/chat"})
    @Test
    void allRejected79IsExplicitFailureWithNothingSaved() throws Exception {
        stub.policy = (n, in) -> ChatGateStubServer.out(79, "REJECTED", false);
        ChatServiceTestFactory f = factory(stub.streamGate(true));
        ChatDTO.MultiChatResponse r = ask(f);
        assertEquals(Boolean.FALSE, r.getSuccess());
        assertEquals("AI_QUALITY_REJECTED", r.getErrorCode());
        assertEquals(Boolean.TRUE, r.getRetryable());
        assertEquals("REJECTED", r.getQualityStatus());
        assertFalse(json(r).contains("CANARY"), "거절 초안이 응답에 실림");
        assertTrue(f.saved.stream().noneMatch(m -> "AI".equals(m.getSender())), "거절 초안이 DB 에 저장됨");
        assertTrue(redisAssistant(f).isEmpty(), "거절 초안이 Redis 에 저장됨");
        assertTrue(f.saved.stream().anyMatch(m -> "USER".equals(m.getSender())), "사용자 질문은 그대로 저장");
        assertFalse(stub.evaluations.isEmpty());
        assertEquals("STUDYMATE_BASIC", stub.evaluations.get(0).get("taskType").asText());
        assertEquals("agent_message", stub.evaluations.get(0).get("outputKind").asText());
    }

    @com.studybridge.api.ai.quality.GateEvidence({"POST /api/agent-rooms/{roomId}/chat"})
    @Test
    void approved80BoundaryKeepsOnlyApprovedMessagesInResponseDbAndRedis() throws Exception {
        // A 답변만 80(승인), 나머지(B 답변·부가 필드 묶음)는 79(거절)
        stub.policy = (n, in) -> ChatGateStubServer.proposedText(in).contains("CANARYA")
                ? ChatGateStubServer.out(80, "APPROVED", false) : ChatGateStubServer.out(79, "REJECTED", false);
        ChatServiceTestFactory f = factory(stub.streamGate(true));
        ChatDTO.MultiChatResponse r = ask(f);
        String body = json(r);
        assertEquals(Boolean.TRUE, r.getSuccess());
        assertEquals("APPROVED", r.getQualityStatus());
        assertTrue(body.contains("CANARYA"), "승인 답변은 그대로 노출");
        for (String draft : List.of("CANARYB", "CANARYP", "CANARYF")) {
            assertFalse(body.contains(draft), "미승인 " + draft + " 노출");
        }
        assertEquals(1, r.getReplies().size());
        assertEquals("에이전트 1", r.getReplies().get(0).getAgentName());
        assertNotNull(r.getAgentErrors(), "거절 메시지는 agentErrors(고정 문구)로");
        assertTrue(json(r.getAgentErrors()).contains("QUALITY_REJECTED"));
        assertNotNull(r.getQualityRedactedFields());
        assertTrue(r.getQualityRedactedFields().contains("processSteps"));
        List<ChatMessage> ai = f.saved.stream().filter(m -> "AI".equals(m.getSender())).toList();
        assertEquals(1, ai.size());
        assertTrue(ai.get(0).getContent().contains("CANARYA"));
        assertEquals("APPROVED", ai.get(0).getQualityStatus());
        assertNull(ai.get(0).getProcessStepsJson(), "미승인 processSteps 는 저장하지 않는다");
        List<RedisChatMessage> redis = redisAssistant(f);
        assertEquals(1, redis.size());
        assertEquals("APPROVED", redis.get(0).getQualityStatus());
        assertTrue(stub.evaluations.stream().anyMatch(in -> ChatGateStubServer.proposedText(in).contains("CANARYF")),
                "부가 본문(finalSynthesis 등)도 평가 대상");
    }

    @Test
    void allApprovedKeepsFullResponse() throws Exception {
        stub.policy = (n, in) -> ChatGateStubServer.out(90, "APPROVED", false);
        ChatServiceTestFactory f = factory(stub.streamGate(true));
        ChatDTO.MultiChatResponse r = ask(f);
        assertEquals(Boolean.TRUE, r.getSuccess());
        assertEquals(2, r.getReplies().size());
        assertEquals("CANARYF 종합 정리", r.getFinalSynthesis());
        assertNull(r.getQualityRedactedFields());
        List<ChatMessage> ai = f.saved.stream().filter(m -> "AI".equals(m.getSender())).toList();
        assertEquals(2, ai.size());
        assertTrue(ai.stream().allMatch(m -> "APPROVED".equals(m.getQualityStatus()) && m.getProcessStepsJson() != null));
    }

    @Test
    void answersOnlyResponseUsesAnswersPathWithApprovedRows() throws Exception {
        stub.policy = (n, in) -> ChatGateStubServer.proposedText(in).contains("CANARYB")
                ? ChatGateStubServer.out(79, "REJECTED", false) : ChatGateStubServer.out(85, "APPROVED", false);
        ChatServiceTestFactory f = factory(stub.streamGate(true));
        Map<String, Object> answersOnly = aiResponse();
        answersOnly.remove("messages");
        when(f.failover.callMultiChat(eq(ROOM), anyString(), any(), any())).thenReturn(Mono.just(answersOnly));
        ChatDTO.MultiChatResponse r = ask(f);
        assertEquals(Boolean.TRUE, r.getSuccess());
        assertEquals(1, r.getReplies().size(), "answers 경로(원 응답 구조 유지)로 승인 답변만");
        assertTrue(r.getReplies().get(0).getAnswer().contains("CANARYA"));
        assertNull(r.getMessages());
        List<ChatMessage> ai = f.saved.stream().filter(m -> "AI".equals(m.getSender())).toList();
        assertEquals(1, ai.size());
        assertEquals("APPROVED", ai.get(0).getQualityStatus());
        assertFalse(json(r).contains("CANARYB"));
    }

    @Test
    void evaluatorDownIsUnavailableNotSuccess() throws Exception {
        stub.policy = (n, in) -> null;
        ChatServiceTestFactory f = factory(stub.streamGate(true));
        ChatDTO.MultiChatResponse r = ask(f);
        assertEquals(Boolean.FALSE, r.getSuccess());
        assertEquals("AI_QUALITY_UNAVAILABLE", r.getErrorCode());
        assertEquals("VALIDATION_ERROR", r.getQualityStatus());
        assertFalse(json(r).contains("CANARY"));
        assertTrue(f.saved.stream().noneMatch(m -> "AI".equals(m.getSender())));
    }

    @Test
    void gateOffIsLegacyBehaviourAndShape() throws Exception {
        ChatServiceTestFactory f = factory(null);
        ChatDTO.MultiChatResponse r = ask(f);
        String body = json(r);
        assertEquals(0, stub.evaluations.size());
        assertTrue(body.contains("CANARYB") && body.contains("CANARYF"));
        for (String k : List.of("qualityStatus", "retryable", "agentErrors", "qualityRedactedFields")) {
            assertFalse(body.contains("\"" + k + "\""), "게이트 OFF 응답에 새 키 " + k);
        }
        List<ChatMessage> ai = f.saved.stream().filter(m -> "AI".equals(m.getSender())).toList();
        assertEquals(2, ai.size());
        assertTrue(ai.stream().allMatch(m -> m.getQualityStatus() == null));
    }

    // ── 의도 라우터 파이프라인(개인 SSE) ─────────────────────────────────────────────

    static List<ServerSentEvent<String>> routed(ChatServiceTestFactory f, IntentDTO.RouteAction action) {
        IntentRouterService router = (IntentRouterService) ReflectionTestUtils.getField(f.service, "intentRouterService");
        when(router.route(anyString(), eq("learning_mate"), anyMap())).thenReturn(IntentDTO.RouteResult.builder().action(action).build());
        ChatDTO.MultiChatRequest req = ChatDTO.MultiChatRequest.builder().message("이 자료로 문제 내줘").materialId(5L).build();
        return f.service.chatStream(OWNER, ROOM, req).collectList().block(Duration.ofSeconds(10));
    }

    @Test
    void quizPipelineRunsWhenQuizGenerationIsGatedAndRoadmapStaysBlocked() throws Exception {
        assertTrue(ChatService.pipelineGenerationGated(IntentDTO.RouteAction.QUIZ_PIPELINE), "레지스트리: POST quiz = GATED");
        assertTrue(ChatService.pipelineGenerationGated(IntentDTO.RouteAction.SUMMARY_PIPELINE));
        assertFalse(ChatService.pipelineGenerationGated(IntentDTO.RouteAction.ROADMAP_PIPELINE), "로드맵은 아직 BLOCKED");

        ChatServiceTestFactory f = factory(stub.streamGate(true));
        AiIntegrationService ai = (AiIntegrationService) ReflectionTestUtils.getField(f.service, "aiIntegrationService");
        when(ai.generateQuiz(eq(OWNER), eq(5L), any())).thenReturn(QuizDTO.Response.builder().quizId(3L).success(true)
                .qualityStatus("APPROVED").verified(true).build());
        List<ServerSentEvent<String>> ok = routed(f, IntentDTO.RouteAction.QUIZ_PIPELINE);
        assertTrue(ok.stream().anyMatch(e -> "route_pipeline".equals(e.event()) && e.data().contains("\"quizId\":3")
                && e.data().contains("\"qualityStatus\":\"APPROVED\"")));
        assertTrue(ok.stream().noneMatch(e -> e.data().contains("AI_QUALITY_GATE_NOT_WIRED")));

        when(ai.generateQuiz(eq(OWNER), eq(5L), any())).thenReturn(QuizDTO.Response.builder().success(false)
                .errorCode("AI_QUALITY_REJECTED").qualityStatus("REJECTED").verified(false).build());
        List<ServerSentEvent<String>> rejected = routed(f, IntentDTO.RouteAction.QUIZ_PIPELINE);
        assertTrue(rejected.stream().anyMatch(e -> "route_message".equals(e.event()) && e.data().contains("AI_QUALITY_REJECTED")));
        assertTrue(rejected.stream().noneMatch(e -> "route_pipeline".equals(e.event())), "미승인 퀴즈를 성공으로 싣지 않는다");

        List<ServerSentEvent<String>> roadmap = routed(f, IntentDTO.RouteAction.ROADMAP_PIPELINE);
        assertTrue(roadmap.stream().anyMatch(e -> e.data().contains("AI_QUALITY_GATE_NOT_WIRED")));
        verify(ai, never()).getRoadmap(anyLong(), anyLong());
    }

    @Test
    void quizPipelineGateOffIsUnchanged() throws Exception {
        ChatServiceTestFactory f = factory(null);
        AiIntegrationService ai = (AiIntegrationService) ReflectionTestUtils.getField(f.service, "aiIntegrationService");
        when(ai.generateQuiz(eq(OWNER), eq(5L), any())).thenReturn(QuizDTO.Response.builder().quizId(4L).build());
        List<ServerSentEvent<String>> out = routed(f, IntentDTO.RouteAction.QUIZ_PIPELINE);
        assertTrue(out.stream().anyMatch(e -> "route_pipeline".equals(e.event()) && e.data().contains("\"quizId\":4")
                && !e.data().contains("qualityStatus")));
    }
}
