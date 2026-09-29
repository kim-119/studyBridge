package com.studybridge.api.ai.contract;

import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** 성격 canonical 6키 매핑 — AI07 profile_contract 와 동일 어휘. critical != sardonic, unknown silent fallback 금지. */
class CanonicalPersonaMappingTest {

    @Test
    void sixCanonicalKeysMapToThemselves() {
        for (String k : AgentProfileContract.PERSONALITY_KEYS) {
            AgentProfileContract.PersonaResolution r = AgentProfileContract.resolvePersona(k);
            assertEquals(k, r.key(), k);
            assertTrue(r.resolved());
            assertEquals(AgentProfileContract.PERSONALITY_LABELS.get(k), r.label());
        }
    }

    @Test
    void frontSevenKeysMapToCanonical() {
        Map<String, String> expect = Map.of(
                "default", "friendly", "professional", "logical", "friendly", "friendly", "honest", "critical",
                "unique", "creative", "efficient", "concise", "cynical", "sardonic");
        for (Map.Entry<String, String> e : expect.entrySet()) {
            AgentProfileContract.PersonaResolution r = AgentProfileContract.resolvePersona(e.getKey());
            assertEquals(e.getValue(), r.key(), e.getKey());
            assertTrue(r.resolved());
            assertEquals(e.getKey(), r.legacyStyle(), "legacy style 은 프론트 7키 그대로 보존");
        }
    }

    @Test
    void criticalAndSardonicDoNotCollapse() {
        AgentProfileContract.PersonaResolution c = AgentProfileContract.resolvePersona("critical");
        AgentProfileContract.PersonaResolution s = AgentProfileContract.resolvePersona("sardonic");
        assertEquals("critical", c.key());
        assertEquals("sardonic", s.key());
        assertNotEquals(c.key(), s.key());
        assertNotEquals(c.label(), s.label());
        // 한글 라벨도 서로 다른 키로
        assertEquals("critical", AgentProfileContract.resolvePersona("비판형").key());
        assertEquals("sardonic", AgentProfileContract.resolvePersona("냉소적").key());
        assertEquals("critical", AgentProfileContract.resolvePersona("솔직함").key());
    }

    @Test
    void koreanLabelsResolve() {
        assertEquals("logical", AgentProfileContract.resolvePersona("논리적").key());
        assertEquals("logical", AgentProfileContract.resolvePersona("전문적").key());
        assertEquals("friendly", AgentProfileContract.resolvePersona("친근함").key());
        assertEquals("creative", AgentProfileContract.resolvePersona("독특함").key());
        assertEquals("concise", AgentProfileContract.resolvePersona("효율적").key());
    }

    @Test
    void explicitDefaultIsResolvedButLowerPriorityThanConcretePersonality() {
        AgentProfileContract.PersonaResolution d = AgentProfileContract.resolvePersona("default");
        assertEquals("friendly", d.key());
        assertTrue(d.resolved());
        assertEquals("explicit_default", d.source());
        assertEquals(0.5, d.baseTemperature(), 1e-9);
        // personalityStyle=default + personality=논리적 → 구체 성격 우선
        AgentProfileContract.PersonaResolution mixed = AgentProfileContract.resolvePersona("default", "논리적");
        assertEquals("logical", mixed.key());
        // 차분함(레거시 방 데이터) 도 explicit default
        assertEquals("friendly", AgentProfileContract.resolvePersona("차분함").key());
    }

    @Test
    void unknownIsNotSilentlyFriendly() {
        AgentProfileContract.PersonaResolution r = AgentProfileContract.resolvePersona("우주적 시인 말투");
        assertFalse(r.resolved());
        assertNull(r.key(), "unknown 은 canonical key 를 만들지 않는다");
        assertNull(r.legacyStyle(), "unknown 을 'default' 로 위장하지 않는다");
        assertEquals("우주적 시인 말투", r.original());
        assertEquals("unknown", r.source());
    }

    @Test
    void missingIsDistinctFromUnknown() {
        AgentProfileContract.PersonaResolution r = AgentProfileContract.resolvePersona(null, "", "  ");
        assertFalse(r.resolved());
        assertEquals("missing", r.source());
        assertNull(r.key());
    }

    @Test
    void temperatureFollowsCanonicalKeyAndClampsOverride() {
        assertEquals(0.45, AgentProfileContract.temperatureFor(AgentProfileContract.resolvePersona("critical"), null), 1e-9);
        assertEquals(0.55, AgentProfileContract.temperatureFor(AgentProfileContract.resolvePersona("sardonic"), null), 1e-9);
        assertEquals(1.2, AgentProfileContract.temperatureFor(AgentProfileContract.resolvePersona("critical"), 5.0), 1e-9);
        assertEquals(0.0, AgentProfileContract.temperatureFor(AgentProfileContract.resolvePersona("critical"), -1.0), 1e-9);
        assertEquals(0.5, AgentProfileContract.temperatureFor(AgentProfileContract.resolvePersona("???"), null), 1e-9);
    }
}
