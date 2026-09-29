package com.studybridge.api.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.service.support.RelayTestSupport;
import com.studybridge.api.service.support.SseStubServer;
import org.junit.jupiter.api.Test;
import org.springframework.http.codec.ServerSentEvent;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;

/** 많은 이벤트가 빠르게 와도 순서가 보존된다(멀티라인 data/한글/코드블록 포함). */
class SseOrderingTest {

    private static final ObjectMapper OM = new ObjectMapper();

    @Test
    void hundredEventsKeepOrderAndContent() throws Exception {
        try (SseStubServer stub = new SseStubServer()) {
            stub.frames.add(SseStubServer.frame("turn_start", RelayTestSupport.env("r", "t", "evt_ts", "turn_start", "{}")));
            List<String> expected = new ArrayList<>();
            for (int i = 0; i < 100; i++) {
                String content = "한글 답변 " + i + "\\n```java\\nint x = " + i + ";\\n```";
                expected.add("한글 답변 " + i + "\n```java\nint x = " + i + ";\n```");
                stub.frames.add(SseStubServer.frame("agent_answer", RelayTestSupport.env("r", "t", "evt_" + i, "agent_answer",
                        "{\"agentId\":" + (i % 3 + 1) + ",\"seq\":" + i + ",\"content\":\"" + content + "\",\"answer\":\"" + content + "\"}")));
            }
            stub.frames.add(SseStubServer.frame("all_complete", RelayTestSupport.env("r", "t", "evt_ac", "all_complete", "{\"status\":\"COMPLETED\",\"answers\":[]}")));
            stub.frames.add(SseStubServer.frame("done", RelayTestSupport.env("r", "t", "evt_d", "done", "{\"status\":\"done\"}")));
            List<ServerSentEvent<String>> evs = RelayTestSupport.run(RelayTestSupport.service(stub.baseUrl()), "r");
            List<String> got = new ArrayList<>();
            int seq = 0;
            for (ServerSentEvent<String> e : evs) {
                if ("agent_answer".equals(e.event())) {
                    Map<?, ?> m = OM.readValue(e.data(), Map.class);
                    assertEquals(seq++, m.get("seq"), "순서 보존");
                    got.add(String.valueOf(m.get("content")));
                }
            }
            assertEquals(100, seq);
            assertEquals(expected, got, "UTF-8/개행/코드블록 손실 없음");
        }
    }
}
