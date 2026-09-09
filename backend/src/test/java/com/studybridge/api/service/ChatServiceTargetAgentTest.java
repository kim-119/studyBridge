package com.studybridge.api.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.studybridge.api.entity.Agent;
import java.util.List;
import org.junit.jupiter.api.Test;

/**
 * "이 교수에게 질문"(STRICT TARGETING) Agent Identity 리졸버 회귀 테스트.
 *  - 요청 targetAgentId 는 방 agent PK 로만 해석(문자/숫자 무관), 모르는 id 는 400(IllegalArgumentException),
 *    null/blank 는 전체 협업 모드(null).
 *  - 응답 작성자는 agentId → 이름 → null. 배열 index/첫 번째 교수 silent fallback 금지.
 */
class ChatServiceTargetAgentTest {

        private static List<Agent> room() {
                return List.of(
                                Agent.builder().id(31L).name("개념 정리 교수").build(),
                                Agent.builder().id(37L).name("쉬운 풀이 튜터").build(),
                                Agent.builder().id(42L).name("논점 검증 코치").build());
        }

        @Test
        void explicitTarget_resolvesByStableIdRegardlessOfPosition() {
                Agent a = ChatService.resolveExplicitTargetAgent(room(), "37");
                assertEquals(37L, a.getId());
                assertEquals("쉬운 풀이 튜터", a.getName());
                assertEquals(42L, ChatService.resolveExplicitTargetAgent(room(), " 42 ").getId());
        }

        @Test
        void explicitTarget_nullOrBlankMeansGroupMode() {
                assertNull(ChatService.resolveExplicitTargetAgent(room(), null));
                assertNull(ChatService.resolveExplicitTargetAgent(room(), "   "));
        }

        @Test
        void explicitTarget_unknownIdRejectsInsteadOfFirstAgentFallback() {
                IllegalArgumentException ex = assertThrows(IllegalArgumentException.class,
                                () -> ChatService.resolveExplicitTargetAgent(room(), "999"));
                assertTrue(ex.getMessage().contains("TARGET_AGENT_NOT_FOUND"));
                assertTrue(ex.getMessage().contains("999"));
        }

        @Test
        void explicitTarget_indexLikeValueIsNotAnIdentity() {
                // UI 두 번째 교수 index(1)를 보내도 PK 1 이 방에 없으면 거절한다(index ≠ identity).
                assertThrows(IllegalArgumentException.class,
                                () -> ChatService.resolveExplicitTargetAgent(room(), "1"));
        }

        @Test
        void responseAgent_prefersIdOverNameAndAcceptsNumericOrString() {
                assertEquals(37L, ChatService.resolveResponseAgent(room(), 37, "개념 정리 교수").getId());
                assertEquals(37L, ChatService.resolveResponseAgent(room(), "37", null).getId());
        }

        @Test
        void responseAgent_fallsBackToNameThenNull_neverFirstAgent() {
                assertEquals(42L, ChatService.resolveResponseAgent(room(), null, "논점 검증 코치").getId());
                assertEquals(42L, ChatService.resolveResponseAgent(room(), "agent-x", "논점 검증 코치").getId());
                assertNull(ChatService.resolveResponseAgent(room(), "agent-x", "없는 교수"));
                assertNull(ChatService.resolveResponseAgent(room(), null, "AI"));
                assertNull(ChatService.resolveResponseAgent(List.of(), "37", "쉬운 풀이 튜터"));
        }
}
