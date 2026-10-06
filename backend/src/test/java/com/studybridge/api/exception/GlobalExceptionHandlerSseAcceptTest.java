package com.studybridge.api.exception;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import java.util.NoSuchElementException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;
import reactor.core.publisher.Flux;

/**
 * SSE 컨트롤러({@code produces=text/event-stream}) 에서 비즈니스 예외가 나도 403/404/400 상태코드와 JSON 본문이 보존되어야 한다.
 * 회귀 배경: 요청 Accept 가 text/event-stream 이면 @ExceptionHandler 의 Map 본문을 쓸 컨버터가 없어
 * "Failure in @ExceptionHandler" → 빈 본문 500 으로 새어 나갔다(방 소유자 아님/없는 방/잘못된 targetAgentId 전부 500).
 */
class GlobalExceptionHandlerSseAcceptTest {

        @RestController
        static class SseThrowingController {
                @PostMapping(value = "/sse/{kind}", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
                Flux<ServerSentEvent<String>> stream(@PathVariable String kind) {
                        switch (kind) {
                                case "forbidden": throw new SecurityException("해당 채팅방에 접근할 권한이 없습니다.");
                                case "notfound": throw new NoSuchElementException("해당 채팅방을 찾을 수 없습니다.");
                                case "badtarget": throw new IllegalArgumentException("TARGET_AGENT_NOT_FOUND: targetAgentId=999");
                                case "conflict": throw new IllegalStateException("현재 플랜에서는 학습방을 최대 3개까지 생성할 수 있습니다.");
                                default: return Flux.empty();
                        }
                }
        }

        private MockMvc mvc;

        @BeforeEach
        void setUp() {
                mvc = MockMvcBuilders.standaloneSetup(new SseThrowingController())
                                .setControllerAdvice(new GlobalExceptionHandler())
                                .build();
        }

        private void assertMapped(String kind, int expectedStatus, String messagePart) throws Exception {
                mvc.perform(post("/sse/" + kind)
                                .accept(MediaType.TEXT_EVENT_STREAM)
                                .contentType(MediaType.APPLICATION_JSON)
                                .content("{\"message\":\"x\"}"))
                                .andExpect(status().is(expectedStatus))
                                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON))
                                .andExpect(jsonPath("$.status").value(expectedStatus))
                                .andExpect(jsonPath("$.message").value(org.hamcrest.Matchers.containsString(messagePart)));
        }

        @Test
        void forbiddenOnSseEndpointIs403Json() throws Exception {
                assertMapped("forbidden", 403, "권한이 없습니다");
        }

        @Test
        void notFoundOnSseEndpointIs404Json() throws Exception {
                assertMapped("notfound", 404, "찾을 수 없습니다");
        }

        @Test
        void badTargetOnSseEndpointIs400Json() throws Exception {
                assertMapped("badtarget", 400, "TARGET_AGENT_NOT_FOUND");
        }

        @Test
        void conflictOnSseEndpointIs409Json() throws Exception {
                assertMapped("conflict", 409, "최대 3개");
        }
}
