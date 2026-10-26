package com.studybridge.api.service;

import com.studybridge.api.entity.Agent;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** "이 교수에게 질문": 3명 중 2번을 고르면 요청 targetAgentId = 그 agentId, agentSlot 은 원래 순서(2)를 유지, 미지 id 는 명시 오류. */
class TargetAgentRoutingTest {

    private final List<Agent> room = List.of(
            Agent.builder().id(665L).name("개념 정리 교수").role("r").tone("friendly").persona("").build(),
            Agent.builder().id(666L).name("쉬운 풀이 튜터").role("r").tone("creative").persona("").build(),
            Agent.builder().id(667L).name("논점 검증 코치").role("r").tone("logical").persona("").build());

    @Test
    void secondProfessorResolvesToItsOwnIdAndSlot() {
        Agent target = ChatService.resolveExplicitTargetAgent(room, "666");
        assertEquals(666L, target.getId());
        // agents[] 는 방 전체가 그대로 실리고 슬롯은 원래 순서를 유지한다(AI07 이 targetAgentId 로 필터 후 agentIndex=2 로 응답).
        Map<String, Object> slot2 = ChatService.buildAgentPayload(room.get(1), 2, null, null, "extreme", null, null);
        assertEquals(2, slot2.get("agentSlot"));
        assertEquals(666L, slot2.get("agentId"));
        assertEquals("creative", slot2.get("personalityKey"));
    }

    @Test
    void unknownTargetIsExplicitError_noFirstAgentFallback() {
        IllegalArgumentException ex = assertThrows(IllegalArgumentException.class,
                () -> ChatService.resolveExplicitTargetAgent(room, "999"));
        assertTrue(ex.getMessage().contains("TARGET_AGENT_NOT_FOUND"));
        assertTrue(ex.getMessage().contains("665"));
    }

    @Test
    void blankTargetMeansAllAgents() {
        assertNull(ChatService.resolveExplicitTargetAgent(room, null));
        assertNull(ChatService.resolveExplicitTargetAgent(room, "  "));
    }
}
