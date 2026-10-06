package com.studybridge.api.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.service.support.RelayTestSupport;
import com.studybridge.api.service.support.SseStubServer;
import org.junit.jupiter.api.Test;
import org.springframework.http.codec.ServerSentEvent;
import reactor.core.publisher.Flux;

import java.time.Duration;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** heartbeat(AI07 event) 와 ':hb'(Spring comment) 는 control event: 이름 보존, agentId 없음, coverage/영속화 대상 아님. */
class SseHeartbeatTest {

    private static final ObjectMapper OM = new ObjectMapper();

    @Test
    void upstreamHeartbeatIsRelayedAsHeartbeatAndNotCountedAsAnswer() throws Exception {
        try (SseStubServer stub = new SseStubServer()) {
            stub.frames.addAll(RelayTestSupport.happyTurn("req_hb", "turn_hb"));
            List<ServerSentEvent<String>> evs = RelayTestSupport.run(RelayTestSupport.service(stub.baseUrl()), "req_hb");
            ServerSentEvent<String> hb = RelayTestSupport.find(evs, "heartbeat");
            Map<?, ?> d = OM.readValue(hb.data(), Map.class);
            assertEquals("heartbeat", d.get("eventType"));
            assertNull(d.get("agentId"));
            assertEquals(Boolean.FALSE, d.get("visible"));
            Map<?, ?> done = OM.readValue(RelayTestSupport.find(evs, "done").data(), Map.class);
            Map<?, ?> cov = (Map<?, ?>) done.get("coverage");
            assertEquals(List.of("1", "2", "3"), cov.get("relayed"), "heartbeat 는 relayed 작성자에 포함되지 않는다");
        }
    }

    @Test
    void springCommentHeartbeatStartsOnlyAfterFirstBusinessEvent_andIsAComment() {
        ServerSentEvent<String> a = ServerSentEvent.<String>builder("{}").event("turn_start").build();
        ServerSentEvent<String> b = ServerSentEvent.<String>builder("{}").event("done").build();
        Flux<ServerSentEvent<String>> main = Flux.concat(Flux.just(a), Flux.just(b).delayElements(Duration.ofMillis(2500)));
        List<ServerSentEvent<String>> out = ChatService.withHeartbeat(main, 1).collectList().block(Duration.ofSeconds(10));
        List<String> names = RelayTestSupport.names(out);
        assertEquals("turn_start", names.get(0));
        assertEquals("done", names.get(names.size() - 1));
        long hbs = names.stream().filter(":hb"::equals).count();
        assertTrue(hbs >= 1 && hbs <= 3, "1초 간격 주석 하트비트 1~3개: " + names);
        for (ServerSentEvent<String> e : out) {
            if ("hb".equals(e.comment())) {
                assertNull(e.event(), "하트비트는 event 이름이 없는 주석이라 프론트 핸들러를 타지 않는다");
                assertNull(e.data());
            }
        }
    }

    @Test
    void preStreamErrorPropagatesWithoutHeartbeat() {
        Flux<ServerSentEvent<String>> main = Flux.error(new IllegalStateException("pre-stream"));
        Throwable got = ChatService.withHeartbeat(main, 1)
                .collectList()
                .map(l -> (Throwable) null)
                .onErrorResume(e -> reactor.core.publisher.Mono.just(e))
                .block(Duration.ofSeconds(5));
        assertTrue(got instanceof IllegalStateException, String.valueOf(got));
    }
}
