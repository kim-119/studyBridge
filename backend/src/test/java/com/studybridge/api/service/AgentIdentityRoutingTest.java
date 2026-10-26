package com.studybridge.api.service;

import com.studybridge.api.entity.Agent;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

/** identity 는 agentId 기준. 동명이인이 있어도 agentId 가 결정하며, 이름은 id 가 없을 때의 보조 수단이다. */
class AgentIdentityRoutingTest {

    private final List<Agent> room = List.of(
            Agent.builder().id(31L).name("김교수").build(),
            Agent.builder().id(37L).name("김교수").build(),   // 동명이인
            Agent.builder().id(42L).name("논점 검증 코치").build());

    @Test
    void duplicateNames_agentIdDecides() {
        assertEquals(37L, ChatService.resolveResponseAgent(room, 37, "김교수").getId());
        assertEquals(37L, ChatService.resolveResponseAgent(room, "37", "김교수").getId());
        assertEquals(31L, ChatService.resolveResponseAgent(room, 31L, "김교수").getId());
    }

    @Test
    void wrongNameWithValidId_idStillWins() {
        assertEquals(42L, ChatService.resolveResponseAgent(room, 42, "김교수").getId(), "이름이 아니라 id 가 identity");
    }

    @Test
    void nameOnlyFallbackPicksFirstMatch_butUnknownIdNeverFallsBackToFirstAgent() {
        assertEquals(42L, ChatService.resolveResponseAgent(room, null, "논점 검증 코치").getId());
        assertNull(ChatService.resolveResponseAgent(room, 999, "없는 교수"), "첫 번째 교수 폴백 금지");
        assertNull(ChatService.resolveResponseAgent(room, "debate-consensus", "최종 결론 (합의)"), "가상 작성자는 agent 없음");
    }
}
