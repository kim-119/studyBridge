package com.studybridge.api.service;

import com.studybridge.api.exception.AiUpstreamException;
import com.studybridge.api.exception.GlobalExceptionHandler;
import com.studybridge.api.service.support.RelayTestSupport;
import com.studybridge.api.service.support.SseStubServer;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;
import reactor.core.publisher.Flux;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/** AI07 가 스트림을 열기 전 4xx/5xx JSON 을 돌려주면 Spring 은 200 SSE 로 위장하지 않고 상태코드 + application/json 으로 응답한다. */
class SsePreStreamErrorTest {

    private static AiUpstreamException runExpectingUpstreamException(SseStubServer stub, String rid) {
        try {
            RelayTestSupport.run(RelayTestSupport.service(stub.baseUrl()), rid);
        } catch (RuntimeException e) {
            Throwable c = e;
            while (c != null && !(c instanceof AiUpstreamException)) {
                c = c.getCause();
            }
            return (AiUpstreamException) c;
        }
        return null;
    }

    @Test
    void upstream422DetailIsPreservedAs422() throws Exception {
        try (SseStubServer stub = new SseStubServer()) {
            stub.status = 422;
            stub.errorBody = "{\"detail\":{\"code\":\"TARGET_AGENT_NOT_FOUND\",\"targetAgentId\":\"999\",\"message\":\"지정한 교수(targetAgentId)가 이 방의 에이전트 목록에 없습니다.\"}}";
            AiUpstreamException ex = runExpectingUpstreamException(stub, "req_422");
            assertNotNull(ex);
            assertEquals(422, ex.getStatus().value());
            assertEquals("TARGET_AGENT_NOT_FOUND", ex.getUpstreamCode());
            assertEquals("지정한 교수(targetAgentId)가 이 방의 에이전트 목록에 없습니다.", ex.getMessage());
            assertEquals(1, stub.hits.get(), "계약 오류는 재시도/failover 하지 않는다");
        }
    }

    @Test
    void upstream401IsMappedTo502NotBrowser401() throws Exception {
        try (SseStubServer stub = new SseStubServer()) {
            stub.status = 401;
            stub.errorBody = "{\"detail\":\"invalid api key http://internal\"}";
            AiUpstreamException ex = runExpectingUpstreamException(stub, "req_401");
            assertNotNull(ex);
            assertEquals(502, ex.getStatus().value());
            assertEquals("AI_UPSTREAM_AUTH", ex.getCode());
            assertEquals(401, ex.getUpstreamStatus());
        }
    }

    @Test
    void upstream500ExhaustsToTyped503() throws Exception {
        try (SseStubServer stub = new SseStubServer()) {
            stub.status = 500;
            stub.nonStreamStatus = 500;
            AiUpstreamException ex = runExpectingUpstreamException(stub, "req_500");
            assertNotNull(ex);
            assertEquals(503, ex.getStatus().value());
            assertEquals("AI_UPSTREAM_UNAVAILABLE", ex.getCode());
        }
    }

    @RestController
    static class Ctl {
        @PostMapping(value = "/sse/{kind}", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
        Flux<ServerSentEvent<String>> stream(@PathVariable String kind) {
            return switch (kind) {
                case "422" -> Flux.error(AiUpstreamException.contract(422, "UNSUPPORTED_MODE", "지원하지 않는 학습 모드입니다.", "req_x"));
                case "503" -> Flux.error(AiUpstreamException.unavailable("req_y", null));
                default -> Flux.empty();
            };
        }
    }

    @Test
    void handlerWritesJsonWithStatusEvenOnSseEndpoint() throws Exception {
        MockMvc mvc = MockMvcBuilders.standaloneSetup(new Ctl()).setControllerAdvice(new GlobalExceptionHandler()).build();
        var r = mvc.perform(post("/sse/422").accept(MediaType.TEXT_EVENT_STREAM).contentType(MediaType.APPLICATION_JSON).content("{}"))
                .andReturn();
        // Flux 오류는 async dispatch 로 처리된다
        mvc.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders.asyncDispatch(r))
                .andExpect(status().is(422))
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON))
                .andExpect(header().string("X-Request-ID", "req_x"))
                .andExpect(jsonPath("$.code").value("AI_REQUEST_REJECTED"))
                .andExpect(jsonPath("$.upstreamCode").value("UNSUPPORTED_MODE"))
                .andExpect(jsonPath("$.retryable").value(false));
        var r2 = mvc.perform(post("/sse/503").accept(MediaType.TEXT_EVENT_STREAM).contentType(MediaType.APPLICATION_JSON).content("{}"))
                .andReturn();
        mvc.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders.asyncDispatch(r2))
                .andExpect(status().is(503))
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON))
                .andExpect(header().string("Retry-After", "5"))
                .andExpect(jsonPath("$.code").value("AI_UPSTREAM_UNAVAILABLE"))
                .andExpect(jsonPath("$.retryable").value(true));
    }
}
