package com.studybridge.api.service.adaptive;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.web.reactive.function.client.WebClient;

/**
 * ai07 적응형 엔진 클라이언트(Mock HTTP 서버): Bearer 내부 키·X-Request-ID, 429/503 Retry-After 재시도 범위,
 * 4xx 무결성 오류 비우회, 타임아웃·연결 실패·계약 버전 불일치 매핑.
 */
class AdaptivePlannerClientTest {

    private final ObjectMapper om = new ObjectMapper();
    private HttpServer server;
    private final List<String> auths = new ArrayList<>();
    private final List<String> requestIds = new ArrayList<>();
    private final List<String> bodies = new ArrayList<>();
    private final AtomicInteger calls = new AtomicInteger();
    /** 호출 순서별 응답(status, retryAfter, body). 마지막 항목을 계속 쓴다. */
    record Resp(int status, Integer retryAfter, String body) {}

    private volatile List<Resp> script = List.of();
    private volatile long delayMs = 0;

    private static final String OK = "{\"contractVersion\":\"adaptive-planner.v1\",\"mode\":\"MANUAL_NEXT\",\"status\":\"READY\",\"source\":\"RULE_BASED\"}";

    @BeforeEach
    void start() throws Exception {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/api/ai/planner/adaptive", ex -> {
            int n = calls.getAndIncrement();
            synchronized (this) {
                auths.add(ex.getRequestHeaders().getFirst("Authorization"));
                requestIds.add(ex.getRequestHeaders().getFirst("X-Request-ID"));
                bodies.add(new String(ex.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            }
            if (delayMs > 0) {
                try { Thread.sleep(delayMs); } catch (InterruptedException ignored) { }
            }
            Resp r = script.get(Math.min(n, script.size() - 1));
            byte[] out = r.body().getBytes(StandardCharsets.UTF_8);
            ex.getResponseHeaders().add("Content-Type", "application/json");
            if (r.retryAfter() != null) ex.getResponseHeaders().add("Retry-After", String.valueOf(r.retryAfter()));
            ex.sendResponseHeaders(r.status(), out.length);
            ex.getResponseBody().write(out);
            ex.close();
        });
        server.start();
    }

    @AfterEach
    void stop() {
        server.stop(0);
    }

    private AdaptivePlannerClient client(String key, Duration timeout) {
        WebClient wc = WebClient.builder().baseUrl("http://127.0.0.1:" + server.getAddress().getPort()).build();
        return new AdaptivePlannerClient(wc, om, "/api/ai/planner/adaptive", key, timeout, 3);
    }

    private AdaptivePlannerClient client() {
        return client("k-secret", Duration.ofSeconds(45));
    }

    private static Resp resp(int status, Integer retryAfter, String body) {
        return new Resp(status, retryAfter, body);
    }

    private static String err(String code, boolean retryable) {
        return "{\"error\":{\"code\":\"" + code + "\",\"message\":\"m\",\"retryable\":" + retryable + ",\"requestId\":\"r\"}}";
    }

    @Test
    void sendsBearerKey_requestId_andBodyVerbatim() throws Exception {
        script = List.of(resp(200, null, OK));
        JsonNode r = client().recommend(Map.of("mode", "MANUAL_NEXT", "userId", 55, "availableMinutes", 30), "req-1");
        assertEquals("READY", r.path("status").asText());
        assertEquals("Bearer k-secret", auths.get(0));
        assertEquals("req-1", requestIds.get(0));
        JsonNode sent = om.readTree(bodies.get(0));
        assertEquals("MANUAL_NEXT", sent.path("mode").asText());
        assertEquals(55, sent.path("userId").asInt());
    }

    @Test
    void missingKey_doesNotCall_andFailsClosed() {
        script = List.of(resp(200, null, OK));
        AdaptivePlannerException e = assertThrows(AdaptivePlannerException.class,
                () -> client("", Duration.ofSeconds(45)).recommend(Map.of(), "r"));
        assertEquals("ADAPTIVE_NOT_CONFIGURED", e.getCode());
        assertEquals(0, calls.get());
    }

    @Test
    void retryable429_withShortRetryAfter_retriesOnce_thenSucceeds() {
        script = List.of(resp(429, 1, err("ADAPTIVE_TOO_MANY_REQUESTS", true)), resp(200, null, OK));
        JsonNode r = client().recommend(Map.of(), "r");
        assertEquals("READY", r.path("status").asText());
        assertEquals(2, calls.get());
    }

    @Test
    void retryable503_twice_surfacesOverloadedWithRetryAfter_noThirdCall() {
        script = List.of(resp(503, 1, err("ADAPTIVE_OVERLOADED", true)));
        AdaptivePlannerException e = assertThrows(AdaptivePlannerException.class, () -> client().recommend(Map.of(), "r"));
        assertEquals("ADAPTIVE_OVERLOADED", e.getCode());
        assertEquals(HttpStatus.SERVICE_UNAVAILABLE, e.getStatus());
        assertTrue(e.isRetryable());
        assertEquals(1, e.getRetryAfterSeconds());
        assertEquals(2, calls.get());
    }

    @Test
    void retryAfterBeyondSafeWait_isNotRetried() {
        script = List.of(resp(429, 20, err("ADAPTIVE_TOO_MANY_REQUESTS", true)));
        AdaptivePlannerException e = assertThrows(AdaptivePlannerException.class, () -> client().recommend(Map.of(), "r"));
        assertEquals("ADAPTIVE_BUSY", e.getCode());
        assertEquals(20, e.getRetryAfterSeconds());
        assertEquals(1, calls.get());
    }

    @Test
    void nonRetryable503_disabled_isNotRetried() {
        script = List.of(resp(503, null, err("ADAPTIVE_DISABLED", false)));
        AdaptivePlannerException e = assertThrows(AdaptivePlannerException.class, () -> client().recommend(Map.of(), "r"));
        assertEquals("ADAPTIVE_DISABLED", e.getCode());
        assertFalse(e.isRetryable());
        assertEquals(1, calls.get());
    }

    @Test
    void integrity422_isNotRetried_norBypassed() {
        script = List.of(resp(422, null, "{\"error\":{\"code\":\"ADAPTIVE_CURRENT_STEP_NOT_FOUND\",\"message\":\"m\",\"retryable\":false,\"field\":\"currentStepId\"}}"));
        AdaptivePlannerException e = assertThrows(AdaptivePlannerException.class, () -> client().recommend(Map.of(), "r"));
        assertEquals("ADAPTIVE_REQUEST_REJECTED", e.getCode());
        assertEquals(HttpStatus.BAD_GATEWAY, e.getStatus());
        assertFalse(e.isRetryable());
        assertEquals("ADAPTIVE_CURRENT_STEP_NOT_FOUND", e.getDetails().get("upstreamCode"));
        assertEquals("currentStepId", e.getDetails().get("field"));
        assertEquals(1, calls.get());
    }

    @Test
    void unauthorized401_isConfigError_notRetried() {
        script = List.of(resp(401, null, err("ADAPTIVE_UNAUTHORIZED", false)));
        AdaptivePlannerException e = assertThrows(AdaptivePlannerException.class, () -> client().recommend(Map.of(), "r"));
        assertEquals("ADAPTIVE_UPSTREAM_CONFIG", e.getCode());
        assertEquals(1, calls.get());
    }

    @Test
    void routeMissing404_isUnavailable() {
        script = List.of(resp(404, null, "{\"detail\":\"Not Found\"}"));
        AdaptivePlannerException e = assertThrows(AdaptivePlannerException.class, () -> client().recommend(Map.of(), "r"));
        assertEquals("ADAPTIVE_UNAVAILABLE", e.getCode());
        assertTrue(e.isRetryable());
    }

    @Test
    void wrongContractVersion_isInvalidResponse() {
        script = List.of(resp(200, null, "{\"contractVersion\":\"recommendation.v1\",\"status\":\"READY\"}"));
        AdaptivePlannerException e = assertThrows(AdaptivePlannerException.class, () -> client().recommend(Map.of(), "r"));
        assertEquals("ADAPTIVE_INVALID_RESPONSE", e.getCode());
    }

    @Test
    void slowUpstream_timesOut_asRetryable504() {
        script = List.of(resp(200, null, OK));
        delayMs = 1500;
        AdaptivePlannerException e = assertThrows(AdaptivePlannerException.class,
                () -> client("k", Duration.ofMillis(400)).recommend(Map.of(), "r"));
        assertEquals("ADAPTIVE_TIMEOUT", e.getCode());
        assertEquals(HttpStatus.GATEWAY_TIMEOUT, e.getStatus());
        assertTrue(e.isRetryable());
    }

    @Test
    void connectionRefused_isUnavailable() {
        int port = server.getAddress().getPort();
        server.stop(0);
        WebClient wc = WebClient.builder().baseUrl("http://127.0.0.1:" + port).build();
        AdaptivePlannerClient c = new AdaptivePlannerClient(wc, om, "/api/ai/planner/adaptive", "k", Duration.ofSeconds(5), 3);
        AdaptivePlannerException e = assertThrows(AdaptivePlannerException.class, () -> c.recommend(Map.of(), "r"));
        assertEquals("ADAPTIVE_UNAVAILABLE", e.getCode());
        assertTrue(e.isRetryable());
    }

    @Test
    void productionConstructor_neverAllowsTimeoutBelow40Seconds() {
        WebClient wc = WebClient.builder().baseUrl("http://127.0.0.1:1").build();
        AdaptivePlannerClient c = new AdaptivePlannerClient(wc, om, "/p", "k", 10, 3);
        assertEquals(Duration.ofSeconds(40), c.timeout());
    }
}
