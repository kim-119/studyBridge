package com.studybridge.api.ai.contract;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** 지식수준 canonical 5키(beginner/bachelor/master/phd/expert) ↔ enum(INTRO..EXPERT) ↔ 한글 라벨. */
class CanonicalKnowledgeMappingTest {

    @Test
    void fiveCanonicalKeys() {
        String[][] rows = {
                {"beginner", "INTRO", "입문"}, {"bachelor", "BACHELOR", "학사"}, {"master", "MASTER", "석사"},
                {"phd", "DOCTOR", "박사"}, {"expert", "EXPERT", "전문가"}};
        for (String[] r : rows) {
            AgentProfileContract.KnowledgeResolution k = AgentProfileContract.resolveKnowledge(r[0]);
            assertEquals(r[0], k.key());
            assertEquals(r[1], k.enumValue());
            assertEquals(r[2], k.label());
            assertTrue(k.resolved());
            // enum 입력도 같은 키
            assertEquals(r[0], AgentProfileContract.resolveKnowledge(r[1]).key(), r[1]);
            // 한글 "X 수준" 도 같은 키
            assertEquals(r[0], AgentProfileContract.resolveKnowledge(r[2] + " 수준").key(), r[2]);
        }
    }

    @Test
    void learningMateVocabularyMaps() {
        assertEquals("bachelor", AgentProfileContract.resolveKnowledge("undergraduate").key());
        assertEquals("master", AgentProfileContract.resolveKnowledge("advanced").key(), "advanced 는 bachelor 로 조용히 떨어지지 않는다");
        assertEquals("phd", AgentProfileContract.resolveKnowledge("Ph.D").key());
        assertEquals("beginner", AgentProfileContract.resolveKnowledge("입문자").key(), "학습메이트 '입문자 맞춤' 어휘");
        assertEquals("beginner", AgentProfileContract.resolveKnowledge("입문").key());
    }

    @Test
    void unknownIsExposedNotDefaulted() {
        AgentProfileContract.KnowledgeResolution k = AgentProfileContract.resolveKnowledge("초월자");
        assertFalse(k.resolved());
        assertNull(k.key());
        assertNull(k.enumValue());
        assertEquals("초월자", k.original());
        // OrDefault 도 unknown 은 그대로(missing 만 학사 기본)
        assertFalse(AgentProfileContract.resolveKnowledgeOrDefault("초월자").resolved());
    }

    @Test
    void missingDefaultsToBachelorExplicitly() {
        AgentProfileContract.KnowledgeResolution k = AgentProfileContract.resolveKnowledgeOrDefault(null, "");
        assertTrue(k.resolved());
        assertEquals("bachelor", k.key());
        assertEquals("BACHELOR", k.enumValue());
        assertEquals("explicit_default", k.source());
        assertEquals("학사 수준", k.enumLabel());
    }
}
