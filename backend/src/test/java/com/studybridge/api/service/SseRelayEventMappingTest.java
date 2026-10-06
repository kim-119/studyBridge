package com.studybridge.api.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.service.support.RelayTestSupport;
import com.studybridge.api.service.support.SseStubServer;
import org.junit.jupiter.api.Test;
import org.springframework.http.codec.ServerSentEvent;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** 이벤트 이름/metadata 보존: turn_start/agent_start/agent_answer/heartbeat/follow_up/all_complete 그대로, unknown 이벤트도 이름 보존, done 은 metadata 병합. */
class SseRelayEventMappingTest {

    private static final ObjectMapper OM = new ObjectMapper();

    @Test
    void allCoreEventNamesAndPayloadsArePreserved() throws Exception {
        try (SseStubServer stub = new SseStubServer()) {
            stub.frames.addAll(RelayTestSupport.happyTurn("req_map", "turn_map"));
            // 확장/미지 이벤트도 이름 그대로 중계되고 agent_answer 로 간주되지 않는다.
            stub.frames.add(stub.frames.size() - 2, SseStubServer.frame("phase_progress", RelayTestSupport.env("req_map", "turn_map", "evt_pp", "phase_progress", "{\"phase\":\"REACTION\"}")));
            stub.frames.add(stub.frames.size() - 2, SseStubServer.frame("some_future_event", RelayTestSupport.env("req_map", "turn_map", "evt_fx", "some_future_event", "{\"x\":1}")));
            List<ServerSentEvent<String>> evs = RelayTestSupport.run(RelayTestSupport.service(stub.baseUrl()), "req_map");
            List<String> names = RelayTestSupport.names(evs);

            assertEquals(List.of("turn_start", "agent_start", "heartbeat", "agent_answer", "agent_start", "agent_answer", "agent_start", "agent_answer",
                    "follow_up_suggestions", "phase_progress", "some_future_event", "all_complete", "done"), names);
            // payload 는 변형 없이 그대로(원본 eventId/turnId/personalityKey 보존)
            Map<?, ?> a1 = OM.readValue(RelayTestSupport.find(evs, "agent_answer").data(), Map.class);
            assertEquals("evt_a1", a1.get("eventId"));
            assertEquals("turn_map", a1.get("turnId"));
            assertEquals("critical", a1.get("personalityKey"));
            assertEquals("studymate-sse-2", a1.get("contractVersion"));
            Map<?, ?> ac = OM.readValue(RelayTestSupport.find(evs, "all_complete").data(), Map.class);
            assertNotNull(ac.get("agentCoverage"));
            assertEquals("sm-prompt-test", ac.get("promptVersion"));
        }
    }

    @Test
    void springDoneMergesUpstreamDoneMetadata() throws Exception {
        try (SseStubServer stub = new SseStubServer()) {
            stub.frames.addAll(RelayTestSupport.happyTurn("req_done", "turn_done"));
            List<ServerSentEvent<String>> evs = RelayTestSupport.run(RelayTestSupport.service(stub.baseUrl()), "req_done");
            Map<?, ?> done = OM.readValue(RelayTestSupport.find(evs, "done").data(), Map.class);
            assertEquals("done", done.get("status"));
            assertEquals("turn_done", done.get("turnId"), "업스트림 turnId 보존");
            assertEquals("req_done", done.get("requestId"));
            assertEquals("studymate-sse-2", done.get("contractVersion"));
            assertEquals("basic", done.get("mode"), "mode 는 AI 모드(transport 아님)");
            assertEquals("stream", done.get("transport"));
            assertEquals("primary", done.get("upstream"));
            assertEquals(Boolean.TRUE, done.get("isFinal"));
            assertEquals("COMPLETED", done.get("relayState"));
            Map<?, ?> up = (Map<?, ?>) done.get("upstreamDone");
            assertNotNull(up);
            assertEquals(123, up.get("elapsedMs"));
            assertTrue(((Map<?, ?>) done.get("latency")).containsKey("firstAgentAnswerMs"));
            Map<?, ?> cov = (Map<?, ?>) done.get("coverage");
            assertEquals(Boolean.FALSE, cov.get("mismatch"));
        }
    }
}
