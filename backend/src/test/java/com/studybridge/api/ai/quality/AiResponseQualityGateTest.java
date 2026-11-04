package com.studybridge.api.ai.quality;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.studybridge.api.ai.contract.v1.ResponseQualityV1;
import com.studybridge.api.ai.contract.v1.ResponseQualityV1.QualityStatus;
import com.studybridge.api.ai.quality.StubEvaluator.Reply;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;
import reactor.core.publisher.Flux;

/**
 * JSON 경로 게이트: 79 거절 / 80 승인 / 95+HardFail 거절 / null 점수 / 재생성 2회 후 승인 / 전부 실패 차단 /
 * 평가기 503·timeout·success:false 미노출 / 동일 초안 반복 중단 / Bearer·계약 / 서킷 / bulkhead.
 */
class AiResponseQualityGateTest {

        static AiResponseQualityGate.Spec spec() {
                return new AiResponseQualityGate.Spec("req-unit-gate-0001", ResponseQualityV1.TaskType.PDF_SUMMARY,
                                ResponseQualityV1.OutputKind.TEXT, "요약해줘",
                                AiResponseQualityGate.pdfEvidence(42L, "TCP 3-way handshake 는 SYN, SYN-ACK, ACK.", 4000, 48000),
                                ResponseQualityV1.Constraints.empty(), null);
        }

        static AiResponseQualityGate gate(StubEvaluator stub, AiQualityGateSettings s) {
                return new AiResponseQualityGate(s, stub.evaluatorClient(s));
        }

        /** 시도 순서대로 점수를 돌려주는 정책. */
        static java.util.function.Function<ResponseQualityV1.Input, Reply> scores(double... scores) {
                AtomicInteger i = new AtomicInteger();
                return in -> {
                        double s = scores[Math.min(i.getAndIncrement(), scores.length - 1)];
                        return Reply.output(in.requestId(), s, false, s >= 80 ? "APPROVED" : "REJECTED");
                };
        }

        @Test
        void score79IsRejectedAndRegeneratedUntil85IsApproved() throws Exception {
                try (StubEvaluator stub = new StubEvaluator(scores(79, 70, 85))) {
                        List<Integer> attempts = new ArrayList<>();
                        AiResponseQualityGate.Outcome<String> o = gate(stub, AiQualityGateSettings.forTest(true))
                                        .generateApproved(spec(), (a, prev) -> {
                                                attempts.add(a);
                                                return "초안 " + a;
                                        }, AiResponseQualityGate::text);
                        assertTrue(o.approved());
                        assertEquals("초안 2", o.value());
                        assertEquals(List.of(0, 1, 2), attempts);
                        assertEquals(3, o.decision().attempts());
                        assertEquals(List.of(0, 1, 2), stub.requests.stream().map(ResponseQualityV1.Input::attemptIndex).toList());
                        assertTrue(stub.authHeaders.stream().allMatch(h -> h.equals("Bearer " + "k".repeat(64))));
                        assertEquals(3, stub.requests.stream().map(ResponseQualityV1.Input::requestId).distinct().count(),
                                        "시도마다 고유 requestId(평가기 멱등 409 방지)");
                }
        }

        @Test
        void score80IsApprovedOnFirstAttempt() throws Exception {
                try (StubEvaluator stub = new StubEvaluator(scores(80))) {
                        AiResponseQualityGate.Outcome<String> o = gate(stub, AiQualityGateSettings.forTest(true))
                                        .generateApproved(spec(), (a, p) -> "초안", AiResponseQualityGate::text);
                        assertTrue(o.approved());
                        assertEquals(80.0, o.decision().score());
                }
        }

        @Test
        void allRegenerationsFailingBlocksOutput() throws Exception {
                try (StubEvaluator stub = new StubEvaluator(scores(79, 79, 79, 99))) {
                        AiResponseQualityGate.Outcome<String> o = gate(stub, AiQualityGateSettings.forTest(true))
                                        .generateApproved(spec(), (a, p) -> "초안 " + a, AiResponseQualityGate::text);
                        assertFalse(o.approved());
                        assertNull(o.value());
                        assertEquals(QualityStatus.REJECTED, o.decision().qualityStatus());
                        assertEquals(GateDecision.REJECTED, o.decision().errorCode());
                        assertEquals(3, stub.requests.size(), "최초 1 + 재생성 2 = 3회까지만");
                }
        }

        @Test
        void hardFailWith95IsRejected() throws Exception {
                try (StubEvaluator stub = new StubEvaluator(in -> Reply.output(in.requestId(), 95, true, "REJECTED"))) {
                        AiResponseQualityGate.Outcome<String> o = gate(stub, AiQualityGateSettings.forTest(true))
                                        .generateApproved(spec(), (a, p) -> "초안 " + a, AiResponseQualityGate::text);
                        assertFalse(o.approved());
                        assertTrue(o.decision().reasonCodes().contains("SOURCE_CONTRADICTION"));
                }
        }

        @Test
        void approvedLabelWithHardFailIsContractViolationNotApproval() throws Exception {
                // 평가기가 APPROVED+hardFail 을 보내도(계약 위반) 노출하지 않는다.
                try (StubEvaluator stub = new StubEvaluator(in -> Reply.output(in.requestId(), 95, true, "APPROVED"))) {
                        AiResponseQualityGate.Outcome<String> o = gate(stub, AiQualityGateSettings.forTest(true))
                                        .generateApproved(spec(), (a, p) -> "초안 " + a, AiResponseQualityGate::text);
                        assertFalse(o.approved());
                        assertEquals(QualityStatus.VALIDATION_ERROR, o.decision().qualityStatus());
                        assertEquals(List.of("EVALUATOR_OUTPUT_CONTRACT_INVALID"), o.decision().reasonCodes());
                }
        }

        @Test
        void nullScoreIsRejected() throws Exception {
                try (StubEvaluator stub = new StubEvaluator(in -> new Reply(200, Reply.output(in.requestId(), 0, false, "REJECTED").body()
                                .replace("\"score\":0.0", "\"score\":null"), 0))) {
                        AiResponseQualityGate.Outcome<String> o = gate(stub, AiQualityGateSettings.forTest(true))
                                        .generateApproved(spec(), (a, p) -> "초안 " + a, AiResponseQualityGate::text);
                        assertFalse(o.approved());
                }
        }

        @Test
        void evaluator503IsNotDisplayedAndNotRegenerated() throws Exception {
                try (StubEvaluator stub = new StubEvaluator(in -> new Reply(503, "{\"success\":false,\"errorCode\":\"FEATURE_DISABLED\"}", 0))) {
                        AtomicInteger generated = new AtomicInteger();
                        AiResponseQualityGate.Outcome<String> o = gate(stub, AiQualityGateSettings.forTest(true))
                                        .generateApproved(spec(), (a, p) -> "초안 " + generated.incrementAndGet(), AiResponseQualityGate::text);
                        assertFalse(o.approved());
                        assertEquals(QualityStatus.VALIDATION_ERROR, o.decision().qualityStatus());
                        assertEquals(GateDecision.UNAVAILABLE, o.decision().errorCode());
                        assertEquals(List.of("EVALUATOR_UNAVAILABLE"), o.decision().reasonCodes());
                        assertEquals(1, generated.get(), "평가기 장애는 재생성으로 해결되지 않는다");
                }
        }

        @Test
        void http200WithSuccessFalseIsNotApproval() throws Exception {
                try (StubEvaluator stub = new StubEvaluator(in -> new Reply(200, "{\"success\":false,\"errorCode\":\"FEATURE_DISABLED\"}", 0))) {
                        AiResponseQualityGate.Outcome<String> o = gate(stub, AiQualityGateSettings.forTest(true))
                                        .generateApproved(spec(), (a, p) -> "초안", AiResponseQualityGate::text);
                        assertFalse(o.approved());
                        assertEquals(List.of("EVALUATOR_OUTPUT_CONTRACT_INVALID"), o.decision().reasonCodes());
                }
        }

        @Test
        void evaluatorTimeoutIsNotDisplayed() throws Exception {
                try (StubEvaluator stub = new StubEvaluator(in -> new Reply(200, Reply.output(in.requestId(), 99, false, "APPROVED").body(), 3500))) {
                        AiResponseQualityGate.Outcome<String> o = gate(stub, AiQualityGateSettings.forTest(true))
                                        .generateApproved(spec(), (a, p) -> "초안", AiResponseQualityGate::text);
                        assertFalse(o.approved());
                        assertEquals(List.of("EVALUATOR_TIMEOUT"), o.decision().reasonCodes());
                }
        }

        @Test
        void identicalDraftStopsRegeneration() throws Exception {
                try (StubEvaluator stub = new StubEvaluator(scores(70))) {
                        AiResponseQualityGate.Outcome<String> o = gate(stub, AiQualityGateSettings.forTest(true))
                                        .generateApproved(spec(), (a, p) -> "늘 같은 초안", AiResponseQualityGate::text);
                        assertFalse(o.approved());
                        assertEquals(List.of("IDENTICAL_DRAFT_REPEATED"), o.decision().reasonCodes());
                        assertEquals(1, stub.requests.size());
                }
        }

        @Test
        void emptyDraftAndGeneratorExceptionAreNotApproved() throws Exception {
                try (StubEvaluator stub = new StubEvaluator(scores(99))) {
                        AiResponseQualityGate.Outcome<String> o = gate(stub, AiQualityGateSettings.forTest(true))
                                        .generateApproved(spec(), (a, p) -> {
                                                if (a == 0) {
                                                        throw new IllegalStateException("upstream");
                                                }
                                                return a == 1 ? "  " : "정상 초안";
                                        }, AiResponseQualityGate::text);
                        assertTrue(o.approved(), "세 번째 시도에서 승인");
                        assertEquals(1, stub.requests.size(), "빈 초안/생성 실패는 평가기에 보내지 않는다");
                }
        }

        @Test
        void circuitOpensAfterConsecutiveInfraFailures() throws Exception {
                try (StubEvaluator stub = new StubEvaluator(in -> new Reply(503, "{}", 0))) {
                        AiQualityGateSettings s = AiQualityGateSettings.forTest(true); // threshold 3, open 1000ms
                        QualityEvaluatorClient c = stub.evaluatorClient(s);
                        AiResponseQualityGate g = new AiResponseQualityGate(s, c);
                        for (int i = 0; i < 5; i++) {
                                g.generateApproved(spec(), (a, p) -> "초안 " + System.nanoTime(), AiResponseQualityGate::text);
                        }
                        assertEquals(3, stub.requests.size(), "3회 연속 실패 후에는 평가기를 호출하지 않는다");
                        AiResponseQualityGate.Outcome<String> o = g.generateApproved(spec(), (a, p) -> "x", AiResponseQualityGate::text);
                        assertEquals(List.of("EVALUATOR_CIRCUIT_OPEN"), o.decision().reasonCodes());
                        Thread.sleep(1100);
                        stub.policy = in -> Reply.output(in.requestId(), 90, false, "APPROVED");
                        assertTrue(g.generateApproved(spec(), (a, p) -> "회복 " + System.nanoTime(), AiResponseQualityGate::text).approved(),
                                        "반개방 시험이 성공하면 닫힌다");
                }
        }

        @Test
        void bulkheadLimitsConcurrentEvaluations() throws Exception {
                try (StubEvaluator stub = new StubEvaluator(in -> new Reply(200, Reply.output(in.requestId(), 90, false, "APPROVED").body(), 400))) {
                        AiQualityGateSettings s = new AiQualityGateSettings(true, 2, 3000, 1, 0, 5, 1000, "/api/ai/quality/evaluate", 60000, 400000);
                        AiResponseQualityGate g = new AiResponseQualityGate(s, stub.evaluatorClient(s));
                        List<GateDecision> ds = Flux.range(0, 4)
                                        .flatMap(i -> g.evaluateOnce(spec(), "req-bulkhead-" + i, 0, AiResponseQualityGate.text("초안 " + i)))
                                        .collectList().block();
                        assertEquals(1, stub.maxInFlight.get(), "동시 평가 상한 1");
                        assertTrue(ds.stream().anyMatch(d -> d.reasonCodes().contains("EVALUATOR_BUSY")), "대기 상한 0 → 즉시 BUSY(미노출)");
                        assertTrue(ds.stream().filter(GateDecision::approved).count() >= 1);
                }
        }
}
