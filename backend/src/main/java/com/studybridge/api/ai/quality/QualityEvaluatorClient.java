package com.studybridge.api.ai.quality;

import com.studybridge.api.ai.contract.v1.ContractJson;
import com.studybridge.api.ai.contract.v1.ResponseQualityV1;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientResponseException;
import reactor.core.publisher.Mono;
import reactor.util.retry.Retry;

import java.time.Duration;
import java.util.concurrent.Semaphore;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;

/**
 * ai07 POST /api/ai/quality/evaluate 호출(response-quality.v1). 내부 Bearer 필수, 브라우저 직접 호출 대상 아님.
 *
 * 자원 보호(16GB GPU 공유 — 평가가 생성 추론을 굶기지 않게):
 *  · bulkhead: 동시 평가 상한(기본 2 = ai07 AI_QUALITY_EVAL_MAX_CONCURRENCY), 대기 상한(queueWaitMs) 초과 시 EVALUATOR_BUSY.
 *  · timeout : 평가 1회 상한(기본 8s) — 초과 시 EVALUATOR_TIMEOUT(노출 금지).
 *  · circuit : 연속 실패 N회(기본 5) → 일정 시간(기본 30s) 호출 없이 EVALUATOR_CIRCUIT_OPEN, 이후 1건으로 반개방 시험.
 * 어떤 실패도 "승인"으로 바뀌지 않는다(fail-closed). 로그에는 요청/답변/근거 원문을 남기지 않는다.
 */
@Slf4j
@Component
public class QualityEvaluatorClient {

    public record Result(ResponseQualityV1.Output output, String errorCode, long latencyMs) {
        public static Result error(String code, long latencyMs) {
            return new Result(null, code, latencyMs);
        }
    }

    /** ai07 limited_route_class(256 * 1024) 와 같은 바이트 상한. */
    static final int MAX_REQUEST_BYTES = 256 * 1024;

    private final WebClient webClient;
    private final AiQualityGateSettings settings;
    private final String apiKey;
    private final Semaphore permits;
    private final AtomicInteger consecutiveFailures = new AtomicInteger();
    private final AtomicLong openUntil = new AtomicLong();
    private final java.util.concurrent.atomic.AtomicBoolean halfOpenInFlight = new java.util.concurrent.atomic.AtomicBoolean();

    @Autowired
    public QualityEvaluatorClient(@Qualifier("fastApiWebClient") WebClient webClient, AiQualityGateSettings settings,
                                  @Value("${ai.server.api-key:}") String apiKey) {
        this.webClient = webClient;
        this.settings = settings;
        this.apiKey = apiKey == null ? "" : apiKey.strip();
        this.permits = new Semaphore(settings.maxConcurrency());
    }

    public Mono<Result> evaluate(ResponseQualityV1.Input input) {
        // 모든 판단(서킷·bulkhead)은 구독 시점에 한다(조립 시점 판단은 구독되지 않은 Mono 가 반개방 슬롯을 영구 점유).
        return Mono.defer(() -> evaluateNow(input));
    }

    /** 평가기가 요청을 받을 수 있는 상태인가(서킷 열림이면 false) — 생성 전에 확인해 불필요한 재생성을 막는다. */
    public boolean acceptingRequests() {
        long until = openUntil.get();
        return until == 0 || System.currentTimeMillis() >= until && !halfOpenInFlight.get();
    }

    private Mono<Result> evaluateNow(ResponseQualityV1.Input input) {
        long started = System.currentTimeMillis();
        ContractJson.Violations v = ResponseQualityV1.validate(input);
        if (!v.ok()) {
            // 우리가 만든 입력이 계약 위반이면 보내지 않는다(평가기 쪽 422 와 같은 의미).
            log.warn("[QUALITY-GATE] 입력 계약 위반 requestId={} violations={}", input == null ? null : input.requestId(), v.list());
            return Mono.just(Result.error("EVALUATOR_INPUT_CONTRACT_INVALID", 0));
        }
        if (apiKey.length() < 24) {
            return Mono.just(Result.error("EVALUATOR_AUTH_NOT_CONFIGURED", 0));
        }
        boolean trial;
        long until = openUntil.get();
        if (until != 0 && System.currentTimeMillis() < until) {
            return Mono.just(Result.error("EVALUATOR_CIRCUIT_OPEN", 0));
        }
        if (until != 0) {
            // 반개방: 한 건만 시험. 시험이 어떤 식으로 끝나든(성공·실패·취소·빈 응답) doFinally 에서 슬롯을 돌려준다.
            if (!halfOpenInFlight.compareAndSet(false, true)) {
                return Mono.just(Result.error("EVALUATOR_CIRCUIT_OPEN", 0));
            }
            trial = true;
        } else {
            trial = false;
        }
        byte[] body;
        try {
            body = ContractJson.STRICT.writeValueAsBytes(input);
        } catch (Exception e) {
            if (trial) {
                halfOpenInFlight.set(false);
            }
            return Mono.just(Result.error("EVALUATOR_INPUT_CONTRACT_INVALID", 0));
        }
        // ai07 평가 라우트 본문 상한(256KiB, 바이트). 계약 상한(6만 자)은 문자 수라 한글이면 넘을 수 있다 → 보내기 전에 막는다(413 왕복·슬롯 낭비 방지).
        if (body.length > MAX_REQUEST_BYTES) {
            if (trial) {
                halfOpenInFlight.set(false);
            }
            return Mono.just(Result.error("EVALUATOR_INPUT_TOO_LARGE", 0));
        }
        Mono<Result> call = webClient.post()
                .uri(settings.evaluatePath())
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + apiKey)
                .header("X-Request-ID", input.requestId())
                .header("X-Caller-Id", "spring-quality-gate")
                .contentType(MediaType.APPLICATION_JSON)
                .bodyValue(body)
                .retrieve()
                .bodyToMono(byte[].class)
                .defaultIfEmpty(new byte[0]) // 200/204 빈 본문도 결과를 남긴다(→ 출력 계약 위반 = 미노출)
                .timeout(Duration.ofMillis(settings.evaluateTimeoutMs()))
                .map(bytes -> parse(bytes, input.requestId(), started))
                .onErrorResume(e -> Mono.just(Result.error(classify(e), System.currentTimeMillis() - started)));
        long waitSteps = Math.max(0, settings.queueWaitMs() / 50);
        return Mono.defer(() -> permits.tryAcquire()
                        ? call.doFinally(sig -> permits.release())
                        : Mono.<Result>error(new BusyException()))
                .retryWhen(Retry.fixedDelay(waitSteps, Duration.ofMillis(50)).filter(BusyException.class::isInstance))
                .onErrorResume(e -> Mono.just(Result.error("EVALUATOR_BUSY", System.currentTimeMillis() - started)))
                .doOnNext(this::record)
                .doFinally(sig -> {
                    if (trial) {
                        halfOpenInFlight.set(false);
                    }
                });
    }

    private Result parse(byte[] bytes, String requestId, long started) {
        long latency = System.currentTimeMillis() - started;
        try {
            ResponseQualityV1.Output o = ContractJson.STRICT.readValue(bytes, ResponseQualityV1.Output.class);
            ContractJson.Violations v = ResponseQualityV1.validate(o);
            if (!v.ok()) {
                log.warn("[QUALITY-GATE] 출력 계약 위반 requestId={} violations={}", requestId, v.list());
                return Result.error("EVALUATOR_OUTPUT_CONTRACT_INVALID", latency);
            }
            if (!requestId.equals(o.requestId())) {
                return Result.error("EVALUATOR_REQUEST_MISMATCH", latency);
            }
            return new Result(o, null, latency);
        } catch (Exception e) {
            // 200 + {"success":false,"errorCode":...}(FEATURE_DISABLED 등) 도 출력 계약이 아니므로 여기서 거절된다.
            return Result.error("EVALUATOR_OUTPUT_CONTRACT_INVALID", latency);
        }
    }

    private static String classify(Throwable e) {
        if (e instanceof TimeoutException || (e.getCause() instanceof TimeoutException)) {
            return "EVALUATOR_TIMEOUT";
        }
        if (e instanceof WebClientResponseException w) {
            int s = w.getStatusCode().value();
            if (s == 401 || s == 403) {
                return "EVALUATOR_AUTH_FAILED";
            }
            if (s == 404) {
                return "EVALUATOR_ROUTE_NOT_DEPLOYED";
            }
            if (s == 409) {
                return "EVALUATOR_IDEMPOTENCY_CONFLICT";
            }
            if (s == 413 || s == 422) {
                return "EVALUATOR_INPUT_REJECTED";
            }
            if (s == 429) {
                return "EVALUATOR_BUSY";
            }
            if (s == 503) {
                return "EVALUATOR_UNAVAILABLE";
            }
            return "EVALUATOR_HTTP_" + s;
        }
        return "EVALUATOR_UNREACHABLE";
    }

    // ── circuit breaker ────────────────────────────────────────────────────────────
    private void record(Result r) {
        String c = r.errorCode();
        if (c != null && (c.equals("EVALUATOR_BUSY") || c.equals("EVALUATOR_CIRCUIT_OPEN"))) {
            return; // 중립: 로컬 대기 초과/429 는 평가기 건강 신호가 아니다(서킷을 닫거나 열지 않는다)
        }
        boolean infraFailure = c != null && (c.equals("EVALUATOR_TIMEOUT") || c.equals("EVALUATOR_UNREACHABLE")
                || c.equals("EVALUATOR_UNAVAILABLE") || c.equals("EVALUATOR_ROUTE_NOT_DEPLOYED") || c.startsWith("EVALUATOR_HTTP_5"));
        if (infraFailure) {
            int n = consecutiveFailures.incrementAndGet();
            if (n >= settings.circuitFailureThreshold()) {
                openUntil.set(System.currentTimeMillis() + settings.circuitOpenMs());
                log.warn("[QUALITY-GATE] 평가기 서킷 오픈 {}ms (연속 실패 {}회, 마지막 {})", settings.circuitOpenMs(), n, c);
            }
        } else {
            // 평가기가 응답했다(승인/거절/계약 오류 무관) → 인프라는 정상: 서킷 닫음
            consecutiveFailures.set(0);
            openUntil.set(0);
        }
    }

    private static final class BusyException extends RuntimeException {
        BusyException() {
            super("EVALUATOR_BUSY", null, false, false);
        }
    }
}
