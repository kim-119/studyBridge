package com.studybridge.api.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.service.support.RelayTestSupport;
import com.studybridge.api.service.support.SseStubServer;
import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** 브라우저 X-Request-ID → Spring requestId → AI07 요청 헤더(X-Request-ID) + body.requestId 로 동일 값 전달. */
class CorrelationIdPropagationTest {

    @Test
    void requestIdReachesUpstreamHeaderAndBody_streamAndNonStream() throws Exception {
        try (SseStubServer stub = new SseStubServer()) {
            stub.frames.addAll(RelayTestSupport.happyTurn("web-1234-abcd", "turn_c"));
            RelayTestSupport.run(RelayTestSupport.service(stub.baseUrl()), "web-1234-abcd");
            assertEquals("web-1234-abcd", stub.lastHeaders.get().getFirst("X-Request-ID"));
            Map<?, ?> body = new ObjectMapper().readValue(stub.lastBody.get(), Map.class);
            assertEquals("web-1234-abcd", body.get("requestId"));

            // non-stream 도 같은 헤더
            RelayTestSupport.service(stub.baseUrl()).callMultiChat(2L, "web-1234-abcd", Map.of("message", "hi"), java.time.Duration.ofSeconds(5))
                    .block(java.time.Duration.ofSeconds(10));
            assertEquals("web-1234-abcd", stub.lastHeaders.get().getFirst("X-Request-ID"));
        }
    }

    @Test
    void requestIdResolutionValidatesFormat() {
        assertEquals("web-1234-abcd", ChatService.resolveRequestId("web-1234-abcd", "m1"));
        assertEquals("1758512345-ab12cd", ChatService.resolveRequestId(null, "1758512345-ab12cd"), "헤더 없으면 messageId");
        String minted = ChatService.resolveRequestId("<script>", "x y z");
        assertNotNull(minted);
        assertTrue(minted.startsWith("req_"), "형식 위반은 무시하고 Spring 발급: " + minted);
        assertTrue(ChatService.resolveRequestId("a".repeat(65), null).startsWith("req_"));
    }
}
