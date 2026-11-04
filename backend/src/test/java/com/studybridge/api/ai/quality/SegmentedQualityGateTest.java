package com.studybridge.api.ai.quality;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.studybridge.api.ai.contract.v1.ResponseQualityV1;
import com.studybridge.api.ai.quality.StubEvaluator.Reply;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;

/**
 * Phase D4 분할 평가: 84일 로드맵(≈15만 자)을 상한(6만 자) 이하 세그먼트로 나눠 모두 승인될 때만 전체 승인.
 * 누락·중복 커버리지·선수학습 위반은 평가 없이 거절, 세그먼트 하나라도 79 면 전체 거절, 체크섬으로 표시 범위 결속.
 */
class SegmentedQualityGateTest {

        static final ObjectMapper M = new ObjectMapper();

        /** 12주 × 7일 로드맵. 일자마다 ~1.8k 자 → 전체 ~15만 자. */
        static ObjectNode roadmap(String marker) {
                ObjectNode r = M.createObjectNode();
                r.put("title", "84일 네트워크 로드맵 " + marker);
                ArrayNode weeks = r.putArray("weeks");
                for (int w = 1; w <= 12; w++) {
                        ObjectNode wk = weeks.addObject();
                        wk.put("week", w);
                        wk.put("goal", w + "주차 목표 " + marker);
                        ArrayNode days = wk.putArray("days");
                        for (int d = 1; d <= 7; d++) {
                                ObjectNode day = days.addObject();
                                day.put("id", "w" + w + "d" + d);
                                day.put("prereq", d == 1 ? (w == 1 ? "" : "w" + (w - 1) + "d7") : "w" + w + "d" + (d - 1));
                                day.put("minutes", 60);
                                day.put("task", (w + "주 " + d + "일 학습 내용 " + marker + " ").repeat(120));
                        }
                }
                return r;
        }

        /** 헤더(title) + 연속 주차를 상한 이하로 묶는다. */
        static SegmentedQualityGate.Segmenter weeksPacker(int maxChars) {
                return full -> {
                        List<SegmentedQualityGate.SegmentPlan> out = new ArrayList<>();
                        out.add(new SegmentedQualityGate.SegmentPlan("hdr", List.of("/title")));
                        List<String> cur = new ArrayList<>();
                        int size = 0;
                        for (int i = 0; i < full.get("weeks").size(); i++) {
                                int s = full.get("weeks").get(i).toString().length();
                                if (!cur.isEmpty() && size + s > maxChars) {
                                        out.add(new SegmentedQualityGate.SegmentPlan("wk" + out.size(), List.copyOf(cur)));
                                        cur.clear();
                                        size = 0;
                                }
                                cur.add("/weeks/" + i);
                                size += s;
                        }
                        if (!cur.isEmpty()) {
                                out.add(new SegmentedQualityGate.SegmentPlan("wk" + out.size(), List.copyOf(cur)));
                        }
                        return out;
                };
        }

        /** 결정적 전체 검사: 84일, 주차 순서, 선수학습은 앞선 id 만, 하루 학습 시간 1..600분. */
        static final SegmentedQualityGate.WholeValidator VALIDATOR = full -> {
                List<String> v = new ArrayList<>();
                HashSet<String> seen = new HashSet<>();
                int days = 0;
                for (int i = 0; i < full.path("weeks").size(); i++) {
                        JsonNode wk = full.path("weeks").get(i);
                        if (wk.path("week").asInt() != i + 1) {
                                v.add("WEEK_ORDER");
                        }
                        for (JsonNode d : wk.path("days")) {
                                days++;
                                String pre = d.path("prereq").asText();
                                if (!pre.isEmpty() && !seen.contains(pre)) {
                                        v.add("PREREQ_NOT_EARLIER");
                                }
                                int m = d.path("minutes").asInt(-1);
                                if (m < 1 || m > 600) {
                                        v.add("MINUTES_OUT_OF_RANGE");
                                }
                                seen.add(d.path("id").asText());
                        }
                }
                if (days != 84) {
                        v.add("DAY_COUNT");
                }
                return v.stream().distinct().toList();
        };

        static AiResponseQualityGate.Spec spec() {
                return new AiResponseQualityGate.Spec("req-roadmap-0001", ResponseQualityV1.TaskType.PLANNER_COACHING,
                                ResponseQualityV1.OutputKind.PLAN_JSON, "84일 로드맵", List.of(), ResponseQualityV1.Constraints.empty(), null);
        }

        static SegmentedQualityGate gate(StubEvaluator stub) {
                AiQualityGateSettings s = AiQualityGateSettings.forTest(true);
                return new SegmentedQualityGate(new AiResponseQualityGate(s, stub.evaluatorClient(s)));
        }

        @Test
        void allSegmentsApprovedApprovesWholeWithBoundManifest() throws Exception {
                ObjectNode r = roadmap("A");
                assertTrue(r.toString().length() > 140_000, "실제 크기 재현: " + r.toString().length());
                try (StubEvaluator stub = new StubEvaluator(in -> Reply.output(in.requestId(), 85, false, "APPROVED"))) {
                        SegmentedQualityGate.Result res = gate(stub).evaluate(spec(), r, weeksPacker(55_000), VALIDATOR, 0);
                        assertTrue(res.approved());
                        assertTrue(stub.requests.size() >= 4, "헤더 + 주차 묶음 ≥3");
                        assertEquals(stub.requests.size(), stub.requests.stream().map(ResponseQualityV1.Input::requestId).distinct().count(),
                                        "세그먼트마다 고유 requestId");
                        assertTrue(stub.requests.stream().allMatch(in -> in.proposedOutput().toString().length() <= ResponseQualityV1.MAX_OUTPUT_CHARS));
                        assertEquals(stub.requests.size(), res.manifest().segments().size());
                        assertTrue(SegmentedQualityGate.stillApproved(r, res.manifest().fullChecksum()));
                        ((ObjectNode) r.get("weeks").get(5).get("days").get(2)).put("task", "편집된 과제");
                        assertFalse(SegmentedQualityGate.stillApproved(r, res.manifest().fullChecksum()), "표시본이 바뀌면 승인 범위 밖");
                }
        }

        @Test
        void oneSegmentAt79RejectsWhole() throws Exception {
                AtomicInteger n = new AtomicInteger();
                try (StubEvaluator stub = new StubEvaluator(in -> Reply.output(in.requestId(), n.incrementAndGet() == 3 ? 79 : 95, false,
                                n.get() == 3 ? "REJECTED" : "APPROVED"))) {
                        SegmentedQualityGate.Result res = gate(stub).evaluate(spec(), roadmap("B"), weeksPacker(55_000), VALIDATOR, 0);
                        assertFalse(res.approved(), "부분 승인으로 전체 승인 금지");
                        assertEquals(GateDecision.REJECTED, res.decision().errorCode());
                }
        }

        @Test
        void hardFailSegmentRejectsWhole() throws Exception {
                try (StubEvaluator stub = new StubEvaluator(in -> Reply.output(in.requestId(), 95, true, "REJECTED"))) {
                        assertFalse(gate(stub).evaluate(spec(), roadmap("C"), weeksPacker(55_000), VALIDATOR, 0).approved());
                }
        }

        @Test
        void missingOrDuplicateCoverageIsRejectedWithoutEvaluation() throws Exception {
                try (StubEvaluator stub = new StubEvaluator(in -> Reply.output(in.requestId(), 99, false, "APPROVED"))) {
                        SegmentedQualityGate g = gate(stub);
                        ObjectNode r = roadmap("D");
                        SegmentedQualityGate.Segmenter skipsWeek7 = full -> weeksPacker(55_000).plan(full).stream()
                                        .map(p -> new SegmentedQualityGate.SegmentPlan(p.segmentId(),
                                                        p.pointers().stream().filter(x -> !x.equals("/weeks/6")).toList()))
                                        .toList();
                        SegmentedQualityGate.Result miss = g.evaluate(spec(), r, skipsWeek7, VALIDATOR, 0);
                        assertFalse(miss.approved());
                        assertTrue(miss.violations().contains("SEGMENT_COVERAGE_MISSING"));
                        SegmentedQualityGate.Segmenter dup = full -> {
                                List<SegmentedQualityGate.SegmentPlan> l = new ArrayList<>(weeksPacker(55_000).plan(full));
                                l.add(new SegmentedQualityGate.SegmentPlan("dup", List.of("/weeks/0/days/0")));
                                return l;
                        };
                        SegmentedQualityGate.Result d = g.evaluate(spec(), r, dup, VALIDATOR, 0);
                        assertTrue(d.violations().contains("SEGMENT_OVERLAP") || d.violations().contains("SEGMENT_COVERAGE_DUPLICATE"));
                        SegmentedQualityGate.Result big = g.evaluate(spec(), r, full -> List.of(new SegmentedQualityGate.SegmentPlan("all", List.of("/title", "/weeks"))),
                                        VALIDATOR, 0);
                        assertTrue(big.violations().contains("SEGMENT_TOO_LARGE"), "원문을 잘라 평가하지 않는다 — 상한 초과 세그먼트는 거절");
                        assertEquals(0, stub.requests.size(), "결정적 사전 검사 실패면 평가기 호출 0");
                }
        }

        @Test
        void crossSegmentPrerequisiteViolationRejectedBeforeEvaluation() throws Exception {
                ObjectNode r = roadmap("E");
                ((ObjectNode) r.get("weeks").get(1).get("days").get(0)).put("prereq", "w9d3"); // 미래 항목 선수학습
                try (StubEvaluator stub = new StubEvaluator(in -> Reply.output(in.requestId(), 99, false, "APPROVED"))) {
                        SegmentedQualityGate.Result res = gate(stub).evaluate(spec(), r, weeksPacker(55_000), VALIDATOR, 0);
                        assertFalse(res.approved());
                        assertTrue(res.violations().contains("PREREQ_NOT_EARLIER"));
                        assertEquals(0, stub.requests.size());
                }
        }

        @Test
        void evaluatorOutageStopsAndRegenerationCapIsTwo() throws Exception {
                try (StubEvaluator stub = new StubEvaluator(in -> new Reply(503, "{}", 0))) {
                        AtomicInteger gens = new AtomicInteger();
                        SegmentedQualityGate.Outcome<JsonNode> o = gate(stub).generateApproved(spec(), (a, prev) -> {
                                gens.incrementAndGet();
                                return roadmap("F" + a);
                        }, x -> x, weeksPacker(55_000), VALIDATOR);
                        assertFalse(o.approved());
                        assertNull(o.value());
                        assertEquals(1, gens.get(), "평가기 장애면 재생성하지 않는다");
                        assertEquals(1, stub.requests.size(), "첫 세그먼트에서 장애 확인 후 중단");
                }
                AtomicInteger n = new AtomicInteger();
                try (StubEvaluator stub = new StubEvaluator(in -> Reply.output(in.requestId(), 70, false, "REJECTED"))) {
                        SegmentedQualityGate.Outcome<JsonNode> o = gate(stub).generateApproved(spec(), (a, prev) -> {
                                n.incrementAndGet();
                                return roadmap("G" + a);
                        }, x -> x, weeksPacker(55_000), VALIDATOR);
                        assertFalse(o.approved());
                        assertEquals(3, n.get(), "최초 1 + 재생성 2");
                }
        }

        @Test
        void generatorExceptionIsAnAttemptAndOpenCircuitSkipsGeneration() throws Exception {
                AtomicInteger n = new AtomicInteger();
                try (StubEvaluator stub = new StubEvaluator(in -> Reply.output(in.requestId(), 90, false, "APPROVED"))) {
                        SegmentedQualityGate.Outcome<JsonNode> o = gate(stub).generateApproved(spec(), (a, prev) -> {
                                if (n.incrementAndGet() == 1) {
                                        throw new IllegalStateException("upstream glitch");
                                }
                                return roadmap("H" + a);
                        }, x -> x, weeksPacker(55_000), VALIDATOR);
                        assertTrue(o.approved(), "생성기 예외는 시도 1회로 세고 다음 시도로");
                        assertEquals(2, n.get());
                }
                try (StubEvaluator stub = new StubEvaluator(in -> new Reply(503, "{}", 0))) {
                        AiQualityGateSettings s = AiQualityGateSettings.forTest(true);
                        AiResponseQualityGate g = new AiResponseQualityGate(s, stub.evaluatorClient(s));
                        for (int i = 0; i < 4; i++) { // forTest 임계 3 → 서킷 열림
                                g.evaluateOnce(spec(), "req-open-" + i, 0, M.createObjectNode().put("x", i)).block(java.time.Duration.ofSeconds(5));
                        }
                        AtomicInteger gens = new AtomicInteger();
                        SegmentedQualityGate.Outcome<JsonNode> o = new SegmentedQualityGate(g).generateApproved(spec(), (a, prev) -> {
                                gens.incrementAndGet();
                                return roadmap("I");
                        }, x -> x, weeksPacker(55_000), VALIDATOR);
                        assertFalse(o.approved());
                        assertEquals(0, gens.get(), "서킷 열림이면 생성(GPU) 0회");
                }
        }

        @Test
        void evaluatorRequestOverByteLimitIsNotSent() throws Exception {
                try (StubEvaluator stub = new StubEvaluator(in -> Reply.output(in.requestId(), 90, false, "APPROVED"))) {
                        AiQualityGateSettings s = AiQualityGateSettings.forTest(true);
                        AiResponseQualityGate g = new AiResponseQualityGate(s, stub.evaluatorClient(s));
                        // 문자 수 상한(6만) 안이지만 한글 UTF-8 바이트로는 256KiB 초과: 본문 5만 자 + 근거 4.8만 자 ≈ 29만 바이트
                        AiResponseQualityGate.Spec big = new AiResponseQualityGate.Spec("req-big-0001", ResponseQualityV1.TaskType.PDF_SUMMARY,
                                        ResponseQualityV1.OutputKind.TEXT, "요약", AiResponseQualityGate.pdfEvidence(1L, "가".repeat(48_000), 4000, 48_000),
                                        ResponseQualityV1.Constraints.empty(), null);
                        GateDecision d = g.evaluateOnce(big, "req-big-0001", 0, M.getNodeFactory().textNode("나".repeat(50_000)))
                                        .block(java.time.Duration.ofSeconds(5));
                        assertFalse(d.approved());
                        assertTrue(d.reasonCodes().contains("EVALUATOR_INPUT_TOO_LARGE"), String.valueOf(d.reasonCodes()));
                        assertEquals(0, stub.requests.size(), "보내지 않는다");
                }
        }
}

