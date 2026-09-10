package com.studybridge.api.service;

import org.junit.jupiter.api.Test;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 모드 전용 all_complete(토론/소크라테스/상황극)는 processSteps 가 없다. 그대로 저장하면 새로고침/보정 후
 * 에이전트별 평문 행만 남아 구조(최종 결론 독립 영역·선택지)가 사라지므로 구조화 payload 를 processSteps 로 영속화한다.
 */
class ChatServiceStructuredPersistTest {

    @Test
    void debate_allComplete_keepsStagesResultAndStrength() {
        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("mode", "debate");
        resp.put("learningMode", "debate");
        resp.put("debateStrength", "normal");
        resp.put("topic", "논제");
        resp.put("debateStages", List.of(
                Map.of("stageType", "DEBATE_OPENING", "agentId", 632, "agentName", "A", "content", "a"),
                Map.of("stageType", "DEBATE_OPENING", "agentId", 633, "agentName", "B", "content", "b"),
                Map.of("stageType", "DEBATE_OPENING", "agentId", 634, "agentName", "C", "content", "c"),
                Map.of("stageType", "DEBATE_FINAL_CONCLUSION", "agentId", "debate-consensus", "agentName", "최종 결론 (합의)", "content", "final")));
        resp.put("debateResult", Map.of("decision", "d", "conditions", List.of("c1")));
        resp.put("debateParticipants", List.of(Map.of("agentId", 632), Map.of("agentId", 633), Map.of("agentId", 634)));
        resp.put("answers", List.of(Map.of("agentId", 632, "answer", "a")));

        Map<String, Object> ps = ChatService.structuredProcessSteps(resp);
        assertNotNull(ps);
        assertEquals("debate", ps.get("mode"));
        assertEquals(4, ((List<?>) ps.get("debateStages")).size(), "에이전트 4 발언(3명 + 최종 결론) 전부 보존");
        assertEquals("normal", ((Map<?, ?>) ps.get("debateConfig")).get("debateStrength"));
        assertEquals("d", ((Map<?, ?>) ps.get("debateResult")).get("decision"));
        assertEquals(3, ((List<?>) ps.get("debateParticipants")).size());
        assertEquals("논제", ps.get("topic"));
        assertNull(ps.get("socraticSteps"));
    }

    @Test
    void socratic_allComplete_keepsStepsSessionAndConfig() {
        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("learningMode", "socratic");
        resp.put("sessionId", "socratic-abc");
        resp.put("turnIndex", 2);
        resp.put("questionIntensity", "normal");
        resp.put("hintPolicy", "step");
        resp.put("socraticSteps", List.of(
                Map.of("stageType", "DIAGNOSIS", "agentId", 629),
                Map.of("stageType", "COUNTEREXAMPLE", "agentId", 630),
                Map.of("stageType", "MISCONCEPTION_CHECK", "agentId", 631)));

        Map<String, Object> ps = ChatService.structuredProcessSteps(resp);
        assertNotNull(ps);
        assertEquals("socratic", ps.get("mode"));
        assertEquals(3, ((List<?>) ps.get("socraticSteps")).size());
        assertEquals("socratic-abc", ps.get("sessionId"));
        assertEquals(2, ps.get("turnIndex"));
        Map<?, ?> cfg = (Map<?, ?>) ps.get("socraticConfig");
        assertEquals("normal", cfg.get("questionIntensity"));
        assertEquals("step", cfg.get("hintPolicy"));
    }

    @Test
    void simulation_allComplete_keepsStagesChoicesAndConfig() {
        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("mode", "simulation");
        resp.put("sessionId", "simulation-xyz");
        resp.put("scenarioType", "project");
        resp.put("difficulty", "hard");
        resp.put("choiceCount", 2);
        resp.put("choices", List.of(Map.of("choiceId", "A"), Map.of("choiceId", "B")));
        resp.put("simulationStages", List.of(
                Map.of("stageType", "SCENE_SETUP", "agentId", 635),
                Map.of("stageType", "CHALLENGE", "agentId", 636),
                Map.of("stageType", "FEEDBACK", "agentId", 637)));

        Map<String, Object> ps = ChatService.structuredProcessSteps(resp);
        assertNotNull(ps);
        assertEquals("simulation", ps.get("mode"));
        assertEquals(3, ((List<?>) ps.get("simulationStages")).size());
        assertEquals(2, ((List<?>) ps.get("choices")).size());
        Map<?, ?> cfg = (Map<?, ?>) ps.get("simulationConfig");
        assertEquals("project", cfg.get("scenarioType"));
        assertEquals("hard", cfg.get("difficulty"));
        assertEquals(2, cfg.get("choiceCount"));
        assertEquals("simulation-xyz", ps.get("sessionId"));
    }

    @Test
    void basicOrEmpty_returnsNull_soLegacyProcessStepsRuleIsUntouched() {
        assertNull(ChatService.structuredProcessSteps(null));
        assertNull(ChatService.structuredProcessSteps(Map.of("mode", "basic", "answers", List.of())));
        assertNull(ChatService.structuredProcessSteps(Map.of("mode", "debate", "debateStages", List.of())));
        assertTrue(ChatService.structuredProcessSteps(Map.of("mode", "socratic", "socraticSteps", List.of(Map.of("stageType", "DIAGNOSIS")))) != null);
    }
}
