package com.studybridge.api.service;

import com.studybridge.api.ai.contract.AgentProfileContract;
import org.junit.jupiter.api.Test;

import java.util.LinkedHashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** stream agent_answer 와 non-stream answers[] 는 같은 identity(agentId/agentIndex/persona/knowledge/status/failureCode/degraded)를 낸다. */
class StreamNonStreamIdentityParityTest {

    private static Map<String, Object> base() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("agentId", 7001);
        m.put("agentIndex", 1);
        m.put("agentName", "김교수");
        m.put("personality", "critical");
        m.put("personalityKey", "critical");
        m.put("personalityLabel", "비판형");
        m.put("knowledgeLevel", "master");
        m.put("knowledgeLevelKey", "master");
        m.put("knowledgeLevelLabel", "석사");
        m.put("status", "SUCCESS");
        m.put("degraded", false);
        return m;
    }

    @Test
    void identityExtractedIdenticallyFromBothShapes() {
        Map<String, Object> stream = base();
        stream.put("type", "agent_answer");
        stream.put("eventId", "evt_1");
        stream.put("answer", "a");
        stream.put("content", "a");
        Map<String, Object> nonStream = base();
        nonStream.put("answer", "a");
        nonStream.put("qualityStatus", "ok");
        nonStream.put("displayDelayMs", 0);

        assertEquals(AgentProfileContract.identityOf(stream), AgentProfileContract.identityOf(nonStream));
        Map<String, Object> id = AgentProfileContract.identityOf(stream);
        assertEquals(7001, id.get("agentId"));
        assertEquals(1, id.get("agentIndex"));
        assertEquals("critical", id.get("personalityKey"));
        assertEquals("master", id.get("knowledgeLevelKey"));
        assertEquals("SUCCESS", id.get("status"));
        assertEquals(false, id.get("degraded"));
    }

    @Test
    void failedAnswerIsFailedInBothShapes() {
        Map<String, Object> failed = base();
        failed.put("status", "FAILED");
        failed.put("code", "AGENT_ANSWER_MISSING");
        failed.put("degraded", true);
        assertTrue(AgentProfileContract.isFailedAnswer(failed));
        assertEquals("AGENT_ANSWER_MISSING", AgentProfileContract.identityOf(failed).get("failureCode"));
        assertEquals(true, AgentProfileContract.identityOf(failed).get("degraded"));
    }

    @Test
    void dedupKeyIsStableAcrossShapes() {
        Map<String, Object> a = base();
        a.put("stage", "DIRECT_ANSWER");
        a.put("displayOrder", 1);
        String k1 = ChatService.dedupKeyOf(a, "turn_x", "req_1", 0);
        String k2 = ChatService.dedupKeyOf(new LinkedHashMap<>(a), "turn_x", "req_1", 5);
        assertEquals(k1, k2, "eventId 가 없으면 turnId:agentId:stage:displayOrder — index 와 무관");
        assertEquals("turn_x:7001:DIRECT_ANSWER:1", k1);
        a.put("eventId", "evt_9");
        assertEquals("evt_9", ChatService.dedupKeyOf(a, "turn_x", "req_1", 0), "eventId 가 있으면 그대로");
    }
}
