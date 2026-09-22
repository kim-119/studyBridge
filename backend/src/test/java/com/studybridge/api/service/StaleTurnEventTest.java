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

/** eventId 기반 중복 제거 + 같은 릴레이 안에서 requestId 는 항상 클라이언트 값으로 고정(늦은 이벤트를 다른 턴에 섞지 않는다). */
class StaleTurnEventTest {

    private static final ObjectMapper OM = new ObjectMapper();

    @Test
    void duplicateEventIdIsDroppedOnce() throws Exception {
        try (SseStubServer stub = new SseStubServer()) {
            List<String> f = RelayTestSupport.happyTurn("req_dup", "turn_dup");
            stub.frames.addAll(f);
            stub.frames.add(4, f.get(3)); // agent_answer evt_a1 두 번(재전송/reconnect 시뮬)
            List<ServerSentEvent<String>> evs = RelayTestSupport.run(RelayTestSupport.service(stub.baseUrl()), "req_dup");
            long a1 = evs.stream().filter(e -> "agent_answer".equals(e.event()) && e.data().contains("evt_a1")).count();
            assertEquals(1, a1, "같은 eventId 는 한 번만 중계");
            Map<?, ?> done = OM.readValue(RelayTestSupport.find(evs, "done").data(), Map.class);
            assertEquals(1, ((Map<?, ?>) done.get("relay")).get("dedupDropped"));
        }
    }

    @Test
    void everySpringGeneratedEventCarriesTheClientRequestId() throws Exception {
        try (SseStubServer stub = new SseStubServer()) {
            List<String> f = RelayTestSupport.happyTurn("req_A", "turn_A");
            stub.frames.addAll(f.subList(0, 4)); // all_complete 없이 종료 → Spring error + done
            stub.nonStreamStatus = 500; // non-stream 폴백도 실패 → Spring 이 error + done 으로 종결
            List<ServerSentEvent<String>> evs = RelayTestSupport.run(RelayTestSupport.service(stub.baseUrl()), "req_A");
            for (String n : List.of("error", "done")) {
                Map<?, ?> m = OM.readValue(RelayTestSupport.find(evs, n).data(), Map.class);
                assertEquals("req_A", m.get("requestId"), n);
                assertEquals("turn_A", m.get("turnId"), n + " 는 관측된 turnId 를 싣는다");
            }
            assertTrue(evs.stream().allMatch(e -> e.data() == null || e.data().contains("\"requestId\":\"req_A\"")));
        }
    }
}
