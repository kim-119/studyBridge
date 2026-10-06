package com.studybridge.api.service;

import com.studybridge.api.entity.Agent;
import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

/** 지식수준: persona 태그 > 요청값 > 기본(학사). canonical key + enum + 라벨이 함께 실린다. */
class KnowledgeLevelPropagationTest {

    private static Map<String, Object> payload(String personaTag, String requestLevel) {
        Agent a = Agent.builder().id(1L).name("A").role("r").tone("logical")
                .persona(personaTag != null ? "[지식수준: " + personaTag + "]" : "").build();
        return ChatService.buildAgentPayload(a, 1, requestLevel, null, "extreme", null, null);
    }

    @Test
    void fiveLevelsFromPersonaTag() {
        String[][] rows = {{"입문 수준", "beginner", "INTRO"}, {"학사 수준", "bachelor", "BACHELOR"}, {"석사 수준", "master", "MASTER"},
                {"박사 수준", "phd", "DOCTOR"}, {"전문가 수준", "expert", "EXPERT"}};
        for (String[] r : rows) {
            Map<String, Object> p = payload(r[0], null);
            assertEquals(r[1], p.get("knowledgeLevelKey"), r[0]);
            assertEquals(r[2], p.get("knowledgeLevel"), r[0]);
            assertEquals(r[2], p.get("knowledge_level"));
            assertEquals(r[0], p.get("knowledgeLevelLabel"));
        }
    }

    @Test
    void requestLevelUsedWhenPersonaHasNoTag() {
        Map<String, Object> p = payload(null, "phd");
        assertEquals("phd", p.get("knowledgeLevelKey"));
        assertEquals("DOCTOR", p.get("knowledgeLevel"));
    }

    @Test
    void missingDefaultsToBachelorAndUnknownStaysRaw() {
        assertEquals("bachelor", payload(null, null).get("knowledgeLevelKey"));
        Map<String, Object> p = payload("초월자 수준", null);
        assertNull(p.get("knowledgeLevelKey"));
        assertEquals("초월자 수준", p.get("knowledgeLevel"));
        assertEquals(Boolean.FALSE, p.get("knowledgeLevelResolved"));
    }
}
