package com.studybridge.api.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.dto.MindMapAiDTO;
import com.studybridge.api.dto.MindMapAiDTO.MindMapAiRequest;
import com.studybridge.api.dto.MindMapAiDTO.MindMapAiResponse;
import com.studybridge.api.dto.MindmapSemanticGraphDTO;
import com.studybridge.api.dto.MindmapSemanticGraphDTO.AnswerSource;
import com.studybridge.api.dto.MindmapSemanticGraphDTO.Response;
import com.studybridge.api.entity.AgentChatRoom;
import com.studybridge.api.entity.User;
import com.studybridge.api.exception.AiUpstreamException;
import com.studybridge.api.repository.AgentChatRoomRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.data.redis.core.RedisTemplate;
import org.springframework.data.redis.core.ValueOperations;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.NoSuchElementException;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import java.util.stream.Collectors;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;

/**
 * Semantic MindMap 릴레이 단위 테스트(AI07 FINAL CONTRACT mindmap.semantic.v1, M1~M10 서버측).
 *  · Redis 는 인메모리 Map fake, AI07 은 typed SemanticGraphUpstream stub.
 *  · 개념 라벨은 AI07 canonicalLabel 그대로 통과하고, 서버는 어떤 토큰/키워드 개념도 새로 만들지 않는다.
 *  · 422/500/504 FAILED 는 AiUpstreamException(실제 HTTP 상태) 로 올라가며 폴백 그래프가 없다.
 */
class MindmapSemanticGraphServiceTest {

    private static final long USER = 55L;
    private static final long ROOM = 231L;

    private final Map<String, Object> redisStore = new LinkedHashMap<>();
    private final AtomicInteger upstreamCalls = new AtomicInteger();
    private final AtomicReference<MindMapAiRequest> lastRequest = new AtomicReference<>();
    private MindMapAiResponse nextUpstream;
    private SemanticGraphUpstream.UpstreamException nextFailure;

    private MindmapSemanticGraphService service;

    @SuppressWarnings("unchecked")
    @BeforeEach
    void setUp() {
        redisStore.clear();
        upstreamCalls.set(0);
        nextFailure = null;

        AgentChatRoomRepository rooms = mock(AgentChatRoomRepository.class);
        AgentChatRoom room = new AgentChatRoom();
        room.setId(ROOM);
        room.setUser(User.builder().id(USER).build());
        Mockito.when(rooms.findById(ROOM)).thenReturn(Optional.of(room));
        Mockito.when(rooms.findById(999L)).thenReturn(Optional.empty());

        ValueOperations<String, Object> ops = mock(ValueOperations.class, inv -> {
            String m = inv.getMethod().getName();
            Object[] a = inv.getArguments();
            if (m.equals("get")) return redisStore.get((String) a[0]);
            if (m.equals("set")) { redisStore.put((String) a[0], a[1]); return null; }
            return null;
        });
        RedisTemplate<String, Object> redis = mock(RedisTemplate.class, inv -> {
            if (inv.getMethod().getName().equals("opsForValue")) return ops;
            return null;
        });

        SemanticGraphUpstream upstream = req -> {
            upstreamCalls.incrementAndGet();
            lastRequest.set(req);
            if (nextFailure != null) throw nextFailure;
            return nextUpstream;
        };
        service = new MindmapSemanticGraphService(rooms, redis, upstream, new ObjectMapper(), 168);
    }

    private static MindmapSemanticGraphDTO.Request req(String question, String... answers) {
        List<AnswerSource> list = new ArrayList<>();
        int i = 0;
        for (String a : answers) {
            list.add(AnswerSource.builder().messageId(100L + i).agentId(10L + i).agentName("교수" + (i + 1)).agentRole("theory").content(a).build());
            i++;
        }
        return MindmapSemanticGraphDTO.Request.builder().roomId(ROOM).question(question).answers(list).build();
    }

    private static MindMapAiDTO.Node concept(String id, String label, String level, String... aliases) {
        return MindMapAiDTO.Node.builder().id(id).type("concept").level(level).label(label).canonicalLabel(label)
                .aliases(List.of(aliases)).surfaceForms(List.of(aliases)).mentions(1).visible(true).build();
    }

    private static MindMapAiDTO.Edge edge(String id, String from, String to, String kind, String relation, String key) {
        return MindMapAiDTO.Edge.builder().id(id).from(from).to(to).kind(kind).relation(relation).relationKey(key).build();
    }

    /** 계약 예시: JDBC ─[정의]→ Java Database Connectivity, ─[목적]→ 데이터베이스 연결, ─[수행]→ SQL 실행, ─[구성 요소]→ Connection. */
    private static MindMapAiResponse jdbcGraph(String status) {
        MindMapAiResponse r = MindMapAiResponse.builder()
                .schemaVersion("mindmap.semantic.v1").question("JDBC가 뭐야?").status(status)
                .degraded("DEGRADED".equals(status)).degradedReason("DEGRADED".equals(status) ? "LLM_TIMEOUT_DETERMINISTIC_FALLBACK" : null)
                .degradedReasons("DEGRADED".equals(status) ? List.of("LLM_TIMEOUT_DETERMINISTIC_FALLBACK") : List.of())
                .extractor("DEGRADED".equals(status) ? "deterministic" : "llm").analyzer("kiwi")
                .build();
        r.setNodes(new ArrayList<>(List.of(
                MindMapAiDTO.Node.builder().id("q_1").type("question").level("QUESTION").label("JDBC가 뭐야?").body("JDBC가 뭐야?").visible(true).build(),
                concept("c_1", "JDBC", "CORE", "JDBC가", "JDBC의", "JDBC를"),
                concept("c_2", "Java Database Connectivity", "PRIMARY"),
                concept("c_3", "데이터베이스 연결", "PRIMARY"),
                concept("c_4", "SQL 실행", "PRIMARY"),
                concept("c_5", "Connection", "SECONDARY"))));
        r.setEdges(new ArrayList<>(List.of(
                edge("e_0", "q_1", "c_1", "topic", "주제", "TOPIC"),
                edge("e_1", "c_1", "c_2", "semantic", "정의", "DEFINITION"),
                edge("e_2", "c_1", "c_3", "semantic", "목적", "PURPOSE"),
                edge("e_3", "c_1", "c_4", "semantic", "수행", "PERFORMS"),
                edge("e_4", "c_1", "c_5", "semantic", "구성 요소", "COMPONENT"))));
        r.setSourceNodes(new ArrayList<>(List.of(
                MindMapAiDTO.Node.builder().id("s_1").type("agent").level("SOURCE").label("개념 정리 교수").agentKey("agent:10").build())));
        r.setProvenanceEdges(new ArrayList<>(List.of(edge("p_1", "s_1", "c_1", "provenance", "출처", "SOURCE"))));
        r.setRejected(new ArrayList<>(List.of(MindMapAiDTO.RejectedConcept.builder().surfaceForm("있는").reason("STOPWORD").build())));
        r.setStats(new LinkedHashMap<>(Map.of("conceptCount", 5)));
        return r;
    }

    @Test
    void m1_m4_canonical_concepts_relations_and_hierarchy_pass_through() {
        nextUpstream = jdbcGraph("OK");
        Response r = service.semanticGraph(USER, req("JDBC가 뭐야?", "JDBC가 뭐냐면 JDBC의 정의는 Java Database Connectivity 입니다."));

        assertEquals("OK", r.getStatus());
        assertFalse(r.isDegraded());
        assertEquals("mindmap.semantic.v1", r.getSchemaVersion());
        assertEquals("llm", r.getExtractor());
        assertEquals("kiwi", r.getAnalyzer());
        assertEquals(1, r.getRejectedCount());
        List<String> labels = r.getConcepts().stream().map(MindmapSemanticGraphDTO.Concept::getLabel).collect(Collectors.toList());
        assertEquals(List.of("JDBC", "Java Database Connectivity", "데이터베이스 연결", "SQL 실행", "Connection"), labels);
        // 질문 노드는 concept 가 아니다(기존 question 노드가 담당)
        assertFalse(labels.contains("JDBC가 뭐야?"));
        // 관계: topic 간선은 relations 에서 제외, semantic 은 relation/relationKey 그대로
        assertEquals(4, r.getRelations().size());
        assertEquals("정의", r.getRelations().get(0).getLabel());
        assertEquals("DEFINITION", r.getRelations().get(0).getRelationKey());
        assertEquals("c_1", r.getRelations().get(0).getFrom());
        assertEquals("c_2", r.getRelations().get(0).getTo());
        // 계층: CORE=0, PRIMARY=1, SECONDARY=2 + levelName 보존, 하위의 parentId 힌트
        assertEquals(0, r.getConcepts().get(0).getLevel());
        assertEquals("CORE", r.getConcepts().get(0).getLevelName());
        assertEquals(2, r.getConcepts().get(4).getLevel());
        assertEquals("c_1", r.getConcepts().get(4).getParentId());
        // 1.7 provenance: 교수는 concept 가 아니라 source 레이어
        assertEquals(1, r.getSources().size());
        assertEquals("개념 정리 교수", r.getSources().get(0).getLabel());
        assertEquals("agent:10", r.getSources().get(0).getAgentKey());
        assertEquals(1, r.getProvenance().size());
        assertEquals("SOURCE", r.getProvenance().get(0).getRelationKey());
        assertEquals("출처", r.getProvenance().get(0).getLabel());
    }

    @Test
    void m2_server_never_fabricates_surface_form_or_stopword_concepts() {
        nextUpstream = jdbcGraph("OK");
        Response r = service.semanticGraph(USER, req("JDBC가 뭐야?",
                "JDBC가 있는 플랫폼에서의 JDBC의 역할을 말할 수 있다. JDBC를 사용한다."));
        List<String> labels = r.getConcepts().stream().map(MindmapSemanticGraphDTO.Concept::getLabel).collect(Collectors.toList());
        for (String junk : List.of("JDBC가", "JDBC의", "JDBC를", "플랫폼에서의", "있는", "말할")) {
            assertFalse(labels.contains(junk), "junk concept leaked: " + junk);
        }
        assertTrue(r.getConcepts().get(0).getSurfaceForms().contains("JDBC가"), "표면형은 surfaceForms 로만 남는다");
        assertEquals(labels.size(), labels.stream().map(String::toLowerCase).distinct().count());
    }

    @Test
    void contract_request_shape_and_limits() {
        nextUpstream = jdbcGraph("OK");
        StringBuilder longAnswer = new StringBuilder();
        while (longAnswer.length() < 25000) longAnswer.append("JDBC 설명 ");
        String[] fourteen = new String[14];
        for (int i = 0; i < 14; i++) fourteen[i] = "답변 " + i + " " + longAnswer;
        MindmapSemanticGraphDTO.Request request = req("q".repeat(2500), fourteen);
        request.getAnswers().get(0).setAgentName("N".repeat(150));
        service.semanticGraph(USER, request);

        MindMapAiRequest sent = lastRequest.get();
        assertNotNull(sent);
        assertEquals(Boolean.TRUE, sent.getUseLlm());
        assertEquals(MindMapAiDTO.MAX_QUESTION, sent.getQuestion().length());
        assertEquals(MindMapAiDTO.MAX_ANSWERS, sent.getAnswers().size(), "answers 최대 12");
        assertEquals(MindMapAiDTO.MAX_CONTENT, sent.getAnswers().get(0).getContent().length(), "content 최대 20000");
        assertEquals(MindMapAiDTO.MAX_AGENT_NAME, sent.getAnswers().get(0).getAgentName().length());
        assertEquals(10L, sent.getAnswers().get(0).getAgentId());
        assertEquals("theory", sent.getAnswers().get(0).getRole());
        // 본문은 토큰화되지 않고 원문 그대로 시작한다
        assertTrue(sent.getAnswers().get(1).getContent().startsWith("답변 1 JDBC 설명"));
    }

    @Test
    void m5_degraded_is_renderable_and_identifiable() {
        nextUpstream = jdbcGraph("DEGRADED");
        Response r = service.semanticGraph(USER, req("q", "a"));
        assertEquals("DEGRADED", r.getStatus());
        assertTrue(r.isDegraded());
        assertEquals("LLM_TIMEOUT_DETERMINISTIC_FALLBACK", r.getDegradedReason());
        assertEquals(List.of("LLM_TIMEOUT_DETERMINISTIC_FALLBACK"), r.getDegradedReasons());
        assertEquals("deterministic", r.getExtractor());
        assertEquals(5, r.getConcepts().size());
        assertEquals(1, redisStore.size(), "DEGRADED 도 캐시된다(렌더 가능 결과)");
    }

    @Test
    void m6_422_failed_maps_to_422_with_upstream_reason_and_no_fallback() {
        MindMapAiResponse failedBody = MindMapAiResponse.builder().status("FAILED").degradedReason("NO_VALID_CONCEPTS").build();
        nextFailure = new SemanticGraphUpstream.UpstreamException("NO_VALID_CONCEPTS", 422, failedBody, "422", null);
        AiUpstreamException ex = assertThrows(AiUpstreamException.class,
                () -> service.semanticGraph(USER, req("JDBC가 뭐야?", "JDBC가 JDBC의 JDBC를 있는 말할")));
        assertEquals(422, ex.getStatus().value());
        assertEquals("NO_VALID_CONCEPTS", ex.getUpstreamCode());
        assertEquals(422, ex.getUpstreamStatus());
        assertTrue(redisStore.isEmpty(), "FAILED 는 캐시하지 않는다");
    }

    @Test
    void m7_500_failed_maps_to_502() {
        MindMapAiResponse failedBody = MindMapAiResponse.builder().status("FAILED").degradedReason("GRAPH_VALIDATION_FAILED").build();
        nextFailure = new SemanticGraphUpstream.UpstreamException("GRAPH_VALIDATION_FAILED", 500, failedBody, "500", null);
        AiUpstreamException ex = assertThrows(AiUpstreamException.class, () -> service.semanticGraph(USER, req("q", "a")));
        assertEquals(502, ex.getStatus().value());
        assertEquals("AI_UPSTREAM_FAILED", ex.getCode());
        assertEquals("GRAPH_VALIDATION_FAILED", ex.getUpstreamCode());
        assertTrue(ex.isRetryable());
    }

    @Test
    void m8_504_timeout_maps_to_504() {
        nextFailure = new SemanticGraphUpstream.UpstreamException("TIMEOUT", 504,
                MindMapAiResponse.builder().status("FAILED").degradedReason("TIMEOUT").build(), "504", null);
        AiUpstreamException ex = assertThrows(AiUpstreamException.class, () -> service.semanticGraph(USER, req("q", "a")));
        assertEquals(504, ex.getStatus().value());
        assertEquals("AI_UPSTREAM_TIMEOUT", ex.getCode());
        assertEquals("TIMEOUT", ex.getUpstreamCode());
        // 전송 계층 timeout(HTTP 없음) 도 504
        nextFailure = new SemanticGraphUpstream.UpstreamException("TIMEOUT", null, null, "block timeout", null);
        assertEquals(504, assertThrows(AiUpstreamException.class, () -> service.semanticGraph(USER, req("q", "b"))).getStatus().value());
    }

    @Test
    void route_missing_and_unreachable_are_502_503() {
        nextFailure = new SemanticGraphUpstream.UpstreamException("UPSTREAM_ROUTE_NOT_FOUND", 404, null, "404", null);
        AiUpstreamException ex = assertThrows(AiUpstreamException.class, () -> service.semanticGraph(USER, req("q", "a")));
        assertEquals(502, ex.getStatus().value());
        assertEquals("UPSTREAM_ROUTE_NOT_FOUND", ex.getUpstreamCode());
        nextFailure = new SemanticGraphUpstream.UpstreamException("UPSTREAM_UNREACHABLE", null, null, "refused", null);
        assertEquals(503, assertThrows(AiUpstreamException.class, () -> service.semanticGraph(USER, req("q", "b"))).getStatus().value());
    }

    @Test
    void failed_smuggled_in_200_or_empty_graph_is_not_treated_as_success() {
        MindMapAiResponse smuggled = jdbcGraph("OK");
        smuggled.setStatus("FAILED");
        smuggled.setDegradedReason("INTERNAL_ERROR");
        nextUpstream = smuggled;
        AiUpstreamException ex = assertThrows(AiUpstreamException.class, () -> service.semanticGraph(USER, req("q", "a")));
        assertEquals(502, ex.getStatus().value());
        assertEquals("INTERNAL_ERROR", ex.getUpstreamCode());

        MindMapAiResponse empty = jdbcGraph("OK");
        empty.setNodes(new ArrayList<>());
        empty.setEdges(new ArrayList<>());
        nextUpstream = empty;
        AiUpstreamException ex2 = assertThrows(AiUpstreamException.class, () -> service.semanticGraph(USER, req("q", "b")));
        assertEquals(422, ex2.getStatus().value());
        assertEquals("NO_VALID_CONCEPTS", ex2.getUpstreamCode());
        assertTrue(redisStore.isEmpty());
    }

    @Test
    void lazy_cache_same_answers_hit_cache_and_do_not_call_llm_again() {
        nextUpstream = jdbcGraph("OK");
        Response first = service.semanticGraph(USER, req("JDBC가 뭐야?", "답변 A", "답변 B"));
        Response second = service.semanticGraph(USER, req("JDBC가 뭐야?", "답변 A", "답변 B"));
        assertEquals(1, upstreamCalls.get(), "동일 fingerprint 재진입은 업스트림을 다시 부르지 않는다");
        assertFalse(first.isCached());
        assertTrue(second.isCached());
        assertEquals(first.getFingerprint(), second.getFingerprint());
        assertEquals(first.getConcepts().size(), second.getConcepts().size());
        assertTrue(redisStore.keySet().iterator().next().startsWith("studybridge:mindmap:semantic:" + ROOM + ":"));

        service.semanticGraph(USER, req("JDBC가 뭐야?", "답변 A", "답변 C"));
        assertEquals(2, upstreamCalls.get(), "답변이 바뀌면 재생성");

        MindmapSemanticGraphDTO.Request force = req("JDBC가 뭐야?", "답변 A", "답변 B");
        force.setForceRefresh(true);
        service.semanticGraph(USER, force);
        assertEquals(3, upstreamCalls.get(), "forceRefresh 는 캐시 무시");
    }

    @Test
    void empty_answers_are_422_without_calling_upstream() {
        AiUpstreamException ex = assertThrows(AiUpstreamException.class, () -> service.semanticGraph(USER, req("질문만")));
        assertEquals(422, ex.getStatus().value());
        assertEquals("EMPTY_ANSWER", ex.getUpstreamCode());
        assertEquals(0, upstreamCalls.get());
    }

    @Test
    void m10_room_ownership_is_enforced_before_any_upstream_call() {
        nextUpstream = jdbcGraph("OK");
        assertThrows(SecurityException.class, () -> service.semanticGraph(77L, req("q", "a")));
        MindmapSemanticGraphDTO.Request missing = req("q", "a");
        missing.setRoomId(999L);
        assertThrows(NoSuchElementException.class, () -> service.semanticGraph(USER, missing));
        assertEquals(0, upstreamCalls.get());
    }

    @Test
    void edges_referencing_unknown_or_source_nodes_are_dropped_and_invisible_nodes_skipped() {
        MindMapAiResponse raw = jdbcGraph("OK");
        raw.getNodes().add(MindMapAiDTO.Node.builder().id("c_9").type("concept").level("SECONDARY").label("숨김").canonicalLabel("숨김").visible(false).build());
        raw.getEdges().add(edge("e_9", "c_1", "ghost", "semantic", "관련", "RELATED"));
        raw.getEdges().add(edge("e_10", "s_1", "c_1", "semantic", "언급", "RELATED"));
        raw.getEdges().add(edge("e_11", "c_1", "c_9", "semantic", "관련", "RELATED"));
        nextUpstream = raw;
        Response r = service.semanticGraph(USER, req("q", "a"));
        assertEquals(5, r.getConcepts().size());
        assertEquals(4, r.getRelations().size());
        assertNotNull(r.getFingerprint());
        assertNull(r.getDegradedReason());
    }
}
