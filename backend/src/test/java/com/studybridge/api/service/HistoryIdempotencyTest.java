package com.studybridge.api.service;

import com.studybridge.api.entity.Agent;
import com.studybridge.api.service.support.ChatServiceTestFactory;
import org.junit.jupiter.api.Test;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;

/** reload/reconnect/late event/재시도로 같은 all_complete(또는 partial) 가 두 번 와도 AI 메시지는 한 번만 저장된다. */
class HistoryIdempotencyTest {

    private static Map<String, Object> allComplete(String turnId, boolean withEventIds) {
        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("learningMode", "basic");
        resp.put("turnId", turnId);
        Map<String, Object> a1 = new LinkedHashMap<>(Map.of("agentId", 1, "agentIndex", 1, "agentName", "A", "answer", "답1", "status", "SUCCESS",
                "stage", "DIRECT_ANSWER", "displayOrder", 1, "personalityKey", "critical", "knowledgeLevelKey", "master"));
        Map<String, Object> a2 = new LinkedHashMap<>(Map.of("agentId", 2, "agentIndex", 2, "agentName", "B", "answer", "답2", "status", "SUCCESS",
                "stage", "DIRECT_ANSWER", "displayOrder", 2));
        if (withEventIds) {
            a1.put("eventId", "evt_1");
            a2.put("eventId", "evt_2");
        }
        resp.put("answers", List.of(a1, a2));
        return resp;
    }

    @Test
    void sameAllCompleteTwice_storesOnce_withEventIds() {
        ChatServiceTestFactory f = new ChatServiceTestFactory(5L, List.of(
                Agent.builder().id(1L).name("A").build(), Agent.builder().id(2L).name("B").build()));
        f.service.persistAnswerRows(5L, allComplete("turn_1", true), "req_1", "all_complete");
        f.service.persistAnswerRows(5L, allComplete("turn_1", true), "req_1", "all_complete");
        assertEquals(2, f.saved.size());
        assertEquals("evt_1", f.saved.get(0).getEventId());
        assertEquals("critical", f.saved.get(0).getPersonalityKey());
        assertEquals("master", f.saved.get(0).getKnowledgeLevelKey());
        assertEquals(1, f.saved.get(0).getAgentIndex());
        assertEquals("req_1", f.saved.get(0).getRequestId());
    }

    @Test
    void compositeKeyDedupsWhenEventIdMissing_butNewTurnStoresAgain() {
        ChatServiceTestFactory f = new ChatServiceTestFactory(5L, List.of(
                Agent.builder().id(1L).name("A").build(), Agent.builder().id(2L).name("B").build()));
        f.service.persistAnswerRows(5L, allComplete("turn_1", false), "req_1", "all_complete");
        f.service.persistAnswerRows(5L, allComplete("turn_1", false), "req_1", "partial");
        assertEquals(2, f.saved.size(), "eventId 없어도 turnId:agentId:stage:displayOrder 로 멱등");
        assertEquals("turn_1:1:DIRECT_ANSWER:1", f.saved.get(0).getEventId());
        f.service.persistAnswerRows(5L, allComplete("turn_2", false), "req_2", "all_complete");
        assertEquals(4, f.saved.size(), "다른 턴은 새 답변");
    }

    @Test
    void partialThenAllCompleteDoesNotDuplicate() {
        ChatServiceTestFactory f = new ChatServiceTestFactory(5L, List.of(
                Agent.builder().id(1L).name("A").build(), Agent.builder().id(2L).name("B").build()));
        Map<String, Object> partial = allComplete("turn_p", true);
        partial.put("answers", List.of(((List<?>) partial.get("answers")).get(0)));
        f.service.persistAnswerRows(5L, partial, "req_p", "partial");
        f.service.persistAnswerRows(5L, allComplete("turn_p", true), "req_p", "all_complete");
        assertEquals(2, f.saved.size(), "partial 1건 + all_complete 의 나머지 1건");
    }
}
