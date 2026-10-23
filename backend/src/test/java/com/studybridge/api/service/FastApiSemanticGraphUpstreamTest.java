package com.studybridge.api.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.dto.MindMapAiDTO;
import com.studybridge.api.dto.MindMapAiDTO.MindMapAiRequest;
import com.studybridge.api.dto.MindMapAiDTO.MindMapAiResponse;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.web.reactive.function.client.ClientResponse;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

import java.util.List;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * AI07 semantic-graph 업스트림 클라이언트: Bearer 인증 헤더(M9: 서버 내부 처리, 응답에 미포함) + 4xx/5xx FAILED 본문 복원.
 * 실제 네트워크 없이 WebClient ExchangeFunction 을 stub 한다.
 */
class FastApiSemanticGraphUpstreamTest {

    private static final String FAILED_422 = "{\"schemaVersion\":\"mindmap.semantic.v1\",\"status\":\"FAILED\",\"degraded\":false,"
            + "\"degradedReason\":\"NO_VALID_CONCEPTS\",\"nodes\":[],\"edges\":[],\"sourceNodes\":[],\"provenanceEdges\":[],\"rejected\":[],\"validationErrors\":[]}";
    private static final String OK_200 = "{\"schemaVersion\":\"mindmap.semantic.v1\",\"question\":\"q\",\"status\":\"OK\",\"degraded\":false,"
            + "\"extractor\":\"llm\",\"analyzer\":\"kiwi\",\"nodes\":[{\"id\":\"c_1\",\"type\":\"concept\",\"level\":\"CORE\",\"label\":\"JDBC\",\"canonicalLabel\":\"JDBC\","
            + "\"aliases\":[\"JDBC가\"],\"surfaceForms\":[\"JDBC가\"],\"sources\":[\"s_1\"],\"extractedBy\":[\"llm\"],\"mentions\":3,\"visible\":true,\"unknownFuture\":1}],"
            + "\"edges\":[{\"id\":\"e_1\",\"from\":\"q_1\",\"to\":\"c_1\",\"kind\":\"topic\",\"relation\":\"주제\",\"relationKey\":\"TOPIC\"}],"
            + "\"sourceNodes\":[{\"id\":\"s_1\",\"type\":\"agent\",\"level\":\"SOURCE\",\"label\":\"교수\",\"agentKey\":\"agent:1\"}],"
            + "\"provenanceEdges\":[{\"id\":\"p_1\",\"from\":\"s_1\",\"to\":\"c_1\",\"kind\":\"provenance\",\"relation\":\"출처\",\"relationKey\":\"SOURCE\"}],"
            + "\"stats\":{\"conceptCount\":1},\"rejected\":[{\"surfaceForm\":\"있는\",\"reason\":\"STOPWORD\"}],\"validationErrors\":[]}";

    private static WebClient stub(AtomicReference<org.springframework.web.reactive.function.client.ClientRequest> captured, HttpStatus status, String body) {
        return WebClient.builder()
                .baseUrl("http://ai07.test")
                .exchangeFunction(req -> {
                    captured.set(req);
                    return Mono.just(ClientResponse.create(status)
                            .header(HttpHeaders.CONTENT_TYPE, MediaType.APPLICATION_JSON_VALUE)
                            .body(body).build());
                })
                .build();
    }

    private static MindMapAiRequest request() {
        return MindMapAiRequest.builder().question("JDBC가 뭐야?")
                .answers(List.of(MindMapAiDTO.Answer.builder().content("JDBC는 ...").agentId(1).agentName("교수").role("theory").build()))
                .useLlm(true).build();
    }

    @Test
    void m9_bearer_header_sent_when_api_key_configured_and_absent_otherwise() throws Exception {
        AtomicReference<org.springframework.web.reactive.function.client.ClientRequest> cap = new AtomicReference<>();
        FastApiSemanticGraphUpstream withKey = new FastApiSemanticGraphUpstream(stub(cap, HttpStatus.OK, OK_200), new ObjectMapper(), 10, "secret-key-123");
        MindMapAiResponse res = withKey.semanticGraph(request());
        assertEquals("Bearer secret-key-123", cap.get().headers().getFirst(HttpHeaders.AUTHORIZATION));
        assertEquals("/api/ai/mindmap/semantic-graph", cap.get().url().getPath());
        // 응답 DTO 어디에도 키가 없다(브라우저 노출 0)
        assertFalse(new ObjectMapper().writeValueAsString(res).contains("secret-key-123"));
        // typed 계약 필드 손실 없음 + unknown 무시
        assertEquals("mindmap.semantic.v1", res.getSchemaVersion());
        assertEquals("JDBC", res.getNodes().get(0).getCanonicalLabel());
        assertEquals(3, res.getNodes().get(0).getMentions());
        assertEquals("TOPIC", res.getEdges().get(0).getRelationKey());
        assertEquals("agent:1", res.getSourceNodes().get(0).getAgentKey());
        assertEquals("SOURCE", res.getProvenanceEdges().get(0).getRelationKey());
        assertEquals("STOPWORD", res.getRejected().get(0).getReason());
        assertEquals(1, res.getStats().get("conceptCount"));

        AtomicReference<org.springframework.web.reactive.function.client.ClientRequest> cap2 = new AtomicReference<>();
        FastApiSemanticGraphUpstream noKey = new FastApiSemanticGraphUpstream(stub(cap2, HttpStatus.OK, OK_200), new ObjectMapper(), 10, "  ");
        noKey.semanticGraph(request());
        assertNull(cap2.get().headers().getFirst(HttpHeaders.AUTHORIZATION), "키 미설정이면 헤더 없음");
        assertFalse(noKey.hasApiKey());
    }

    @Test
    void m6_422_body_is_restored_as_failed_dto() {
        AtomicReference<org.springframework.web.reactive.function.client.ClientRequest> cap = new AtomicReference<>();
        FastApiSemanticGraphUpstream up = new FastApiSemanticGraphUpstream(stub(cap, HttpStatus.UNPROCESSABLE_ENTITY, FAILED_422), new ObjectMapper(), 10, "");
        SemanticGraphUpstream.UpstreamException ex = assertThrows(SemanticGraphUpstream.UpstreamException.class, () -> up.semanticGraph(request()));
        assertEquals(422, ex.getHttpStatus());
        assertEquals("NO_VALID_CONCEPTS", ex.getReasonCode());
        assertNotNull(ex.getFailedBody());
        assertEquals("FAILED", ex.getFailedBody().getStatus());
        assertTrue(ex.getFailedBody().getNodes().isEmpty(), "FAILED graph 는 항상 비어 있다");
    }

    @Test
    void m7_m8_500_and_504_bodies_and_fastapi_validation_detail() {
        AtomicReference<org.springframework.web.reactive.function.client.ClientRequest> cap = new AtomicReference<>();
        FastApiSemanticGraphUpstream up500 = new FastApiSemanticGraphUpstream(
                stub(cap, HttpStatus.INTERNAL_SERVER_ERROR, "{\"status\":\"FAILED\",\"degradedReason\":\"INTERNAL_ERROR\",\"nodes\":[]}"), new ObjectMapper(), 10, "");
        SemanticGraphUpstream.UpstreamException e500 = assertThrows(SemanticGraphUpstream.UpstreamException.class, () -> up500.semanticGraph(request()));
        assertEquals(500, e500.getHttpStatus());
        assertEquals("INTERNAL_ERROR", e500.getReasonCode());

        FastApiSemanticGraphUpstream up504 = new FastApiSemanticGraphUpstream(
                stub(cap, HttpStatus.GATEWAY_TIMEOUT, "{\"status\":\"FAILED\",\"degradedReason\":\"TIMEOUT\"}"), new ObjectMapper(), 10, "");
        assertEquals("TIMEOUT", assertThrows(SemanticGraphUpstream.UpstreamException.class, () -> up504.semanticGraph(request())).getReasonCode());

        // FastAPI schema violation({"detail":[...]}) → 계약 위반 코드
        FastApiSemanticGraphUpstream up422 = new FastApiSemanticGraphUpstream(
                stub(cap, HttpStatus.UNPROCESSABLE_ENTITY, "{\"detail\":[{\"loc\":[\"body\",\"answers\"],\"msg\":\"field required\"}]}"), new ObjectMapper(), 10, "");
        SemanticGraphUpstream.UpstreamException e422 = assertThrows(SemanticGraphUpstream.UpstreamException.class, () -> up422.semanticGraph(request()));
        assertEquals("UPSTREAM_CONTRACT_REJECTED", e422.getReasonCode());

        // 라우트 없음(운영 ai07 현재 상태) → 404 + 본문 복원 실패 허용
        FastApiSemanticGraphUpstream up404 = new FastApiSemanticGraphUpstream(
                stub(cap, HttpStatus.NOT_FOUND, "{\"detail\":\"Not Found\"}"), new ObjectMapper(), 10, "");
        SemanticGraphUpstream.UpstreamException e404 = assertThrows(SemanticGraphUpstream.UpstreamException.class, () -> up404.semanticGraph(request()));
        assertEquals(404, e404.getHttpStatus());
        assertEquals("UPSTREAM_CONTRACT_REJECTED".equals(e404.getReasonCode()) ? "UPSTREAM_CONTRACT_REJECTED" : e404.getReasonCode(), e404.getReasonCode());
    }
}
