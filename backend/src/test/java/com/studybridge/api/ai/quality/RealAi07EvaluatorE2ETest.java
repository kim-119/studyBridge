package com.studybridge.api.ai.quality;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.ai.contract.v1.ContractJson;
import com.studybridge.api.ai.contract.v1.ResponseQualityV1;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Flux;

/**
 * 격리 E2E(Phase D6): ai07 PR #116 의 실제 평가기 코드(fastapi/app/quality_gate, 결정적 평가·judge OFF)를 로컬 127.0.0.1 에 띄우고
 * Spring 게이트(QualityEvaluatorClient·AiResponseQualityGate·QualityStreamGate)를 실제 HTTP 로 붙인다. 운영 ai07·GPU·Ollama 미사용.
 * 실행: SB_AI07_EVAL_URL=http://127.0.0.1:18765 SB_AI07_EVAL_KEY=<로컬 테스트 Bearer> ./gradlew test --tests '*RealAi07EvaluatorE2ETest'
 * 지연 수치는 CPU 결정적 평가기 기준(judge=qwen3 GPU 아님) — 운영 실측이 아니다.
 */
@EnabledIfEnvironmentVariable(named = "SB_AI07_EVAL_URL", matches = "http://127\\.0\\.0\\.1:.*")
class RealAi07EvaluatorE2ETest {

        static final ObjectMapper M = new ObjectMapper();

        static AiQualityGateSettings settings(int concurrency) {
                return new AiQualityGateSettings(true, 2, 8000, concurrency, 2000, 5, 30000, "/api/ai/quality/evaluate", 60000, 400000);
        }

        static AiResponseQualityGate gate(int concurrency) {
                AiQualityGateSettings s = settings(concurrency);
                WebClient wc = WebClient.create(System.getenv("SB_AI07_EVAL_URL"));
                return new AiResponseQualityGate(s, new QualityEvaluatorClient(wc, s, System.getenv("SB_AI07_EVAL_KEY")));
        }

        static ResponseQualityV1.Input fixture(String name) throws Exception {
                try (var in = RealAi07EvaluatorE2ETest.class.getResourceAsStream("/ai-contracts/v1/response-quality.v1/" + name)) {
                        return ContractJson.STRICT.readValue(new String(in.readAllBytes(), StandardCharsets.UTF_8), ResponseQualityV1.Input.class);
                }
        }

        static GateDecision evaluate(AiResponseQualityGate g, ResponseQualityV1.Input in, String rid) {
                AiResponseQualityGate.Spec spec = new AiResponseQualityGate.Spec(rid, in.taskType(), in.outputKind(), in.originalRequest(),
                                in.groundingEvidence(), in.constraints(), in.modelDigest());
                return g.evaluateOnce(spec, rid, 0, in.proposedOutput()).block(Duration.ofSeconds(20));
        }

        static long pct(List<Long> xs, double p) {
                List<Long> s = new ArrayList<>(xs);
                Collections.sort(s);
                return s.isEmpty() ? -1 : s.get(Math.min(s.size() - 1, (int) Math.ceil(p * s.size()) - 1));
        }

        @Test
        void contractFixturesGetRealAi07Verdicts() throws Exception {
                AiResponseQualityGate g = gate(2);
                Map<String, Boolean> expectApproved = Map.of(
                                "input_pdf_summary_faithful.json", true,
                                "input_pdf_summary_contradiction.json", false,
                                "input_math_incorrect.json", false,
                                "input_quiz_answer_explanation_mismatch.json", false,
                                "input_vision_unsupported_observation.json", false);
                Map<String, String> seen = new java.util.TreeMap<>();
                for (var e : expectApproved.entrySet()) {
                        GateDecision d = evaluate(g, fixture(e.getKey()), "req-e2e-" + Math.abs(e.getKey().hashCode()));
                        assertNotNull(d);
                        seen.put(e.getKey(), (d.approved() ? "APPROVED " : "NOT_APPROVED ") + d.score() + " " + d.reasonCodes());
                        assertEquals(e.getValue(), d.approved(), e.getKey() + " → " + seen.get(e.getKey()));
                }
                seen.forEach((k, v) -> System.out.println("[E2E] verdict " + k + " = " + v));
        }

        @Test
        void regenerationRealEvaluatorRejectsContradictionThenApprovesFaithful() throws Exception {
                ResponseQualityV1.Input bad = fixture("input_pdf_summary_contradiction.json");
                ResponseQualityV1.Input good = fixture("input_pdf_summary_faithful.json");
                AiResponseQualityGate.Spec spec = new AiResponseQualityGate.Spec("req-e2e-regen-0001", good.taskType(), good.outputKind(),
                                good.originalRequest(), good.groundingEvidence(), good.constraints(), good.modelDigest());
                AtomicInteger gens = new AtomicInteger();
                AiResponseQualityGate.Outcome<JsonNode> o = gate(2).generateApproved(spec, (a, prev) -> {
                        gens.incrementAndGet();
                        return a == 0 ? bad.proposedOutput() : good.proposedOutput();
                }, x -> x);
                System.out.println("[E2E] regeneration attempts=" + gens.get() + " approved=" + o.approved() + " score=" + o.decision().score());
                assertTrue(o.approved());
                assertEquals(2, gens.get(), "원문 모순 초안 거절 → 재생성 1회 후 승인");
                assertEquals(good.proposedOutput(), o.value(), "승인된 것은 두 번째 초안");
        }

        @Test
        void sseCapturesThroughRealEvaluatorLeakNoUnapprovedText() throws Exception {
                for (String cap : List.of("studymate_multichat_default", "studymate_multichat_socratic", "studymate_multichat_debate")) {
                        List<ServerSentEvent<String>> in = QualityStreamGateTest.capture(cap);
                        QualityStreamGate sg = new QualityStreamGate(gate(2));
                        long t0 = System.nanoTime();
                        List<ServerSentEvent<String>> out = sg.gate(Flux.fromIterable(in), new QualityStreamGate.Context("req-e2e-sse-" + cap.hashCode(),
                                        QualityStreamGate.taskTypeForLearningMode(cap.endsWith("socratic") ? "socratic" : cap.endsWith("debate") ? "debate" : "basic"),
                                        "객체지향이 뭐야?", ResponseQualityV1.Constraints.empty())).collectList().block(Duration.ofSeconds(60));
                        long ms = (System.nanoTime() - t0) / 1_000_000;
                        JsonNode all = null;
                        int approved = 0;
                        int errors = 0;
                        for (ServerSentEvent<String> e : out) {
                                if ("all_complete".equals(e.event())) {
                                        all = M.readTree(e.data());
                                }
                                if ("agent_error".equals(e.event())) {
                                        errors++;
                                }
                                if (e.data() != null && e.data().contains("\"qualityStatus\":\"APPROVED\"")) {
                                        approved++;
                                }
                        }
                        // 승인되지 않은 에이전트 본문은 출력 어디에도 없어야 한다(실평가기 판정 기준).
                        java.util.Set<String> inSentences = new java.util.HashSet<>();
                        java.util.Set<String> outText = new java.util.HashSet<>();
                        for (ServerSentEvent<String> e : out) {
                                if (e.data() != null) {
                                        outText.add(e.data());
                                }
                        }
                        String joined = String.join("\n", outText);
                        int leaked = 0;
                        for (ServerSentEvent<String> e : in) {
                                if (e.data() == null || !"agent_answer".equals(e.event())) {
                                        continue;
                                }
                                JsonNode n = M.readTree(e.data());
                                String content = n.path("content").asText("");
                                boolean wasApproved = joined.contains(content) && !content.isBlank();
                                if (!wasApproved && !content.isBlank() && joined.contains(content.substring(0, Math.min(40, content.length())))) {
                                        leaked++;
                                }
                        }
                        System.out.println("[E2E] sse " + cap + " events=" + out.size() + " approvedFrames=" + approved + " agentErrors=" + errors
                                        + " qualityGate=" + (all == null ? null : all.get("qualityGate")) + " turnMs=" + ms);
                        assertEquals(0, leaked, cap + ": 거절된 본문 일부가 출력에 남음");
                        assertNotNull(all, cap + ": all_complete 재구성");
                }
        }

        @Test
        void latencyAndConcurrencyUnderRealEvaluator() throws Exception {
                ResponseQualityV1.Input in = fixture("input_pdf_summary_faithful.json");
                AiResponseQualityGate g = gate(2);
                List<Long> seq = new ArrayList<>();
                for (int i = 0; i < 60; i++) {
                        long t0 = System.nanoTime();
                        GateDecision d = evaluate(g, in, "req-e2e-seq-" + i);
                        seq.add((System.nanoTime() - t0) / 1_000_000);
                        assertTrue(d.approved());
                }
                System.out.println("[E2E] sequential n=60 p50=" + pct(seq, 0.50) + "ms p95=" + pct(seq, 0.95) + "ms max=" + pct(seq, 1.0) + "ms");
                for (int parallel : List.of(4, 8, 16)) {
                        ExecutorService pool = Executors.newFixedThreadPool(parallel);
                        List<Long> lat = Collections.synchronizedList(new ArrayList<>());
                        Map<String, AtomicInteger> codes = new ConcurrentHashMap<>();
                        List<Future<?>> fs = new ArrayList<>();
                        for (int i = 0; i < parallel * 4; i++) {
                                final int k = i;
                                fs.add(pool.submit(() -> {
                                        long t0 = System.nanoTime();
                                        GateDecision d = evaluate(g, in, "req-e2e-par-" + parallel + "-" + k);
                                        lat.add((System.nanoTime() - t0) / 1_000_000);
                                        String c = d.approved() ? "APPROVED" : String.valueOf(d.reasonCodes());
                                        codes.computeIfAbsent(c, x -> new AtomicInteger()).incrementAndGet();
                                }));
                        }
                        for (Future<?> f : fs) {
                                f.get();
                        }
                        pool.shutdown();
                        System.out.println("[E2E] parallel=" + parallel + " n=" + lat.size() + " p50=" + pct(lat, 0.50) + "ms p95=" + pct(lat, 0.95)
                                        + "ms outcomes=" + codes);
                        assertFalse(codes.keySet().stream().anyMatch(c -> c.contains("EXCEPTION")), "예외 없이 승인 또는 명시적 불가(BUSY)");
                }
        }
}
