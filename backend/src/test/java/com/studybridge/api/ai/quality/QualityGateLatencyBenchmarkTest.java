package com.studybridge.api.ai.quality;

import static org.junit.jupiter.api.Assertions.assertTrue;

import com.studybridge.api.ai.contract.v1.ResponseQualityV1;
import com.studybridge.api.ai.quality.StubEvaluator.Reply;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.http.codec.ServerSentEvent;
import reactor.core.publisher.Flux;

/**
 * 합성 지연 측정(운영 P95 아님): ai07 실캡처(3 에이전트 basic) 1턴을 게이트 OFF/ON 으로 흘려
 * 첫 본문 이벤트까지 시간(TTFB-body)과 턴 전체 시간을 잰다. 평가기 지연 0ms(오버헤드)·600ms(ai07 보고 judge 하한) 두 경우.
 * 결과는 [GATE-LATENCY] 로 출력하고 보고서에 '합성' 으로 표기한다.
 */
class QualityGateLatencyBenchmarkTest {

        static long[] run(QualityStreamGate gate, List<ServerSentEvent<String>> in, int iterations) {
                List<Long> body = new ArrayList<>();
                List<Long> total = new ArrayList<>();
                for (int i = 0; i < iterations; i++) {
                        long t0 = System.nanoTime();
                        long[] first = {-1};
                        Flux<ServerSentEvent<String>> f = gate == null ? Flux.fromIterable(in)
                                        : gate.gate(Flux.fromIterable(in), new QualityStreamGate.Context("req-bench-" + i + "-0000",
                                                        ResponseQualityV1.TaskType.STUDYMATE_BASIC, "질문", ResponseQualityV1.Constraints.empty()));
                        f.doOnNext(e -> {
                                if (first[0] < 0 && ("agent_answer".equals(e.event()) || "agent_error".equals(e.event()))) {
                                        first[0] = System.nanoTime() - t0;
                                }
                        }).blockLast(Duration.ofSeconds(30));
                        total.add(System.nanoTime() - t0);
                        body.add(first[0]);
                }
                Collections.sort(body);
                Collections.sort(total);
                return new long[]{body.get(body.size() / 2), body.get((int) (body.size() * 0.95) - 1), total.get(total.size() / 2),
                                total.get((int) (total.size() * 0.95) - 1)};
        }

        static String ms(long ns) {
                return String.format("%.1fms", ns / 1_000_000.0);
        }

        @Test
        void syntheticGateLatency() throws Exception {
                List<ServerSentEvent<String>> in = QualityStreamGateTest.capture("studymate_multichat_socratic");
                long[] off = run(null, in, 40);
                long[] on0;
                long[] on600;
                try (StubEvaluator stub = new StubEvaluator(r -> Reply.output(r.requestId(), 90, false, "APPROVED"))) {
                        on0 = run(QualityStreamGateTest.gate(stub), in, 40);
                }
                try (StubEvaluator stub = new StubEvaluator(r -> new Reply(200, Reply.output(r.requestId(), 90, false, "APPROVED").body(), 600))) {
                        on600 = run(QualityStreamGateTest.gate(stub), in, 5);
                }
                System.out.printf("[GATE-LATENCY] synthetic socratic(3 answers) OFF body p50=%s p95=%s total p50=%s p95=%s%n",
                                ms(off[0]), ms(off[1]), ms(off[2]), ms(off[3]));
                System.out.printf("[GATE-LATENCY] ON eval=0ms body p50=%s p95=%s total p50=%s p95=%s%n", ms(on0[0]), ms(on0[1]), ms(on0[2]), ms(on0[3]));
                System.out.printf("[GATE-LATENCY] ON eval=600ms body p50=%s p95=%s total p50=%s p95=%s%n", ms(on600[0]), ms(on600[1]),
                                ms(on600[2]), ms(on600[3]));
                assertTrue(on600[0] >= 600_000_000L, "검증 전 본문을 내보내지 않으므로 첫 본문은 최소 평가 지연 이후");
        }
}
