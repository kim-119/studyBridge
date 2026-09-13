package com.studybridge.api.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

/**
 * ai07 로 나가는 previousAnswers 정리 규칙.
 *  - chatStream 은 USER 메시지를 먼저 저장하므로 Redis 캐시 끝에 "이번 질문" 이 붙는다 → 이전 대화로 실려 가지 않게 제외.
 *  - Redis 캐시(최대 100건)를 전량 보내던 것을 최근 N건으로 제한(순서 보존).
 */
class ChatServicePreviousAnswersTest {

        private static Map<String, Object> row(String role, String answer) {
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("agentName", "USER".equals(role) ? "USER" : "교수");
                m.put("answer", answer);
                m.put("role", role);
                return m;
        }

        @Test
        void dropsTrailingEchoOfCurrentQuestionOnly() {
                List<Map<String, Object>> in = List.of(
                                row("USER", "첫 질문"), row("ASSISTANT", "첫 답"), row("USER", "  이번 질문  "));
                List<Map<String, Object>> out = ChatService.trimPreviousAnswers(in, "이번 질문", 20);
                assertEquals(2, out.size());
                assertEquals("첫 답", out.get(1).get("answer"));
        }

        @Test
        void keepsTrailingUserEntryWhenItIsADifferentQuestion() {
                List<Map<String, Object>> in = List.of(row("USER", "다른 질문"), row("ASSISTANT", "답"), row("USER", "예전 질문"));
                List<Map<String, Object>> out = ChatService.trimPreviousAnswers(in, "이번 질문", 20);
                assertEquals(3, out.size());
        }

        @Test
        void capsToMostRecentEntriesPreservingOrder() {
                List<Map<String, Object>> in = new ArrayList<>();
                for (int i = 0; i < 100; i++) {
                        in.add(row(i % 2 == 0 ? "USER" : "ASSISTANT", "m" + i));
                }
                List<Map<String, Object>> out = ChatService.trimPreviousAnswers(in, "이번 질문", 20);
                assertEquals(20, out.size());
                assertEquals("m80", out.get(0).get("answer"));
                assertEquals("m99", out.get(19).get("answer"));
        }

        @Test
        void zeroOrNegativeMaxMeansNoCap() {
                List<Map<String, Object>> in = List.of(row("ASSISTANT", "a"), row("ASSISTANT", "b"));
                assertEquals(2, ChatService.trimPreviousAnswers(in, "q", 0).size());
                assertEquals(2, ChatService.trimPreviousAnswers(in, "q", -1).size());
        }

        @Test
        void nullAndEmptyAreSafe() {
                assertTrue(ChatService.trimPreviousAnswers(null, "q", 20).isEmpty());
                assertTrue(ChatService.trimPreviousAnswers(List.of(), "q", 20).isEmpty());
        }
}
