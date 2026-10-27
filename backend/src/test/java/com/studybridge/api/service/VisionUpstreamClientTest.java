package com.studybridge.api.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.exception.ScreenAiException;
import com.studybridge.api.service.VisionUpstreamClient.VisionCall;
import com.studybridge.api.service.VisionUpstreamClient.VisionResult;
import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.web.reactive.function.client.WebClient;

/**
 * ai07 Vision 클라이언트: 실제 HTTP(로컬 서버)로 요청 형식·인증·공정성 헤더와 오류/Retry-After 매핑을 검증한다.
 */
class VisionUpstreamClientTest {

    private final ObjectMapper om = new ObjectMapper();
    private HttpServer server;
    private final AtomicReference<String> body = new AtomicReference<>();
    private final AtomicReference<String> auth = new AtomicReference<>();
    private final AtomicReference<String> userHeader = new AtomicReference<>();
    private final AtomicReference<String> groupHeader = new AtomicReference<>();
    private volatile int status = 200;
    private volatile String response = "{}";
    private volatile String retryAfter;

    @BeforeEach
    void start() throws Exception {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/api/ai/vision/analyze", ex -> {
            body.set(new String(ex.getRequestBody().readAllBytes(), StandardCharsets.UTF_8));
            auth.set(ex.getRequestHeaders().getFirst("Authorization"));
            userHeader.set(ex.getRequestHeaders().getFirst("X-AI-User-Id"));
            groupHeader.set(ex.getRequestHeaders().getFirst("X-AI-Group-Id"));
            byte[] out = response.getBytes(StandardCharsets.UTF_8);
            ex.getResponseHeaders().add("Content-Type", "application/json");
            if (retryAfter != null) ex.getResponseHeaders().add("Retry-After", retryAfter);
            ex.sendResponseHeaders(status, out.length);
            ex.getResponseBody().write(out);
            ex.close();
        });
        server.start();
    }

    @AfterEach
    void stop() {
        server.stop(0);
    }

    private VisionUpstreamClient client(String key) {
        WebClient wc = WebClient.builder().baseUrl("http://127.0.0.1:" + server.getAddress().getPort()).build();
        return new VisionUpstreamClient(wc, om, "/api/ai/vision/analyze", key, 260);
    }

    private static VisionCall call() {
        return new VisionCall("6f1c0000-0000-4000-8000-000000000001", 25L, "str_SB_SCREEN", 2L, 3L, "이 PPT 내용을 설명해 줘.", "/9j/AAAA", "image/jpeg");
    }

    @Test
    void sendsContractBody_bearerKey_andFairnessHeaders() throws Exception {
        response = "{\"requestId\":\"6f1c0000-0000-4000-8000-000000000001\",\"answer\":\"화면에 보이는 내용: 슬라이드\",\"model\":\"qwen3-vl:4b-instruct\","
                + "\"latencyMs\":1536,\"queueWaitMs\":0,\"inferenceMs\":1468}";
        VisionResult r = client("k-secret").analyze(call()).block();

        assertEquals("화면에 보이는 내용: 슬라이드", r.answer());
        assertEquals("qwen3-vl:4b-instruct", r.model());
        assertEquals(1468L, r.inferenceMs());
        assertEquals("Bearer k-secret", auth.get());
        assertEquals("3", userHeader.get());
        assertEquals("25", groupHeader.get());
        JsonNode sent = om.readTree(body.get());
        assertEquals("6f1c0000-0000-4000-8000-000000000001", sent.get("requestId").asText());
        assertEquals(25L, sent.get("groupId").asLong());
        assertEquals("str_SB_SCREEN", sent.get("streamId").asText());
        assertEquals(2L, sent.get("sharerUserId").asLong());
        assertEquals(3L, sent.get("askerUserId").asLong());
        assertEquals("이 PPT 내용을 설명해 줘.", sent.get("question").asText());
        assertEquals("/9j/AAAA", sent.get("image").asText());
        assertEquals("image/jpeg", sent.get("mime").asText());
        assertFalse(r.toString().contains("슬라이드"));
    }

    @Test
    void missingApiKey_failsClosed_withoutCallingAi07() {
        ScreenAiException ex = assertThrows(ScreenAiException.class, () -> client("").analyze(call()).block());
        assertEquals("SCREEN_AI_NOT_CONFIGURED", ex.getCode());
        assertNull(body.get());
    }

    @Test
    void overload_isRetryable_withRetryAfter() {
        status = 429;
        retryAfter = "7";
        response = "{\"error\":{\"code\":\"VISION_QUEUE_FULL\",\"message\":\"대기열 초과\",\"retryable\":true,\"requestId\":\"x\"}}";
        ScreenAiException ex = assertThrows(ScreenAiException.class, () -> client("k").analyze(call()).block());
        assertEquals(429, ex.getStatus().value());
        assertEquals("SCREEN_AI_BUSY", ex.getCode());
        assertTrue(ex.isRetryable());
        assertEquals(7, ex.getRetryAfterSeconds());
        assertEquals("VISION_QUEUE_FULL", ex.getDetails().get("upstreamCode"));

        status = 503;
        retryAfter = null;
        response = "{\"error\":{\"code\":\"VISION_QUEUE_TIMEOUT\",\"retryable\":true}}";
        ScreenAiException q = assertThrows(ScreenAiException.class, () -> client("k").analyze(call()).block());
        assertEquals("SCREEN_AI_OVERLOADED", q.getCode());
        assertEquals(10, q.getRetryAfterSeconds());
    }

    @Test
    void inferenceTimeout_disabled_auth_imageAndRouteErrors_areMapped() {
        status = 504;
        response = "{\"error\":{\"code\":\"VISION_INFERENCE_TIMEOUT\",\"retryable\":true}}";
        assertEquals("SCREEN_AI_TIMEOUT", assertThrows(ScreenAiException.class, () -> client("k").analyze(call()).block()).getCode());

        status = 503;
        response = "{\"error\":{\"code\":\"VISION_DISABLED\",\"retryable\":false}}";
        ScreenAiException disabled = assertThrows(ScreenAiException.class, () -> client("k").analyze(call()).block());
        assertEquals("SCREEN_AI_DISABLED", disabled.getCode());
        assertFalse(disabled.isRetryable());

        status = 401;
        response = "{\"error\":{\"code\":\"VISION_UNAUTHORIZED\",\"retryable\":false}}";
        ScreenAiException authErr = assertThrows(ScreenAiException.class, () -> client("wrong").analyze(call()).block());
        assertEquals("SCREEN_AI_UPSTREAM_CONFIG", authErr.getCode());
        assertEquals(502, authErr.getStatus().value());

        status = 422;
        response = "{\"error\":{\"code\":\"VISION_IMAGE_CORRUPT\",\"message\":\"이미지가 손상되었습니다.\",\"retryable\":false}}";
        ScreenAiException img = assertThrows(ScreenAiException.class, () -> client("k").analyze(call()).block());
        assertEquals("SCREEN_AI_IMAGE_INVALID", img.getCode());
        assertEquals("이미지가 손상되었습니다.", img.getMessage());

        status = 404;
        response = "{\"detail\":\"Not Found\"}";
        assertEquals("SCREEN_AI_UNAVAILABLE", assertThrows(ScreenAiException.class, () -> client("k").analyze(call()).block()).getCode());

        status = 200;
        response = "{\"answer\":\"   \"}";
        assertEquals("SCREEN_AI_UPSTREAM_ERROR", assertThrows(ScreenAiException.class, () -> client("k").analyze(call()).block()).getCode());
    }

    @Test
    void unreachableAi07_isReportedAsUnavailable() {
        server.stop(0);
        WebClient wc = WebClient.builder().baseUrl("http://127.0.0.1:" + server.getAddress().getPort()).build();
        VisionUpstreamClient c = new VisionUpstreamClient(wc, om, "/api/ai/vision/analyze", "k", 260);
        ScreenAiException ex = assertThrows(ScreenAiException.class, () -> c.analyze(call()).block());
        assertEquals("SCREEN_AI_UNAVAILABLE", ex.getCode());
        assertTrue(ex.isRetryable());
    }

    @Test
    void retryAfterHeaderParsing() {
        assertEquals(5, VisionUpstreamClient.parseRetryAfter("5"));
        assertEquals(300, VisionUpstreamClient.parseRetryAfter("9999"));
        assertNull(VisionUpstreamClient.parseRetryAfter("Wed, 21 Oct 2026 07:28:00 GMT"));
        assertNull(VisionUpstreamClient.parseRetryAfter(null));
    }
}
