package com.studybridge.api.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.when;

import com.studybridge.api.ai.quality.AiQualityGateSettings;
import com.studybridge.api.ai.quality.AiResponseQualityGate;
import com.studybridge.api.ai.quality.QualityEvaluatorClient;
import com.studybridge.api.ai.quality.QualityStreamGate;
import com.studybridge.api.dto.ChatDTO;
import com.studybridge.api.dto.RedisChatMessage;
import com.studybridge.api.entity.Agent;
import com.studybridge.api.entity.ChatMessage;
import com.studybridge.api.entity.User;
import com.studybridge.api.service.support.ChatServiceTestFactory;
import java.time.Duration;
import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.Mockito;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.test.util.ReflectionTestUtils;
import reactor.core.publisher.Flux;

/**
 * ChatService 실제 relay 체인(게이트 → 영속화) 검증:
 *  · deny-all: 화면 본문 0자 + DB/Redis 에 AI 답변 0건(거절 초안은 정식 이력이 되지 않는다).
 *  · approve-all: 승인 답변만 qualityStatus=APPROVED 로 영속.
 *  · 게이트 OFF: 기존 동작(answers 영속, qualityStatus null).
 *  · 이력: 게이트 ON 이면 미검증(레거시) AI 행 본문 가림. Learning Memory: 미승인 AI 답변은 previousAnswers 에서 제외.
 */
class ChatServiceQualityGateTest {

        static final String CANARY = "CANARY7F3A";

        static List<ServerSentEvent<String>> capture() throws Exception {
                return com.studybridge.api.ai.quality.QualityStreamGateTestSupport.capture("studymate_multichat_default");
        }

        static QualityStreamGate gateWith(com.studybridge.api.ai.quality.QualityStreamGateTestSupport.Stub stub) {
                AiQualityGateSettings s = AiQualityGateSettings.forTest(true);
                QualityEvaluatorClient c = new QualityEvaluatorClient(stub.client(), s, "k".repeat(64));
                return new QualityStreamGate(new AiResponseQualityGate(s, c));
        }

        static List<ServerSentEvent<String>> relay(ChatServiceTestFactory f) throws Exception {
                when(f.failover.streamMultiChat(anyLong(), anyString(), any(), any())).thenReturn(Flux.fromIterable(capture()));
                ChatDTO.MultiChatRequest req = ChatDTO.MultiChatRequest.builder().message("객체지향이 뭐야?").build();
                @SuppressWarnings("unchecked")
                Flux<ServerSentEvent<String>> out = (Flux<ServerSentEvent<String>>) ReflectionTestUtils.invokeMethod(f.service,
                                "relayRemoteStream", 9L, "req-chat-gate-0001", new LinkedHashMap<String, Object>(), req, f.room);
                return out.collectList().block(Duration.ofSeconds(20));
        }

        static ChatServiceTestFactory factory(QualityStreamGate gate) {
                return new ChatServiceTestFactory(9L, List.of(Agent.builder().id(1L).name("에이전트 1").build(),
                                Agent.builder().id(2L).name("에이전트 2").build(), Agent.builder().id(3L).name("에이전트 3").build()), gate);
        }

        @com.studybridge.api.ai.quality.GateEvidence({"POST /api/agent-rooms/{roomId}/chat/stream"})
        @Test
        void denyAllPersistsNothingAndLeaksNothing() throws Exception {
                try (var stub = com.studybridge.api.ai.quality.QualityStreamGateTestSupport.stub(false)) {
                        ChatServiceTestFactory f = factory(gateWith(stub));
                        List<ServerSentEvent<String>> out = relay(f);
                        assertTrue(out.stream().noneMatch(e -> e.data() != null && e.data().contains(CANARY)));
                        assertTrue(f.saved.stream().noneMatch(m -> "AI".equals(m.getSender())), "거절 답변이 DB 이력에 저장됨");
                        ArgumentCaptor<RedisChatMessage> rc = ArgumentCaptor.forClass(RedisChatMessage.class);
                        Mockito.verify(f.redis, Mockito.atLeast(0)).savePersonalMessage(anyLong(), rc.capture());
                        assertTrue(rc.getAllValues().stream().noneMatch(m -> "ASSISTANT".equals(m.getRole())), "거절 답변이 Redis 에 저장됨");
                }
        }

        @com.studybridge.api.ai.quality.GateEvidence({"POST /api/agent-rooms/{roomId}/chat/stream"})
        @Test
        void approveAllPersistsApprovedWithStatus() throws Exception {
                try (var stub = com.studybridge.api.ai.quality.QualityStreamGateTestSupport.stub(true)) {
                        ChatServiceTestFactory f = factory(gateWith(stub));
                        relay(f);
                        List<ChatMessage> ai = f.saved.stream().filter(m -> "AI".equals(m.getSender())).toList();
                        assertFalse(ai.isEmpty());
                        assertTrue(ai.stream().allMatch(m -> "APPROVED".equals(m.getQualityStatus())));
                        assertTrue(ai.stream().allMatch(m -> m.getContent().contains(CANARY)), "승인된 원문 그대로 저장");
                }
        }

        @Test
        void gateOffKeepsLegacyBehaviour() throws Exception {
                ChatServiceTestFactory f = factory(null);
                List<ServerSentEvent<String>> out = relay(f);
                assertEquals(capture().size(), out.size(), "게이트 OFF: 이벤트 그대로 중계");
                List<ChatMessage> ai = f.saved.stream().filter(m -> "AI".equals(m.getSender())).toList();
                assertFalse(ai.isEmpty());
                assertTrue(ai.stream().allMatch(m -> m.getQualityStatus() == null), "게이트 OFF 에선 승인 표시를 붙이지 않는다");
        }

        @com.studybridge.api.ai.quality.GateEvidence({"GET /api/agent-rooms/{roomId}/history"})
        @Test
        void historyRedactsUnverifiedAiRowsOnlyWhenGateOn() throws Exception {
                try (var stub = com.studybridge.api.ai.quality.QualityStreamGateTestSupport.stub(true)) {
                        for (boolean on : List.of(true, false)) {
                                ChatServiceTestFactory f = factory(on ? gateWith(stub) : null);
                                User u = new User();
                                u.setId(77L);
                                f.room.setUser(u);
                                ChatMessage user = ChatMessage.builder().id(1L).sender("USER").content("질문").createdAt(LocalDateTime.now()).build();
                                ChatMessage legacy = ChatMessage.builder().id(2L).sender("AI").content("옛 답변").createdAt(LocalDateTime.now()).build();
                                ChatMessage approved = ChatMessage.builder().id(3L).sender("AI").content("승인 답변").qualityStatus("APPROVED")
                                                .createdAt(LocalDateTime.now()).build();
                                when(f.messages.findByAgentChatRoomIdOrderByCreatedAtAscIdAsc(9L)).thenReturn(List.of(user, legacy, approved));
                                List<ChatDTO.MessageResponse> h = f.service.getRoomChatHistory(77L, 9L);
                                assertEquals("질문", h.get(0).getContent());
                                assertEquals(on ? ChatService.QUALITY_REDACTED_TEXT : "옛 답변", h.get(1).getContent());
                                assertEquals(on ? Boolean.TRUE : null, h.get(1).getQualityRedacted());
                                assertEquals("승인 답변", h.get(2).getContent());
                        }
                }
        }

        @Test
        void learningMemoryDropsUnapprovedAssistantTurnsWhenGateOn() {
                List<Map<String, Object>> prev = List.of(
                                Map.of("role", "USER", "answer", "질문1"),
                                Map.of("role", "ASSISTANT", "answer", "옛 답변(미검증)"),
                                Map.of("role", "ASSISTANT", "answer", "승인 답변", "qualityStatus", "APPROVED"));
                List<Map<String, Object>> on = ChatService.filterTrustedPreviousAnswers(prev, true);
                assertEquals(List.of("질문1", "승인 답변"), on.stream().map(m -> m.get("answer")).toList());
                assertTrue(on.stream().noneMatch(m -> m.containsKey("qualityStatus")), "내부 판정 필드는 ai07 로 보내지 않는다");
                List<Map<String, Object>> off = ChatService.filterTrustedPreviousAnswers(prev, false);
                assertEquals(3, off.size());
                assertNull(off.get(2).get("qualityStatus"));
        }

        @Test
        void intentRouterTextIsReplacedByFixedMessageWhenGateOn() throws Exception {
                com.studybridge.api.dto.IntentDTO.RouteResult route = Mockito.mock(com.studybridge.api.dto.IntentDTO.RouteResult.class);
                when(route.getAction()).thenReturn(com.studybridge.api.dto.IntentDTO.RouteAction.DIRECT_REPLY);
                when(route.userMessage()).thenReturn("CANARY7F3A LLM 이 쓴 직답");
                try (var stub = com.studybridge.api.ai.quality.QualityStreamGateTestSupport.stub(true)) {
                        String on = ReflectionTestUtils.invokeMethod(factory(gateWith(stub)).service, "routeUserMessage", route);
                        assertFalse(on.contains(CANARY), "게이트 ON: 라우터 LLM 문장 미노출");
                }
                String off = ReflectionTestUtils.invokeMethod(factory(null).service, "routeUserMessage", route);
                assertTrue(off.contains(CANARY), "게이트 OFF: 기존 동작");
        }
}
