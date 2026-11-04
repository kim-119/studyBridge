package com.studybridge.api.ai.quality;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.ai.contract.v1.ResponseQualityV1;
import com.studybridge.api.ai.quality.StubEvaluator.Reply;
import java.io.InputStream;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.zip.GZIPInputStream;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.http.codec.ServerSentEvent;
import reactor.core.publisher.Flux;

/**
 * 학습메이트 multi-chat SSE 게이트 — ai07 실캡처(hotfix_main, 가짜 LLM, canary CANARY7F3A) 기반.
 *  deny-all: 생성 본문 0자 노출(canary 0회), agent_error(QUALITY_REJECTED, agentIndex/eventId 유지), all_complete.answers 빈 배열.
 *  approve-all: agent_answer/all_complete 계약 유지(answers 개수·eventId·agentIndex 보존).
 */
class QualityStreamGateTest {

        static final ObjectMapper M = new ObjectMapper();
        static final String CANARY = "CANARY7F3A";

        static List<ServerSentEvent<String>> capture(String name) throws Exception {
                try (InputStream in = new GZIPInputStream(QualityStreamGateTest.class
                                .getResourceAsStream("/ai-contracts/v1/stream-captures/" + name + ".json.gz"))) {
                        Map<String, Object> d = M.readValue(in, new TypeReference<Map<String, Object>>() {});
                        List<ServerSentEvent<String>> out = new ArrayList<>();
                        for (String frame : ((String) d.get("raw")).split("\n\n")) {
                                String ev = null;
                                StringBuilder data = new StringBuilder();
                                for (String line : frame.split("\n")) {
                                        if (line.startsWith("event:")) {
                                                ev = line.substring(6).trim();
                                        } else if (line.startsWith("data:")) {
                                                data.append(line.substring(5).trim());
                                        }
                                }
                                if (data.length() > 0) {
                                        out.add(ServerSentEvent.<String>builder(data.toString()).event(ev).build());
                                }
                        }
                        return out;
                }
        }

        /** 공백 또는 한글을 포함한 12자 이상 문자열(= 문장형 본문). 식별자(eventId 등)는 제외된다. */
        static void collectSentences(com.fasterxml.jackson.databind.JsonNode n, java.util.Set<String> out) {
                if (n.isTextual()) {
                        String t = n.asText();
                        if (t.length() >= 12 && (t.contains(" ") || t.chars().anyMatch(c -> c >= 0xAC00 && c <= 0xD7A3))) {
                                out.add(t.length() > 40 ? t.substring(0, 40) : t);
                        }
                } else {
                        n.forEach(c -> collectSentences(c, out));
                }
        }

        static QualityStreamGate gate(StubEvaluator stub) {
                AiQualityGateSettings s = AiQualityGateSettings.forTest(true);
                return new QualityStreamGate(new AiResponseQualityGate(s, stub.evaluatorClient(s)));
        }

        static QualityStreamGate.Context ctx(ResponseQualityV1.TaskType t) {
                return new QualityStreamGate.Context("req-stream-gate-001", t, "객체지향이 뭐야?", ResponseQualityV1.Constraints.empty());
        }

        static Map<String, Object> json(ServerSentEvent<String> e) throws Exception {
                return M.readValue(e.data(), new TypeReference<Map<String, Object>>() {});
        }

        @ParameterizedTest
        @ValueSource(strings = {"studymate_multichat_default", "studymate_multichat_socratic", "studymate_multichat_debate"})
        void denyAllLeaksZeroBodyCharacters(String name) throws Exception {
                List<ServerSentEvent<String>> in = capture(name);
                // 상류 본문 이벤트(진행/종료 메타 제외)의 문장형 문자열 전부 — 게이트 거절 시 이 중 어느 것도 나가면 안 된다.
                java.util.Set<String> bodyStrings = new java.util.HashSet<>();
                for (ServerSentEvent<String> e : in) {
                        if (!QualityStreamGate.PROGRESS.contains(e.event()) && !"done".equals(e.event())) {
                                collectSentences(M.readTree(e.data()), bodyStrings);
                        }
                }
                assertTrue(bodyStrings.size() >= 1, "캡처에 검증할 본문이 있어야 한다: " + bodyStrings.size());
                try (StubEvaluator stub = new StubEvaluator(r -> Reply.output(r.requestId(), 40, false, "REJECTED"))) {
                        List<ServerSentEvent<String>> out = gate(stub).gate(Flux.fromIterable(in), ctx(QualityStreamGate.taskTypeForLearningMode(name)))
                                        .collectList().block(Duration.ofSeconds(20));
                        for (ServerSentEvent<String> e : out) {
                                assertFalse(e.data() != null && e.data().contains(CANARY), "본문 선노출: " + e.event());
                                assertFalse(e.data() != null && e.data().contains("sk-proj"), "비밀 문자열 노출");
                                for (String b : bodyStrings) {
                                        assertFalse(e.data() != null && e.data().contains(b), "본문 선노출(" + e.event() + "): " + b);
                                }
                        }
                        ServerSentEvent<String> all = out.stream().filter(e -> "all_complete".equals(e.event())).findFirst().orElseThrow();
                        assertEquals(List.of(), json(all).get("answers"));
                        assertEquals(List.of(), json(all).get("messages"));
                        assertTrue(out.stream().anyMatch(e -> "done".equals(e.event())), "done 은 유지");
                }
        }

        @Test
        void denyAllEmitsAgentErrorPreservingIdentity() throws Exception {
                List<ServerSentEvent<String>> in = capture("studymate_multichat_socratic");
                try (StubEvaluator stub = new StubEvaluator(r -> Reply.output(r.requestId(), 79, false, "REJECTED"))) {
                        List<ServerSentEvent<String>> out = gate(stub).gate(Flux.fromIterable(in), ctx(ResponseQualityV1.TaskType.STUDYMATE_SOCRATIC))
                                        .collectList().block(Duration.ofSeconds(20));
                        List<Map<String, Object>> errors = new ArrayList<>();
                        for (ServerSentEvent<String> e : out) {
                                if ("agent_error".equals(e.event())) {
                                        errors.add(json(e));
                                }
                        }
                        long upstreamAnswers = in.stream().filter(e -> "agent_answer".equals(e.event())).count();
                        assertEquals(upstreamAnswers, errors.size(), "에이전트 발화마다 개별 거절 알림");
                        for (Map<String, Object> err : errors) {
                                assertEquals("QUALITY_REJECTED", err.get("code"));
                                assertEquals(true, err.get("retryable"));
                                assertTrue(err.containsKey("agentIndex") && err.containsKey("eventId") && err.containsKey("turnId"));
                        }
                        assertTrue(stub.requests.stream().allMatch(r -> r.taskType() == ResponseQualityV1.TaskType.STUDYMATE_SOCRATIC
                                        && r.outputKind() == ResponseQualityV1.OutputKind.AGENT_MESSAGE));
                }
        }

        @Test
        void approveAllKeepsContract() throws Exception {
                List<ServerSentEvent<String>> in = capture("studymate_multichat_socratic");
                Map<String, Object> upstreamAll = json(in.stream().filter(e -> "all_complete".equals(e.event())).findFirst().orElseThrow());
                try (StubEvaluator stub = new StubEvaluator(r -> Reply.output(r.requestId(), 92, false, "APPROVED"))) {
                        List<ServerSentEvent<String>> out = gate(stub).gate(Flux.fromIterable(in), ctx(ResponseQualityV1.TaskType.STUDYMATE_SOCRATIC))
                                        .collectList().block(Duration.ofSeconds(20));
                        List<String> upstreamOrder = in.stream().map(ServerSentEvent::event).toList();
                        List<String> outOrder = out.stream().map(ServerSentEvent::event).toList();
                        assertEquals(upstreamOrder, outOrder, "승인 시 이벤트 순서·종류 보존");
                        Map<String, Object> all = json(out.stream().filter(e -> "all_complete".equals(e.event())).findFirst().orElseThrow());
                        @SuppressWarnings("unchecked")
                        List<Map<String, Object>> answers = (List<Map<String, Object>>) all.get("answers");
                        @SuppressWarnings("unchecked")
                        List<Map<String, Object>> upAnswers = (List<Map<String, Object>>) upstreamAll.get("answers");
                        assertEquals(upAnswers.size(), answers.size());
                        for (int i = 0; i < answers.size(); i++) {
                                assertEquals(upAnswers.get(i).get("eventId"), answers.get(i).get("eventId"));
                                assertEquals(upAnswers.get(i).get("agentIndex"), answers.get(i).get("agentIndex"));
                                assertEquals(upAnswers.get(i).get("answer"), answers.get(i).get("answer"));
                                assertEquals("APPROVED", answers.get(i).get("qualityStatus"));
                        }
                        assertEquals(Map.of("applied", true, "approved", 3, "rejected", 0), all.get("qualityGate"));
                }
        }

        @Test
        void progressTextUnknownEventsAndDeltasNeverLeak() throws Exception {
                List<ServerSentEvent<String>> in = List.of(
                                ServerSentEvent.<String>builder("{\"type\":\"turn_start\",\"turnId\":\"t1\",\"content\":\"CANARY7F3A 진행 중 본문\",\"message\":\"CANARY7F3A\"}").event("turn_start").build(),
                                ServerSentEvent.<String>builder("{\"type\":\"token\",\"delta\":\"CANARY7F3A 토큰\"}").event("token").build(),
                                ServerSentEvent.<String>builder("{\"type\":\"brand_new\",\"text\":\"CANARY7F3A 미지 타입\"}").event("brand_new").build(),
                                ServerSentEvent.<String>builder("{\"type\":\"error\",\"code\":\"AI_TIMEOUT\",\"message\":\"Traceback CANARY7F3A host=10.0.0.5\"}").event("error").build(),
                                ServerSentEvent.<String>builder().comment("hb").build());
                try (StubEvaluator stub = new StubEvaluator(r -> Reply.output(r.requestId(), 99, false, "APPROVED"))) {
                        List<ServerSentEvent<String>> out = gate(stub).gate(Flux.fromIterable(in), ctx(ResponseQualityV1.TaskType.STUDYMATE_BASIC))
                                        .collectList().block(Duration.ofSeconds(10));
                        assertEquals(List.of("turn_start", "error"), out.stream().map(ServerSentEvent::event).filter(e -> e != null).toList());
                        assertTrue(out.stream().allMatch(e -> e.data() == null || !e.data().contains(CANARY)));
                        assertEquals("t1", json(out.get(0)).get("turnId"));
                        assertEquals("AI_TIMEOUT", json(out.get(1)).get("code"));
                        assertEquals(1, out.stream().filter(e -> "hb".equals(e.comment())).count(), "heartbeat 주석은 통과");
                        assertEquals(0, stub.requests.size(), "본문 메시지가 없으면 평가하지 않는다");
                }
        }

        @Test
        void duplicateMessageIsEmittedOnceAndEvaluatedOnce() throws Exception {
                String a = "{\"type\":\"agent_answer\",\"eventId\":\"e1\",\"agentIndex\":1,\"answer\":\"정상 답변\"}";
                List<ServerSentEvent<String>> in = List.of(ServerSentEvent.<String>builder(a).event("agent_answer").build(),
                                ServerSentEvent.<String>builder(a).event("agent_answer").build());
                try (StubEvaluator stub = new StubEvaluator(r -> Reply.output(r.requestId(), 90, false, "APPROVED"))) {
                        List<ServerSentEvent<String>> out = gate(stub).gate(Flux.fromIterable(in), ctx(ResponseQualityV1.TaskType.STUDYMATE_BASIC))
                                        .collectList().block(Duration.ofSeconds(10));
                        assertEquals(1, out.size());
                        assertEquals(1, stub.requests.size());
                }
        }

        @Test
        void evaluatorTimeoutBecomesQualityUnavailable() throws Exception {
                String a = "{\"type\":\"agent_answer\",\"eventId\":\"e1\",\"agentIndex\":1,\"answer\":\"CANARY7F3A 답변\"}";
                try (StubEvaluator stub = new StubEvaluator(r -> new Reply(200, Reply.output(r.requestId(), 99, false, "APPROVED").body(), 3500))) {
                        List<ServerSentEvent<String>> out = gate(stub).gate(Flux.just(ServerSentEvent.<String>builder(a).event("agent_answer").build()),
                                        ctx(ResponseQualityV1.TaskType.STUDYMATE_BASIC)).collectList().block(Duration.ofSeconds(10));
                        assertEquals("agent_error", out.get(0).event());
                        assertEquals("QUALITY_UNAVAILABLE", json(out.get(0)).get("code"));
                        assertFalse(out.get(0).data().contains(CANARY));
                }
        }

        @Test
        void oversizeMessageRejectedWithoutEvaluation() throws Exception {
                String big = "가".repeat(60001);
                String a = "{\"type\":\"agent_answer\",\"eventId\":\"e1\",\"agentIndex\":1,\"answer\":\"" + big + "\"}";
                try (StubEvaluator stub = new StubEvaluator(r -> Reply.output(r.requestId(), 99, false, "APPROVED"))) {
                        List<ServerSentEvent<String>> out = gate(stub).gate(Flux.just(ServerSentEvent.<String>builder(a).event("agent_answer").build()),
                                        ctx(ResponseQualityV1.TaskType.STUDYMATE_BASIC)).collectList().block(Duration.ofSeconds(10));
                        assertEquals("agent_error", out.get(0).event());
                        assertEquals(0, stub.requests.size());
                }
        }

        @Test
        void cancellationPropagatesUpstream() throws Exception {
                AtomicBoolean upstreamCancelled = new AtomicBoolean();
                Flux<ServerSentEvent<String>> slow = Flux.interval(Duration.ofMillis(50))
                                .map(i -> ServerSentEvent.<String>builder("{\"type\":\"progress\",\"seq\":" + i + "}").event("progress").build())
                                .doOnCancel(() -> upstreamCancelled.set(true));
                try (StubEvaluator stub = new StubEvaluator(r -> Reply.output(r.requestId(), 99, false, "APPROVED"))) {
                        List<ServerSentEvent<String>> out = gate(stub).gate(slow, ctx(ResponseQualityV1.TaskType.STUDYMATE_BASIC))
                                        .take(3).collectList().block(Duration.ofSeconds(5));
                        assertEquals(3, out.size());
                        assertTrue(upstreamCancelled.get(), "클라이언트 취소 → 상류(ai07 스트림) 구독 취소");
                }
        }

        @Test
        void concurrentStreamsDoNotMixVerdicts() throws Exception {
                // 같은 게이트 빈으로 두 사용자 스트림을 동시에 처리: A 는 승인 문구, B 는 거절 문구 — 판정이 섞이면 안 된다.
                try (StubEvaluator stub = new StubEvaluator(r -> StubEvaluator.textOf(r).contains("APPROVE_ME")
                                ? Reply.output(r.requestId(), 90, false, "APPROVED") : Reply.output(r.requestId(), 10, false, "REJECTED"))) {
                        QualityStreamGate g = gate(stub);
                        Flux<ServerSentEvent<String>> a = Flux.range(0, 5).map(i -> ServerSentEvent.<String>builder(
                                        "{\"type\":\"agent_answer\",\"eventId\":\"a" + i + "\",\"agentIndex\":" + i + ",\"answer\":\"APPROVE_ME " + i + "\"}")
                                        .event("agent_answer").build());
                        Flux<ServerSentEvent<String>> b = Flux.range(0, 5).map(i -> ServerSentEvent.<String>builder(
                                        "{\"type\":\"agent_answer\",\"eventId\":\"b" + i + "\",\"agentIndex\":" + i + ",\"answer\":\"CANARY7F3A " + i + "\"}")
                                        .event("agent_answer").build());
                        var ra = g.gate(a, ctx(ResponseQualityV1.TaskType.STUDYMATE_BASIC)).collectList();
                        var rb = g.gate(b, ctx(ResponseQualityV1.TaskType.STUDYMATE_BASIC)).collectList();
                        var both = reactor.core.publisher.Mono.zip(ra, rb).block(Duration.ofSeconds(20));
                        assertTrue(both.getT1().stream().allMatch(e -> "agent_answer".equals(e.event())));
                        assertTrue(both.getT2().stream().allMatch(e -> "agent_error".equals(e.event()) && !e.data().contains(CANARY)));
                }
        }
}
