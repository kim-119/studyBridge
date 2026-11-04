package com.studybridge.api.service;

import static com.studybridge.api.ai.memory.LearningMemoryFixtures.MAT;
import static com.studybridge.api.ai.memory.LearningMemoryFixtures.QUESTION;
import static com.studybridge.api.ai.memory.LearningMemoryFixtures.REQ;
import static com.studybridge.api.ai.memory.LearningMemoryFixtures.ROOM;
import static com.studybridge.api.ai.memory.LearningMemoryFixtures.SCOPE_KEY;
import static com.studybridge.api.ai.memory.LearningMemoryFixtures.USER;
import static org.junit.jupiter.api.Assertions.assertArrayEquals;
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
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.studybridge.api.ai.AiFailoverSettings;
import com.studybridge.api.ai.AiUpstream;
import com.studybridge.api.ai.AiUpstreams;
import com.studybridge.api.ai.contract.v1.AiContractSigning;
import com.studybridge.api.ai.contract.v1.ContractJson;
import com.studybridge.api.ai.contract.v1.LearningContextV1;
import com.studybridge.api.ai.contract.v1.PseudonymousUserKeys;
import com.studybridge.api.ai.memory.LearningMemoryAssembler;
import com.studybridge.api.ai.memory.LearningMemoryFixtures;
import com.studybridge.api.ai.memory.LearningMemorySettings;
import com.studybridge.api.ai.training.TrainingCandidateCollector;
import com.studybridge.api.dto.ChatDTO;
import com.studybridge.api.dto.IntentDTO;
import com.studybridge.api.entity.Agent;
import com.studybridge.api.entity.AgentChatRoom;
import com.studybridge.api.entity.ChatMessage;
import com.studybridge.api.entity.User;
import com.studybridge.api.repository.AgentChatRoomRepository;
import com.studybridge.api.repository.ChatMessageRepository;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.CopyOnWriteArrayList;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.transaction.support.TransactionCallback;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.reactive.function.client.WebClient;

/**
 * ChatService → 실제 AiMultiChatFailoverService → 로컬 HTTP 스텁(ai07 대역)으로 실제 전송 바이트·헤더를 잡아 확인한다.
 *  · 플래그 OFF: 조립기가 주입돼 있어도 요청 본문 바이트가 조립기 미주입(기존 코드 경로)과 같고 X-AI-Scope 헤더가 없다. 조립기 저장소 호출 0.
 *  · 플래그 ON: 본문 = 기존 본문 + learningContext(끝에 추가)뿐, learningContext 는 엄격 파서 + validate 통과, X-AI-Scope 는 rid=requestId·
 *    sub=가명 키로 검증된다. stream·non-stream·failover 재시도 모두 시도마다 헤더가 실린다.
 *  · 키 없음: learningContext·헤더 없이 기존 바이트 그대로 진행(응답 정상).
 */
class ChatServiceLearningMemoryTest {

    static final ObjectMapper M = new ObjectMapper();

    record Captured(String path, byte[] body, Map<String, List<String>> headers) {
        String header(String name) {
            for (Map.Entry<String, List<String>> e : headers.entrySet()) {
                if (e.getKey() != null && e.getKey().equalsIgnoreCase(name)) {
                    return e.getValue().isEmpty() ? null : e.getValue().get(0);
                }
            }
            return null;
        }
    }

    /** ai07 대역: /api/ai/multi-chat(JSON), /api/ai/multi-chat/stream(SSE). 요청 원문 바이트·헤더를 기록한다. */
    static final class Ai07Stub implements AutoCloseable {
        final HttpServer server;
        final List<Captured> requests = new CopyOnWriteArrayList<>();
        volatile int streamStatus = 200;

        Ai07Stub() throws IOException {
            server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
            server.createContext("/api/ai/multi-chat/stream", ex -> {
                capture(ex);
                if (streamStatus != 200) {
                    write(ex, streamStatus, "application/json", "{\"detail\":\"stub\"}");
                    return;
                }
                write(ex, 200, "text/event-stream", "event: turn_start\ndata: {\"type\":\"turn_start\",\"turnId\":\"t1\"}\n\n"
                        + "event: agent_answer\ndata: {\"type\":\"agent_answer\",\"agentId\":\"1\",\"agentIndex\":1,\"agentName\":\"교수\",\"answer\":\"스트림 답\"}\n\n"
                        + "event: all_complete\ndata: {\"type\":\"all_complete\",\"turnId\":\"t1\",\"answers\":[{\"agentId\":\"1\",\"agentName\":\"교수\",\"answer\":\"스트림 답\"}],\"status\":\"COMPLETED\"}\n\n"
                        + "event: done\ndata: {\"type\":\"done\",\"status\":\"done\"}\n\n");
            });
            server.createContext("/api/ai/multi-chat", ex -> {
                capture(ex);
                write(ex, 200, "application/json",
                        "{\"success\":true,\"mode\":\"single_answer\",\"answers\":[{\"agentId\":1,\"agentName\":\"교수\",\"answer\":\"비스트림 답\"}]}");
            });
            server.start();
        }

        void capture(HttpExchange ex) throws IOException {
            requests.add(new Captured(ex.getRequestURI().getPath(), ex.getRequestBody().readAllBytes(), Map.copyOf(ex.getRequestHeaders())));
        }

        static void write(HttpExchange ex, int status, String ct, String body) throws IOException {
            byte[] b = body.getBytes(StandardCharsets.UTF_8);
            ex.getResponseHeaders().add("Content-Type", ct);
            ex.sendResponseHeaders(status, b.length);
            try (OutputStream os = ex.getResponseBody()) {
                os.write(b);
            }
        }

        String url() {
            return "http://127.0.0.1:" + server.getAddress().getPort();
        }

        @Override
        public void close() {
            server.stop(0);
        }
    }

    final List<Ai07Stub> stubs = new ArrayList<>();

    @AfterEach
    void down() {
        stubs.forEach(Ai07Stub::close);
    }

    Ai07Stub stub() throws IOException {
        Ai07Stub s = new Ai07Stub();
        stubs.add(s);
        return s;
    }

    static AiMultiChatFailoverService failover(String... urls) {
        List<AiUpstream> ups = new ArrayList<>();
        for (int i = 0; i < urls.length; i++) {
            ups.add(new AiUpstream(i == 0 ? "primary" : "secondary", urls[i], WebClient.create(urls[i])));
        }
        return new AiMultiChatFailoverService(new AiUpstreams(ups), new ObjectMapper(), AiFailoverSettings.defaults()
                .attemptsPerUpstream(1).backoff(Duration.ofMillis(10)).circuitCooldown(Duration.ofSeconds(1))
                .streamIdleTimeout(Duration.ofSeconds(5)).totalTimeout(Duration.ofSeconds(30)).probeEnabled(false));
    }

    /** memory == null 이면 setter 미호출(조립기 미주입 = 기존 코드 경로). */
    @SuppressWarnings("unchecked")
    static ChatService chatService(AiMultiChatFailoverService failover, LearningMemoryAssembler memory) {
        AgentChatRoomRepository rooms = mock(AgentChatRoomRepository.class);
        ChatMessageRepository messages = mock(ChatMessageRepository.class);
        AgentChatRoom room = new AgentChatRoom();
        room.setId(ROOM);
        User u = new User();
        u.setId(USER);
        room.setUser(u);
        room.setAgents(List.of(Agent.builder().id(1L).name("교수").build()));
        when(rooms.findById(ROOM)).thenReturn(Optional.of(room));
        when(messages.save(any(ChatMessage.class))).thenAnswer(inv -> inv.getArgument(0));
        TransactionTemplate tt = mock(TransactionTemplate.class);
        when(tt.execute(any())).thenAnswer(inv -> ((TransactionCallback<Object>) inv.getArgument(0)).doInTransaction(null));
        IntentRouterService router = mock(IntentRouterService.class);
        when(router.route(anyString(), eq("learning_mate"), anyMap()))
                .thenReturn(IntentDTO.RouteResult.builder().action(IntentDTO.RouteAction.PROCEED).build());
        ChatService s = new ChatService(rooms, messages, mock(WebClient.class), tt, new ObjectMapper(), router,
                mock(AiIntegrationService.class), mock(RedisChatService.class), failover, null, mock(TrainingCandidateCollector.class));
        if (memory != null) {
            s.setLearningMemory(memory);
        }
        return s;
    }

    static ChatDTO.MultiChatRequest request() {
        return ChatDTO.MultiChatRequest.builder().message(QUESTION).messageId(REQ).materialId(MAT).build();
    }

    static ChatDTO.MultiChatResponse nonStream(ChatService s) {
        return s.chatWithRoom(USER, ROOM, request());
    }

    static List<ServerSentEvent<String>> stream(ChatService s) {
        return s.chatStream(USER, ROOM, request(), REQ).collectList().block(Duration.ofSeconds(30));
    }

    static Captured only(Ai07Stub s, String path) {
        List<Captured> c = s.requests.stream().filter(r -> r.path().equals(path)).toList();
        assertEquals(1, c.size(), path + " 호출 수");
        return c.get(0);
    }

    /** ON 본문 = OFF 본문의 마지막 '}' 앞에 ,"learningContext":{...} 를 덧붙인 것(다른 바이트는 그대로). */
    static JsonNode assertOnlyLearningContextAppended(byte[] off, byte[] on) throws Exception {
        return assertOnlyLearningContextAppended(off, on, null);
    }

    static JsonNode assertOnlyLearningContextAppended(byte[] off, byte[] on, String exportName) throws Exception {
        byte[] prefix = Arrays.copyOf(off, off.length - 1);
        assertArrayEquals(prefix, Arrays.copyOf(on, prefix.length), "learningContext 앞부분은 기존 본문과 바이트 동일해야 한다");
        String tail = new String(on, prefix.length, on.length - prefix.length, StandardCharsets.UTF_8);
        assertTrue(tail.startsWith(",\"learningContext\":{") && tail.endsWith("}"), tail.substring(0, Math.min(40, tail.length())));
        exportWire(exportName, tail.substring(",\"learningContext\":".length(), tail.length() - 1));
        ObjectNode onTree = (ObjectNode) M.readTree(on);
        JsonNode lc = onTree.remove("learningContext");
        assertEquals(M.readTree(off), onTree, "learningContext 외 필드 변화 없음");
        return lc;
    }

    /** SB_LEARNING_CONTEXT_EXPORT_DIR 가 있으면 실제 전송된 learningContext 원문 바이트를 남긴다(ai07 Pydantic 교차 검증용). */
    static void exportWire(String name, String rawLearningContextJson) throws IOException {
        String dir = System.getenv("SB_LEARNING_CONTEXT_EXPORT_DIR");
        if (name == null || dir == null || dir.isBlank()) {
            return;
        }
        java.nio.file.Files.createDirectories(java.nio.file.Path.of(dir));
        java.nio.file.Files.writeString(java.nio.file.Path.of(dir, name + ".json"), rawLearningContextJson, StandardCharsets.UTF_8);
    }

    static LearningContextV1 assertValidContext(JsonNode lc) throws Exception {
        assertNotNull(lc);
        // 엄격 파서(모르는 필드·타입 강제변환·중복 키 거부)로 원문 JSON 을 다시 읽어 검증한다.
        LearningContextV1 c = ContractJson.STRICT.readValue(M.writeValueAsBytes(lc), LearningContextV1.class);
        assertTrue(LearningContextV1.validate(c).ok(), () -> String.valueOf(LearningContextV1.validate(c).list()));
        assertEquals(REQ, c.requestId());
        assertFalse(c.contextItems().isEmpty());
        return c;
    }

    static void assertScope(Captured r, LearningContextV1 c) {
        String token = r.header(AiContractSigning.HEADER_SCOPE);
        assertNotNull(token, "X-AI-Scope 누락: " + r.path());
        assertEquals(REQ, r.header("X-Request-ID"));
        String sub = new PseudonymousUserKeys(LearningMemoryFixtures.keys(true, true)).of(USER);
        AiContractSigning.ScopeClaims claims = AiContractSigning.verifyScopeToken(SCOPE_KEY.getBytes(StandardCharsets.UTF_8), token, REQ,
                sub, Instant.now().getEpochSecond());
        assertEquals(c.pseudonymousUserKey(), claims.sub());
        assertEquals(java.util.Set.of(MAT), claims.materialIds());
        assertTrue(claims.exp() - claims.iat() <= 120);
    }

    // ── 플래그 OFF: 바이트 동일 ───────────────────────────────────────────────────────

    @Test
    void flagOffNonStreamBytesIdenticalAndNoHeaderAndNoMemoryReads() throws Exception {
        Ai07Stub legacy = stub();
        Ai07Stub off = stub();
        LearningMemoryFixtures fx = new LearningMemoryFixtures();
        nonStream(chatService(failover(legacy.url()), null));
        ChatDTO.MultiChatResponse r = nonStream(chatService(failover(off.url()), fx.assembler(false)));
        assertEquals(Boolean.TRUE, r.getSuccess());
        Captured a = only(legacy, "/api/ai/multi-chat");
        Captured b = only(off, "/api/ai/multi-chat");
        assertArrayEquals(a.body(), b.body(), "플래그 OFF 요청 본문은 기존과 바이트 동일");
        assertNull(b.header(AiContractSigning.HEADER_SCOPE));
        assertFalse(new String(b.body(), StandardCharsets.UTF_8).contains("learningContext"));
        assertEquals(a.header("X-Request-ID"), b.header("X-Request-ID"));
        verifyNoInteractions(fx.allMocks());
    }

    @Test
    void flagOffStreamBytesIdenticalAndNoHeader() throws Exception {
        Ai07Stub legacy = stub();
        Ai07Stub off = stub();
        LearningMemoryFixtures fx = new LearningMemoryFixtures();
        stream(chatService(failover(legacy.url()), null));
        List<ServerSentEvent<String>> ev = stream(chatService(failover(off.url()), fx.assembler(false)));
        assertTrue(ev.stream().anyMatch(e -> "all_complete".equals(e.event())));
        Captured a = only(legacy, "/api/ai/multi-chat/stream");
        Captured b = only(off, "/api/ai/multi-chat/stream");
        assertArrayEquals(a.body(), b.body());
        assertNull(b.header(AiContractSigning.HEADER_SCOPE));
        verifyNoInteractions(fx.allMocks());
    }

    // ── 플래그 ON ─────────────────────────────────────────────────────────────────

    @Test
    void flagOnNonStreamAppendsValidContextAndSignedScope() throws Exception {
        Ai07Stub off = stub();
        Ai07Stub on = stub();
        nonStream(chatService(failover(off.url()), null));
        ChatDTO.MultiChatResponse r = nonStream(chatService(failover(on.url()), new LearningMemoryFixtures().assembler(true)));
        assertEquals(Boolean.TRUE, r.getSuccess(), "기존 응답 흐름 불변");
        Captured b = only(on, "/api/ai/multi-chat");
        LearningContextV1 c = assertValidContext(assertOnlyLearningContextAppended(only(off, "/api/ai/multi-chat").body(), b.body(),
                "wire-nonstream"));
        assertScope(b, c);
        assertTrue(c.contextItems().stream().noneMatch(i -> i.content().contains(LearningMemoryFixtures.LEGACY_CANARY)));
    }

    @Test
    void flagOnStreamAppendsValidContextAndSignedScope() throws Exception {
        Ai07Stub off = stub();
        Ai07Stub on = stub();
        stream(chatService(failover(off.url()), null));
        List<ServerSentEvent<String>> ev = stream(chatService(failover(on.url()), new LearningMemoryFixtures().assembler(true)));
        assertTrue(ev.stream().anyMatch(e -> "all_complete".equals(e.event())), "SSE 중계 동작 불변");
        assertEquals("done", ev.get(ev.size() - 1).event());
        Captured b = only(on, "/api/ai/multi-chat/stream");
        LearningContextV1 c = assertValidContext(assertOnlyLearningContextAppended(only(off, "/api/ai/multi-chat/stream").body(), b.body(),
                "wire-stream"));
        assertScope(b, c);
    }

    @Test
    void failoverRetriesCarryFreshScopeHeaderOnEveryAttempt() throws Exception {
        Ai07Stub primary = stub();
        Ai07Stub secondary = stub();
        primary.streamStatus = 503;
        secondary.streamStatus = 503; // stream 전부 실패 → non-stream 폴백까지
        List<ServerSentEvent<String>> ev = stream(chatService(failover(primary.url(), secondary.url()),
                new LearningMemoryFixtures().assembler(true)));
        assertTrue(ev.stream().anyMatch(e -> "all_complete".equals(e.event())), "non-stream 폴백으로 완료");
        List<Captured> all = new ArrayList<>(primary.requests);
        all.addAll(secondary.requests);
        assertTrue(all.size() >= 3, "stream×2 + non-stream 시도: " + all.size());
        for (Captured r : all) {
            LearningContextV1 c = assertValidContext(M.readTree(r.body()).get("learningContext"));
            assertScope(r, c);
        }
    }

    @Test
    void flagOnWithoutScopeKeySendsLegacyBytesAndStillAnswers() throws Exception {
        Ai07Stub off = stub();
        Ai07Stub on = stub();
        nonStream(chatService(failover(off.url()), null));
        LearningMemoryFixtures fx = new LearningMemoryFixtures();
        LearningMemoryAssembler noKey = fx.assembler(LearningMemorySettings.forTest(true), LearningMemoryFixtures.keys(false, true));
        ChatDTO.MultiChatResponse r = nonStream(chatService(failover(on.url()), noKey));
        assertEquals(Boolean.TRUE, r.getSuccess(), "키가 없어도 요청은 진행");
        Captured b = only(on, "/api/ai/multi-chat");
        assertArrayEquals(only(off, "/api/ai/multi-chat").body(), b.body(), "fail-closed: learningContext 미전송");
        assertNull(b.header(AiContractSigning.HEADER_SCOPE));
        verifyNoInteractions(fx.allMocks());
    }

    @Test
    void assemblerFailureNeverBreaksChat() throws Exception {
        Ai07Stub off = stub();
        Ai07Stub on = stub();
        nonStream(chatService(failover(off.url()), null));
        LearningMemoryFixtures fx = new LearningMemoryFixtures();
        when(fx.rooms.findById(anyLong())).thenThrow(new IllegalStateException("db down"));
        when(fx.materials.findById(anyLong())).thenThrow(new IllegalStateException("db down"));
        when(fx.reviewNotes.findTop5ByUserIdAndSourceMaterialIdOrderByCreatedAtDesc(anyLong(), anyLong()))
                .thenThrow(new IllegalStateException("db down"));
        when(fx.reviewNotes.findTop20ByUserIdOrderByCreatedAtDesc(anyLong())).thenThrow(new IllegalStateException("db down"));
        when(fx.todos.findTop20ByUserIdAndCompletedFalseAndEndDateGreaterThanEqualOrderByEndDateAsc(anyLong(), any()))
                .thenThrow(new IllegalStateException("db down"));
        when(fx.events.findByUserIdAndEventTypeOrderByCreatedAtDesc(anyLong(), any(), any())).thenThrow(new IllegalStateException("db down"));
        ChatDTO.MultiChatResponse r = nonStream(chatService(failover(on.url()), fx.assembler(true)));
        assertEquals(Boolean.TRUE, r.getSuccess());
        assertArrayEquals(only(off, "/api/ai/multi-chat").body(), only(on, "/api/ai/multi-chat").body());
        Mockito.verify(fx.materials, Mockito.atLeastOnce()).findById(anyLong());
    }
}
