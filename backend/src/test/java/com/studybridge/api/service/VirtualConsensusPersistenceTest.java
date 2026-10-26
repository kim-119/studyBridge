package com.studybridge.api.service;

import com.studybridge.api.entity.Agent;
import com.studybridge.api.entity.ChatMessage;
import com.studybridge.api.service.support.ChatServiceTestFactory;
import org.junit.jupiter.api.Test;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;

/** debate-consensus 같은 가상 작성자는 FK lookup 으로 실패하지 않고 agent=null(VIRTUAL) 로 저장된다. 메시지 유실 없음. */
class VirtualConsensusPersistenceTest {

    @Test
    void consensusAnswerIsPersistedWithoutAgentAndNotLost() {
        ChatServiceTestFactory f = new ChatServiceTestFactory(7L, List.of(
                Agent.builder().id(1L).name("A").build(), Agent.builder().id(2L).name("B").build()));
        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("mode", "debate");
        resp.put("learningMode", "debate");
        resp.put("turnId", "turn_v");
        resp.put("answers", List.of(
                Map.of("agentId", 1, "agentIndex", 1, "agentName", "A", "answer", "찬성", "status", "SUCCESS", "eventId", "evt_1"),
                Map.of("agentId", "debate-consensus", "agentName", "최종 결론 (합의)", "answer", "결론", "status", "SUCCESS", "eventId", "evt_c")));
        f.service.persistAnswerRows(7L, resp, "req_v", "all_complete");

        assertEquals(2, f.saved.size(), "가상 작성자 메시지도 유실되지 않는다");
        ChatMessage consensus = f.saved.get(1);
        assertNull(consensus.getAgent(), "실체 없는 작성자는 agent 없이(VIRTUAL) 저장");
        assertEquals("결론", consensus.getContent());
        assertEquals("evt_c", consensus.getEventId());
        assertEquals("debate", consensus.getMode());
        assertEquals("turn_v", consensus.getTurnId());
        assertNotNull(f.saved.get(0).getAgent());
        assertEquals(1L, f.saved.get(0).getAgent().getId());
    }

    @Test
    void failedAnswersAreNeverStoredAsSuccess() {
        ChatServiceTestFactory f = new ChatServiceTestFactory(7L, List.of(Agent.builder().id(1L).name("A").build()));
        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("turnId", "turn_f");
        resp.put("answers", List.of(
                Map.of("agentId", 1, "agentName", "A", "answer", "이 교수의 답변을 받지 못했어요.", "status", "FAILED", "code", "LLM_TIMEOUT", "eventId", "evt_f1"),
                Map.of("agentId", 1, "agentName", "A", "answer", "", "status", "SUCCESS", "eventId", "evt_f2"),
                Map.of("agentId", 1, "agentName", "A", "answer", "정상", "status", "SUCCESS", "eventId", "evt_f3")));
        f.service.persistAnswerRows(7L, resp, "req_f", "all_complete");
        assertEquals(1, f.saved.size());
        assertEquals("정상", f.saved.get(0).getContent());
        assertEquals("SUCCESS", f.saved.get(0).getStatus());
    }
}
