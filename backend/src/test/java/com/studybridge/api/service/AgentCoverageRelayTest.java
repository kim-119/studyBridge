package com.studybridge.api.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.service.support.RelayTestSupport;
import com.studybridge.api.service.support.SseStubServer;
import org.junit.jupiter.api.Test;
import org.springframework.http.codec.ServerSentEvent;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;

/** AI07 agentCoverage.emitted 와 Spring 이 실제 중계한 agent_answer/agent_error 작성자를 대조한다(불일치 = EC2 transport 버그로 표면화). */
class AgentCoverageRelayTest {

    private static final ObjectMapper OM = new ObjectMapper();

    @Test
    void matchingCoverageIsReportedInDone() throws Exception {
        try (SseStubServer stub = new SseStubServer()) {
            stub.frames.addAll(RelayTestSupport.happyTurn("req_cov", "turn_cov"));
            List<ServerSentEvent<String>> evs = RelayTestSupport.run(RelayTestSupport.service(stub.baseUrl()), "req_cov");
            Map<?, ?> cov = (Map<?, ?>) OM.readValue(RelayTestSupport.find(evs, "done").data(), Map.class).get("coverage");
            assertEquals(List.of("1", "2", "3"), cov.get("emitted"));
            assertEquals(List.of("1", "2", "3"), cov.get("relayed"));
            assertEquals(List.of(), cov.get("missing"));
            assertEquals(Boolean.FALSE, cov.get("mismatch"));
        }
    }

    @Test
    void agentErrorCountsAsCoveredAndMissingIsSurfaced() throws Exception {
        try (SseStubServer stub = new SseStubServer()) {
            List<String> f = RelayTestSupport.happyTurn("req_gap", "turn_gap");
            // 교수3 답변(agent_answer evt_a3) 을 agent_error 로 대체하고, 교수2 는 아예 빠뜨린다(emitted 는 3명 유지).
            stub.frames.add(f.get(0));
            stub.frames.add(f.get(1));
            stub.frames.add(f.get(3));
            stub.frames.add(SseStubServer.frame("agent_error", RelayTestSupport.env("req_gap", "turn_gap", "evt_e3", "agent_error",
                    "{\"agentId\":3,\"agentIndex\":3,\"status\":\"FAILED\",\"code\":\"LLM_TIMEOUT\",\"degraded\":true,\"message\":\"이 교수의 답변을 받지 못했어요.\"}")));
            stub.frames.add(f.get(f.size() - 2));
            stub.frames.add(f.get(f.size() - 1));
            List<ServerSentEvent<String>> evs = RelayTestSupport.run(RelayTestSupport.service(stub.baseUrl()), "req_gap");
            Map<?, ?> cov = (Map<?, ?>) OM.readValue(RelayTestSupport.find(evs, "done").data(), Map.class).get("coverage");
            assertEquals(List.of("1", "3"), cov.get("relayed"));
            assertEquals(List.of("2"), cov.get("missing"));
            assertEquals(Boolean.TRUE, cov.get("mismatch"));
            // agent_error 는 그대로 중계되고 SUCCESS 로 바뀌지 않는다
            ServerSentEvent<String> err = RelayTestSupport.find(evs, "agent_error");
            Map<?, ?> em = OM.readValue(err.data(), Map.class);
            assertEquals("FAILED", em.get("status"));
            assertEquals("LLM_TIMEOUT", em.get("code"));
        }
    }
}
