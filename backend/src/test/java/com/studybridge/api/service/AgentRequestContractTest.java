package com.studybridge.api.service;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.entity.Agent;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Spring → AI07 agents[] 실제 직렬화 JSON 검증(Java 객체가 아니라 ObjectMapper 출력 기준).
 * 각 에이전트에 agentId/agentSlot/name/personalityKey/personalityLabel/personalityStyle/knowledgeLevelKey/knowledgeLevelLabel/
 * customInstruction/temperature/goal/persona 가 실린다.
 */
class AgentRequestContractTest {

    private static final ObjectMapper OM = new ObjectMapper();

    private static Map<String, Object> serialized(Map<String, Object> payload) throws Exception {
        return OM.readValue(OM.writeValueAsString(payload), new TypeReference<Map<String, Object>>() {});
    }

    @Test
    void everyRequiredFieldIsOnTheWire() throws Exception {
        Agent a = Agent.builder().id(665L).name("개념 정리 교수").role("핵심 개념 정리").tone("비판형").goal("핵심 개념 정리")
                .persona("[지식수준: 석사 수준] [성격: 비판형] 운영체제 사례를 반드시 하나 포함").build();
        Map<String, Object> json = serialized(ChatService.buildAgentPayload(a, 2, null, null, "extreme", null, null));

        assertEquals(665, json.get("agentId"));
        assertEquals(2, json.get("agentSlot"));
        assertEquals("개념 정리 교수", json.get("name"));
        assertEquals("critical", json.get("personalityKey"));
        assertEquals("비판형", json.get("personalityLabel"));
        assertEquals("honest", json.get("personalityStyle"), "프론트 7키 호환 값");
        assertEquals(Boolean.TRUE, json.get("personalityResolved"));
        assertEquals("master", json.get("knowledgeLevelKey"));
        assertEquals("석사 수준", json.get("knowledgeLevelLabel"));
        assertEquals("MASTER", json.get("knowledgeLevel"));
        assertEquals("운영체제 사례를 반드시 하나 포함", json.get("customInstruction"));
        assertEquals(0.45, ((Number) json.get("temperature")).doubleValue(), 1e-9);
        assertEquals("핵심 개념 정리", json.get("goal"));
        assertTrue(String.valueOf(json.get("persona")).contains("[성격: 비판형]"));
        for (String k : List.of("agentId", "agentSlot", "name", "personalityKey", "personalityLabel", "personalityStyle",
                "knowledgeLevelKey", "knowledgeLevelLabel", "customInstruction", "temperature", "goal", "persona")) {
            assertTrue(json.containsKey(k), "missing " + k);
        }
    }

    @Test
    void unknownPersonalityIsSentRawWithoutCanonicalKey() throws Exception {
        Agent a = Agent.builder().id(1L).name("A").role("r").tone("우주적 시인 말투").persona("").build();
        Map<String, Object> json = serialized(ChatService.buildAgentPayload(a, 1, null, null, "extreme", null, null));
        assertNull(json.get("personalityKey"));
        assertNull(json.get("personalityStyle"), "unknown 을 default 로 위장하지 않는다");
        assertEquals("우주적 시인 말투", json.get("personality"));
        assertEquals(Boolean.FALSE, json.get("personalityResolved"));
    }

    @Test
    void legacyAgentWithoutPersonalityDefaultsToLogicalNotFriendly() throws Exception {
        Agent a = Agent.builder().id(1L).name("A").role("r").persona("설명").build();
        Map<String, Object> json = serialized(ChatService.buildAgentPayload(a, 1, null, null, "extreme", null, null));
        assertEquals("logical", json.get("personalityKey"));
        assertEquals("professional", json.get("personalityStyle"));
    }

    @Test
    void temperatureOverrideWins() throws Exception {
        Agent a = Agent.builder().id(1L).name("A").role("r").tone("friendly").persona("").build();
        Map<String, Object> json = serialized(ChatService.buildAgentPayload(a, 1, null, null, "extreme", null, 0.9));
        assertEquals(0.9, ((Number) json.get("temperature")).doubleValue(), 1e-9);
        assertFalse(json.get("temperature") instanceof String);
    }
}
