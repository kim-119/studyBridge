package com.studybridge.api.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.ai.quality.GateEvidence;
import com.studybridge.api.dto.MindMapAiDTO;
import com.studybridge.api.dto.MindMapAiDTO.MindMapAiResponse;
import com.studybridge.api.dto.MindmapSemanticGraphDTO;
import com.studybridge.api.dto.MindmapSemanticGraphDTO.AnswerSource;
import com.studybridge.api.dto.MindmapSemanticGraphDTO.Response;
import com.studybridge.api.entity.AgentChatRoom;
import com.studybridge.api.entity.User;
import com.studybridge.api.exception.AiUpstreamException;
import com.studybridge.api.repository.AgentChatRoomRepository;
import com.studybridge.api.service.support.ChatGateStubServer;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.data.redis.core.ValueOperations;

/**
 * 마인드맵 Semantic Graph 품질 게이트(SEMANTIC_GRAPH/graph_json): 79 거절 → 80 승인분만 응답·q1 캐시, 전부 거절/평가기 503 은
 * 422/503 + 캐시 0, 레거시(미검증) 캐시 미노출, 승인 캐시는 AI·평가 0, hardFail 거절, 업스트림 실패는 기존 계약, 게이트 OFF 회귀 없음.
 */
class MindmapSemanticGraphQualityGateTest {

    static final long USER = 55L;
    static final long ROOM = 231L;
    static final ObjectMapper M = new ObjectMapper();

    ChatGateStubServer stub;
    final Map<String, Object> redisStore = new LinkedHashMap<>();
    final AtomicInteger upstreamCalls = new AtomicInteger();
    volatile SemanticGraphUpstream.UpstreamException failure;

    @BeforeEach
    void up() throws Exception {
        stub = new ChatGateStubServer();
    }

    @AfterEach
    void down() {
        stub.close();
    }

    @SuppressWarnings("unchecked")
    MindmapSemanticGraphService service(boolean gateOn) {
        AgentChatRoomRepository rooms = mock(AgentChatRoomRepository.class);
        AgentChatRoom room = new AgentChatRoom();
        room.setId(ROOM);
        room.setUser(User.builder().id(USER).build());
        Mockito.when(rooms.findById(ROOM)).thenReturn(Optional.of(room));
        ValueOperations<String, Object> ops = mock(ValueOperations.class, inv -> {
            String m = inv.getMethod().getName();
            Object[] a = inv.getArguments();
            if (m.equals("get")) return redisStore.get((String) a[0]);
            if (m.equals("set")) { redisStore.put((String) a[0], a[1]); return null; }
            return null;
        });
        RedisTemplate<String, Object> redis = mock(RedisTemplate.class, inv -> inv.getMethod().getName().equals("opsForValue") ? ops : null);
        SemanticGraphUpstream upstream = req -> {
            int n = upstreamCalls.incrementAndGet();
            if (failure != null) throw failure;
            return graph("초안" + n);
        };
        MindmapSemanticGraphService svc = new MindmapSemanticGraphService(rooms, redis, upstream, new ObjectMapper(), 168);
        svc.setQualityGate(stub.gate(gateOn));
        return svc;
    }

    static MindmapSemanticGraphDTO.Request req() {
        List<AnswerSource> list = new ArrayList<>();
        list.add(AnswerSource.builder().messageId(100L).agentId(10L).agentName("개념 정리 교수").agentRole("theory")
                .content("JDBC 는 Java Database Connectivity 로, 자바에서 데이터베이스에 연결해 SQL 을 실행하는 표준 API 다. Connection 객체가 연결을 나타낸다.")
                .build());
        return MindmapSemanticGraphDTO.Request.builder().roomId(ROOM).question("JDBC가 뭐야?").answers(list).build();
    }

    /** 시도마다 설명 문구가 달라지는 그래프(초안 번호가 description 에 들어간다). */
    static MindMapAiResponse graph(String draft) {
        MindMapAiResponse r = MindMapAiResponse.builder().schemaVersion("mindmap.semantic.v1").status("OK").extractor("llm").analyzer("kiwi").build();
        r.setNodes(new ArrayList<>(List.of(
                MindMapAiDTO.Node.builder().id("q_1").type("question").level("QUESTION").label("JDBC가 뭐야?").visible(true).build(),
                MindMapAiDTO.Node.builder().id("c_1").type("concept").level("CORE").label("JDBC").canonicalLabel("JDBC")
                        .aliases(List.of("JDBC가")).surfaceForms(List.of("JDBC가")).body(draft + " 자바 데이터베이스 연결 API").visible(true).build(),
                MindMapAiDTO.Node.builder().id("c_2").type("concept").level("PRIMARY").label("Connection").canonicalLabel("Connection")
                        .visible(true).build())));
        r.setEdges(new ArrayList<>(List.of(
                MindMapAiDTO.Edge.builder().id("e_0").from("q_1").to("c_1").kind("topic").relation("주제").relationKey("TOPIC").build(),
                MindMapAiDTO.Edge.builder().id("e_1").from("c_1").to("c_2").kind("semantic").relation("구성 요소").relationKey("COMPONENT").build())));
        r.setSourceNodes(new ArrayList<>(List.of(
                MindMapAiDTO.Node.builder().id("s_1").type("agent").level("SOURCE").label("개념 정리 교수").agentKey("agent:10").build())));
        r.setProvenanceEdges(new ArrayList<>(List.of(
                MindMapAiDTO.Edge.builder().id("p_1").from("s_1").to("c_1").kind("provenance").relation("출처").relationKey("SOURCE").build())));
        return r;
    }

    String gatedKeyFor(Response r) {
        return String.format(MindmapSemanticGraphService.GATED_CACHE_KEY_PREFIX, ROOM, r.getFingerprint());
    }

    boolean anyCacheContains(String needle) {
        return redisStore.values().stream().anyMatch(v -> String.valueOf(v).contains(needle));
    }

    @GateEvidence({"POST /api/mindmap/semantic-graph"})
    @Test
    void rejected79ThenApproved80IsServedAndOnlyApprovedIsCached() throws Exception {
        stub.policy = (n, in) -> n == 1 ? ChatGateStubServer.out(79, "REJECTED", false) : ChatGateStubServer.out(80, "APPROVED", false);
        Response r = service(true).semanticGraph(USER, req());
        assertEquals("APPROVED", r.getQualityStatus());
        assertEquals(80.0, r.getQualityScore());
        assertTrue(r.getConcepts().get(0).getDescription().startsWith("초안2"), "재생성된 두 번째 그래프만 노출");
        assertEquals(2, upstreamCalls.get());
        assertEquals(2, stub.evaluations.size());
        JsonNode ev = stub.evaluations.get(0);
        assertEquals("SEMANTIC_GRAPH", ev.get("taskType").asText());
        assertEquals("graph_json", ev.get("outputKind").asText());
        JsonNode proposed = ev.get("proposedOutput");
        assertTrue(proposed.get("nodes").isArray() && proposed.get("edges").isArray(), "그래프 JSON(nodes/edges) 그대로 평가");
        assertTrue(proposed.toString().contains("초안1") && proposed.toString().contains("구성 요소") && proposed.toString().contains("개념 정리 교수"),
                "개념 설명·관계명·출처 라벨 전부 평가 대상");
        for (JsonNode e : proposed.get("edges")) {
            Map<String, Boolean> ids = new LinkedHashMap<>();
            proposed.get("nodes").forEach(n -> ids.put(n.get("id").asText(), true));
            assertTrue(ids.containsKey(e.get("from").asText()) && ids.containsKey(e.get("to").asText()), "끊긴 간선 없음(GRAPH_DANGLING_EDGE 방지)");
        }
        assertEquals("CHAT_ANSWER", ev.get("groundingEvidence").get(0).get("sourceType").asText());
        assertTrue(ev.get("groundingEvidence").get(0).get("text").asText().contains("Java Database Connectivity"), "답변 원문 근거 동봉");
        // 캐시: q1(게이트) 키에 승인분만, 레거시 키 미사용, 거절된 초안 1 은 어디에도 없음
        Object cached = redisStore.get(gatedKeyFor(r));
        assertTrue(String.valueOf(cached).contains("초안2") && String.valueOf(cached).contains("\"qualityStatus\":\"APPROVED\""));
        assertFalse(anyCacheContains("초안1"));
        assertNull(redisStore.get(String.format(MindmapSemanticGraphService.CACHE_KEY_PREFIX, ROOM, r.getFingerprint())));
    }

    @GateEvidence({"POST /api/mindmap/semantic-graph"})
    @Test
    void threeRejectionsAreExplicitFailureWithNothingCached() {
        stub.policy = (n, in) -> ChatGateStubServer.out(70, "REJECTED", false);
        AiUpstreamException e = assertThrows(AiUpstreamException.class, () -> service(true).semanticGraph(USER, req()));
        assertEquals("AI_QUALITY_REJECTED", e.getCode());
        assertEquals(422, e.getStatus().value());
        assertTrue(e.isRetryable());
        assertEquals(3, upstreamCalls.get(), "최초 1 + 재생성 2");
        assertTrue(redisStore.isEmpty(), "미승인 그래프는 캐시하지 않는다");
        assertFalse(e.getMessage().contains("초안"));
    }

    @Test
    void hardFailIsRejectedEvenWithHighScore() {
        stub.policy = (n, in) -> ChatGateStubServer.out(95, "REJECTED", true);
        AiUpstreamException e = assertThrows(AiUpstreamException.class, () -> service(true).semanticGraph(USER, req()));
        assertEquals("AI_QUALITY_REJECTED", e.getCode());
        assertTrue(redisStore.isEmpty());
    }

    @Test
    void evaluatorDownIsUnavailableWithoutRegeneration() {
        stub.policy = (n, in) -> null; // 503
        AiUpstreamException e = assertThrows(AiUpstreamException.class, () -> service(true).semanticGraph(USER, req()));
        assertEquals("AI_QUALITY_UNAVAILABLE", e.getCode());
        assertEquals(503, e.getStatus().value());
        assertEquals(1, upstreamCalls.get(), "평가기 장애는 재생성하지 않는다");
        assertTrue(redisStore.isEmpty());
    }

    @GateEvidence({"POST /api/mindmap/semantic-graph"})
    @Test
    void legacyUnverifiedCacheIsNotServedAndApprovedCacheNeedsNoAi() throws Exception {
        // 게이트 OFF 로 만든 레거시 캐시(미검증)
        MindmapSemanticGraphService off = service(false);
        Response legacy = off.semanticGraph(USER, req());
        assertNull(legacy.getQualityStatus());
        assertEquals(0, stub.evaluations.size(), "게이트 OFF: 평가기 호출 0");
        String legacyKey = String.format(MindmapSemanticGraphService.CACHE_KEY_PREFIX, ROOM, legacy.getFingerprint());
        assertTrue(redisStore.containsKey(legacyKey));
        // 게이트 ON: 레거시 캐시는 쓰지 않고 새로 생성·평가
        upstreamCalls.set(0);
        MindmapSemanticGraphService on = service(true);
        Response fresh = on.semanticGraph(USER, req());
        assertEquals("APPROVED", fresh.getQualityStatus());
        assertFalse(fresh.isCached());
        assertEquals(1, upstreamCalls.get());
        assertEquals(1, stub.evaluations.size());
        // 승인 캐시는 AI·평가 없이 재사용
        Response again = on.semanticGraph(USER, req());
        assertTrue(again.isCached());
        assertEquals("APPROVED", again.getQualityStatus());
        assertEquals(1, upstreamCalls.get());
        assertEquals(1, stub.evaluations.size());
    }

    @Test
    void gatedKeyValueWithoutApprovalMarkIsIgnored() throws Exception {
        MindmapSemanticGraphService on = service(true);
        Response first = on.semanticGraph(USER, req());
        // 누군가 q1 키에 판정 없는 값을 써 넣어도(레거시 변환 등) 게이트 ON 은 노출하지 않는다.
        Response tampered = M.readValue(String.valueOf(redisStore.get(gatedKeyFor(first))), Response.class);
        tampered.setQualityStatus(null);
        tampered.getConcepts().get(0).setDescription("미검증 설명");
        redisStore.put(gatedKeyFor(first), M.writeValueAsString(tampered));
        Response r = on.semanticGraph(USER, req());
        assertFalse(r.getConcepts().get(0).getDescription().contains("미검증"));
        assertEquals(2, upstreamCalls.get());
    }

    @Test
    void upstreamFailureKeepsLegacyContractWithoutEvaluation() {
        failure = new SemanticGraphUpstream.UpstreamException("NO_VALID_CONCEPTS", 422, null, "no concepts", null);
        AiUpstreamException e = assertThrows(AiUpstreamException.class, () -> service(true).semanticGraph(USER, req()));
        assertEquals(422, e.getStatus().value());
        assertEquals("NO_VALID_CONCEPTS", e.getUpstreamCode());
        assertEquals(1, upstreamCalls.get(), "생성 실패는 재생성하지 않는다");
        assertEquals(0, stub.evaluations.size());
        assertTrue(redisStore.isEmpty());
    }

    @Test
    void gateOffIsLegacyBehaviour() {
        Response r = service(false).semanticGraph(USER, req());
        assertNull(r.getQualityStatus());
        assertNull(r.getVerified());
        assertEquals(0, stub.evaluations.size());
        assertEquals(1, redisStore.size());
        assertTrue(redisStore.keySet().iterator().next().startsWith("studybridge:mindmap:semantic:" + ROOM + ":"));
    }
}
