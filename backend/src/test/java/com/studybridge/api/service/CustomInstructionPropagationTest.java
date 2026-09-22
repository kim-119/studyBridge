package com.studybridge.api.service;

import com.studybridge.api.entity.Agent;
import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;

/** customInstruction: DB persona 본문(태그 제거) → agents[].customInstruction/custom_instruction 로 그대로 전달. */
class CustomInstructionPropagationTest {

    @Test
    void personaBodyBecomesCustomInstruction() {
        Agent a = Agent.builder().id(9L).name("교수").role("r").tone("logical")
                .persona("[프리셋: os] [지식수준: 학사 수준] [성격: 논리형] 운영체제 사례를 반드시 하나 포함").build();
        Map<String, Object> p = ChatService.buildAgentPayload(a, 1, null, null, "extreme", null, null);
        assertEquals("운영체제 사례를 반드시 하나 포함", p.get("customInstruction"));
        assertEquals("운영체제 사례를 반드시 하나 포함", p.get("custom_instruction"));
        assertEquals("os", p.get("agentPreset"));
    }

    @Test
    void requestLevelInstructionIsFallbackWhenPersonaBodyEmpty() {
        Agent a = Agent.builder().id(9L).name("교수").role("r").tone("logical").persona("[성격: 논리형]").goal("목표").build();
        Map<String, Object> p = ChatService.buildAgentPayload(a, 1, null, null, "extreme", "항상 예시 2개", null);
        assertEquals("항상 예시 2개", p.get("customInstruction"));
        Map<String, Object> p2 = ChatService.buildAgentPayload(a, 1, null, null, "extreme", null, null);
        assertEquals("목표", p2.get("customInstruction"), "요청 지시도 없으면 goal");
    }
}
