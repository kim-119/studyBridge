package com.studybridge.api.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.ai.AiFailoverExecutor;
import com.studybridge.api.ai.AiUpstream;
import com.studybridge.api.ai.AiUpstreams;
import com.studybridge.api.dto.MindMapAiDTO;
import com.studybridge.api.dto.MindMapAiDTO.MindMapAiRequest;
import com.studybridge.api.dto.MindMapAiDTO.MindMapAiResponse;
import com.studybridge.api.exception.AiUpstreamException;
import com.studybridge.api.service.support.FailoverStubServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.web.reactive.function.client.WebClient;

import java.io.IOException;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Semantic MindMap PRIMARY → SECONDARY failover (S1~S8) + credential (K1/K2). 실제 TCP 스텁 2대.
 */
class SemanticGraphFailoverTest {

    private static final String KEY = "shared-internal-ai-key-64chars-0000000000000000000000000000000000";
    private static final String OK_200 = "{\"schemaVersion\":\"mindmap.semantic.v1\",\"question\":\"q\",\"status\":\"OK\",\"degraded\":false,"
            + "\"nodes\":[{\"id\":\"c_1\",\"type\":\"concept\",\"level\":\"CORE\",\"label\":\"JDBC\",\"canonicalLabel\":\"JDBC\",\"mentions\":3,\"visible\":true}],"
            + "\"edges\":[],\"sourceNodes\":[],\"provenanceEdges\":[],\"rejected\":[],\"validationErrors\":[],\"stats\":{\"conceptCount\":1}}";
    private static final String DEGRADED_200 = OK_200.replace("\"status\":\"OK\",\"degraded\":false", "\"status\":\"DEGRADED\",\"degraded\":true,\"degradedReason\":\"LLM_TIMEOUT_FALLBACK\"");
    private static final String FAILED_422 = "{\"schemaVersion\":\"mindmap.semantic.v1\",\"status\":\"FAILED\",\"degraded\":false,"
            + "\"degradedReason\":\"EMPTY_ANSWER\",\"nodes\":[],\"edges\":[],\"sourceNodes\":[],\"provenanceEdges\":[],\"rejected\":[],\"validationErrors\":[]}";
    private static final String FAILED_500 = "{\"status\":\"FAILED\",\"degradedReason\":\"INTERNAL_ERROR\",\"nodes\":[]}";

    private FailoverStubServer primary;
    private FailoverStubServer secondary;

    @BeforeEach
    void up() throws IOException {
        primary = new FailoverStubServer(FastApiSemanticGraphUpstream.PATH);
        secondary = new FailoverStubServer(FastApiSemanticGraphUpstream.PATH);
        secondary.body = OK_200;
    }

    @AfterEach
    void down() {
        primary.close();
        secondary.close();
    }

    private FastApiSemanticGraphUpstream upstream(WebClient p, WebClient s) {
        AiUpstreams ups = new AiUpstreams(List.of(new AiUpstream("primary", primary.baseUrl(), p), new AiUpstream("secondary", secondary.baseUrl(), s)));
        return new FastApiSemanticGraphUpstream(new AiFailoverExecutor(ups), new ObjectMapper(), 5, KEY);
    }

    private FastApiSemanticGraphUpstream upstream() {
        return upstream(primary.client(5), secondary.client(5));
    }

    private static MindMapAiRequest request() {
        return MindMapAiRequest.builder().question("JDBC가 뭐야?")
                .answers(List.of(MindMapAiDTO.Answer.builder().content("JDBC는 ...").agentId(1).agentName("교수").role("theory").build()))
                .useLlm(true).build();
    }

    @Test
    void s1_primary_200_secondary_zero_calls_k1_primary_credential() throws Exception {
        primary.body = OK_200;
        MindMapAiResponse res = upstream().semanticGraph(request());
        assertEquals("OK", res.getStatus());
        assertEquals(1, primary.hits.get());
        assertEquals(0, secondary.hits.get());
        assertEquals("Bearer " + KEY, primary.authorizationHeaders.get(0));
    }

    @Test
    void s2_primary_connection_refused_secondary_200_k2_secondary_credential() throws Exception {
        MindMapAiResponse res = upstream(FailoverStubServer.refusedClient(), secondary.client(5)).semanticGraph(request());
        assertEquals("OK", res.getStatus());
        assertEquals("JDBC", res.getNodes().get(0).getCanonicalLabel());
        assertEquals(0, primary.hits.get());
        assertEquals(1, secondary.hits.get());
        assertEquals("Bearer " + KEY, secondary.authorizationHeaders.get(0), "secondary 에 동일 credential");
    }

    @Test
    void s3_primary_timeout_secondary_200() throws Exception {
        primary.body = OK_200;
        primary.delayMs = 3000;
        MindMapAiResponse res = upstream(primary.client(1), secondary.client(5)).semanticGraph(request());
        assertEquals("OK", res.getStatus());
        assertEquals(1, primary.hits.get());
        assertEquals(1, secondary.hits.get());
    }

    @Test
    void s4_primary_500_secondary_200() throws Exception {
        primary.status = 500;
        primary.body = FAILED_500;
        MindMapAiResponse res = upstream().semanticGraph(request());
        assertEquals("OK", res.getStatus());
        assertEquals(1, primary.hits.get());
        assertEquals(1, secondary.hits.get());
    }

    @Test
    void s5_primary_404_route_drift_secondary_200() throws Exception {
        primary.status = 404;
        primary.body = "{\"detail\":\"Not Found\"}";
        MindMapAiResponse res = upstream().semanticGraph(request());
        assertEquals("OK", res.getStatus());
        assertEquals(1, secondary.hits.get());
    }

    @Test
    void s6_primary_422_empty_answer_no_failover_and_error_contract_preserved() {
        primary.status = 422;
        primary.body = FAILED_422;
        SemanticGraphUpstream.UpstreamException ex = assertThrows(SemanticGraphUpstream.UpstreamException.class,
                () -> upstream().semanticGraph(request()));
        assertEquals(422, ex.getHttpStatus());
        assertEquals("EMPTY_ANSWER", ex.getReasonCode());
        assertEquals(0, secondary.hits.get(), "domain 422 는 secondary 로 보내지 않는다");
        AiUpstreamException http = MindmapSemanticGraphService.toHttpFailure(ex);
        assertEquals(422, http.getStatus().value());
        assertEquals("EMPTY_ANSWER", http.getUpstreamCode());
    }

    @Test
    void s6b_primary_401_no_failover() {
        primary.status = 401;
        primary.body = "{\"detail\":\"AI 서버 인증에 실패했습니다.\"}";
        SemanticGraphUpstream.UpstreamException ex = assertThrows(SemanticGraphUpstream.UpstreamException.class,
                () -> upstream().semanticGraph(request()));
        assertEquals(401, ex.getHttpStatus());
        assertEquals(0, secondary.hits.get());
    }

    @Test
    void s7_primary_degraded_is_normal_response_no_failover() throws Exception {
        primary.body = DEGRADED_200;
        MindMapAiResponse res = upstream().semanticGraph(request());
        assertEquals("DEGRADED", res.getStatus());
        assertTrue(Boolean.TRUE.equals(res.getDegraded()));
        assertEquals(1, res.getNodes().size());
        assertEquals(0, secondary.hits.get());
    }

    @Test
    void s8_both_fail_keeps_existing_error_contract() {
        primary.status = 500;
        primary.body = FAILED_500;
        secondary.status = 504;
        secondary.body = "{\"status\":\"FAILED\",\"degradedReason\":\"TIMEOUT\"}";
        SemanticGraphUpstream.UpstreamException ex = assertThrows(SemanticGraphUpstream.UpstreamException.class,
                () -> upstream().semanticGraph(request()));
        assertEquals(504, ex.getHttpStatus(), "마지막 업스트림의 실패가 기존 UpstreamException 계약으로 전달");
        assertEquals("TIMEOUT", ex.getReasonCode());
        assertEquals(1, primary.hits.get());
        assertEquals(1, secondary.hits.get());
        assertEquals(504, MindmapSemanticGraphService.toHttpFailure(ex).getStatus().value());

        // 둘 다 연결 불가 → UPSTREAM_UNREACHABLE → 503
        SemanticGraphUpstream.UpstreamException ex2 = assertThrows(SemanticGraphUpstream.UpstreamException.class,
                () -> {
                    try {
                        upstream(FailoverStubServer.refusedClient(), FailoverStubServer.refusedClient()).semanticGraph(request());
                    } catch (IOException e) {
                        throw new RuntimeException(e);
                    }
                });
        assertEquals("UPSTREAM_UNREACHABLE", ex2.getReasonCode());
        assertEquals(503, MindmapSemanticGraphService.toHttpFailure(ex2).getStatus().value());
        assertNotNull(ex2.getMessage());
    }
}
