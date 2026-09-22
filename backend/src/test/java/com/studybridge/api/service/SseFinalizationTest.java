package com.studybridge.api.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.service.support.RelayTestSupport;
import com.studybridge.api.service.support.SseStubServer;
import org.junit.jupiter.api.Test;
import org.springframework.http.codec.ServerSentEvent;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** turn_start 1회, all_complete ≤1, done 정확히 1회(항상 마지막), all_complete 이후 business event 차단, 업스트림 done 삼킴+병합. */
class SseFinalizationTest {

    private static final ObjectMapper OM = new ObjectMapper();

    @Test
    void exactlyOnceTerminalEvents() throws Exception {
        try (SseStubServer stub = new SseStubServer()) {
            List<String> f = RelayTestSupport.happyTurn("req_fin", "turn_fin");
            stub.frames.addAll(f);
            // 계약 위반 업스트림: turn_start 중복, all_complete 이후 agent_answer, done 2회
            stub.frames.add(1, f.get(0));
            stub.frames.add(stub.frames.size() - 1, SseStubServer.frame("agent_answer", RelayTestSupport.env("req_fin", "turn_fin", "evt_late", "agent_answer", "{\"agentId\":9,\"answer\":\"late\"}")));
            stub.frames.add(f.get(f.size() - 1));
            List<ServerSentEvent<String>> evs = RelayTestSupport.run(RelayTestSupport.service(stub.baseUrl()), "req_fin");
            List<String> names = RelayTestSupport.names(evs);
            assertEquals(1, names.stream().filter("turn_start"::equals).count());
            assertEquals(1, names.stream().filter("all_complete"::equals).count());
            assertEquals(1, names.stream().filter("done"::equals).count());
            assertEquals("done", names.get(names.size() - 1));
            assertTrue(names.indexOf("all_complete") < names.indexOf("done"));
            assertTrue(evs.stream().noneMatch(e -> e.data() != null && e.data().contains("evt_late")), "all_complete 이후 business event 차단");
            Map<?, ?> done = OM.readValue(RelayTestSupport.find(evs, "done").data(), Map.class);
            assertEquals(1, ((Map<?, ?>) done.get("relay")).get("afterCompleteDropped"));
        }
    }

    @Test
    void missingAllCompleteEndsWithDoneError_notException() throws Exception {
        try (SseStubServer stub = new SseStubServer()) {
            List<String> f = RelayTestSupport.happyTurn("req_inc", "turn_inc");
            stub.frames.addAll(f.subList(0, 4)); // turn_start, agent_start, heartbeat, agent_answer 후 종료(all_complete 없음)
            stub.nonStreamStatus = 500; // non-stream 폴백도 실패 → Spring 이 error + done 으로 종결
            List<ServerSentEvent<String>> evs = RelayTestSupport.run(RelayTestSupport.service(stub.baseUrl()), "req_inc");
            List<String> names = RelayTestSupport.names(evs);
            assertEquals("done", names.get(names.size() - 1));
            assertTrue(names.contains("error"), names.toString());
            Map<?, ?> done = OM.readValue(RelayTestSupport.find(evs, "done").data(), Map.class);
            assertEquals("error", done.get("status"));
            assertEquals(Boolean.FALSE, done.get("allComplete"));
            assertEquals("FAILED", done.get("relayState"));
            Map<?, ?> err = OM.readValue(RelayTestSupport.find(evs, "error").data(), Map.class);
            assertEquals("stream_error", err.get("eventType"));
            assertEquals(Boolean.TRUE, err.get("degraded"));
        }
    }
}
