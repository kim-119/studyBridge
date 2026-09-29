package com.studybridge.api.ai;

import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientRequestException;
import org.springframework.web.reactive.function.client.WebClientResponseException;

import java.util.List;
import java.util.Locale;
import java.util.concurrent.TimeoutException;

/**
 * 단발성(non-stream) AI 호출용 PRIMARY → SECONDARY 공통 failover executor.
 *
 * <p>멀티에이전트 채팅의 {@code AiMultiChatFailoverService} 와 같은 {@link AiUpstreams}(ordered) 를 소비하지만,
 * SSE 릴레이/circuit/probe 는 갖지 않는다. 매 요청은 항상 primary 부터 순서대로 시도하므로 primary 복구 시
 * 별도 조치 없이 즉시 primary 로 돌아간다. endpoint 별 request/response 해석은 호출 서비스가 책임지고,
 * 이 클래스는 순회·실패 분류·로그·선택 upstream 추적만 한다.</p>
 *
 * <pre>
 *  FAILOVER : connection refused/connect·I/O 실패/timeout, HTTP 404·405, HTTP 5xx, 2xx 후 본문 절단
 *  CONTRACT : HTTP 400/401/403/409/422 및 그 외 4xx (다른 서버로 보내도 해결되지 않는 요청/인증 문제) → 즉시 전파
 *  RESPONSE : HTTP 200 이지만 호출자가 "일시적 실패" 로 판정한 본문(예: quiz success=false + retryable AI_TIMEOUT)
 * </pre>
 * 로그에는 endpoint/upstream 이름/사유(상태코드·예외 클래스)만 남기고 Authorization 헤더·키·본문은 남기지 않는다.
 */
@Slf4j
@Component
public class AiFailoverExecutor {

    public enum FailureKind { FAILOVER, CONTRACT }

    /** 업스트림 1개에 대한 실제 호출. WebClient 의 block() 이 던지는 런타임 예외를 그대로 던진다. */
    @FunctionalInterface
    public interface Call<T> {
        T invoke(AiUpstream upstream);
    }

    /** HTTP 200 본문 기반 재시도 판정. null = 정상 응답(그대로 반환), non-null = 다음 upstream 으로 넘길 사유 코드. */
    @FunctionalInterface
    public interface ResponseRetryPolicy<T> {
        String retryReason(T response);
    }

    /** 선택된 upstream 과 응답. attempts = 시도한 upstream 수(1 = primary 즉시 성공). */
    public record Result<T>(T value, AiUpstream upstream, int attempts) {
        public String upstreamName() { return upstream.name(); }
    }

    private final AiUpstreams upstreams;

    public AiFailoverExecutor(AiUpstreams upstreams) {
        this.upstreams = upstreams;
    }

    /** primary 단독 구성(기존 단일 WebClient 생성자/단위 테스트 호환용). */
    public static AiFailoverExecutor single(WebClient client) {
        return new AiFailoverExecutor(new AiUpstreams(List.of(new AiUpstream("primary", "n/a", client))));
    }

    public AiUpstreams upstreams() {
        return upstreams;
    }

    public <T> Result<T> execute(String endpoint, Call<T> call) {
        return execute(endpoint, call, r -> null);
    }

    /**
     * ordered upstream 을 순회한다.
     * <ul>
     *   <li>호출 성공 + policy 통과 → 즉시 반환(다음 upstream 호출 없음).</li>
     *   <li>CONTRACT 예외 → failover 없이 그대로 던진다.</li>
     *   <li>FAILOVER 예외 / policy 재시도 사유 → 다음 upstream. 마지막 upstream 까지 실패하면
     *       앞선 "구조화 실패 응답" 이 있으면 그것을 반환하고(호출자가 domain 실패로 처리), 없으면 마지막 예외를 던진다.</li>
     * </ul>
     */
    public <T> Result<T> execute(String endpoint, Call<T> call, ResponseRetryPolicy<T> policy) {
        List<AiUpstream> order = upstreams.ordered();
        RuntimeException lastError = null;
        Result<T> lastRetryableResponse = null;
        for (int i = 0; i < order.size(); i++) {
            AiUpstream up = order.get(i);
            boolean hasNext = i + 1 < order.size();
            T value;
            try {
                value = call.invoke(up);
            } catch (RuntimeException e) {
                if (classify(e) == FailureKind.CONTRACT) {
                    // 요청/인증/도메인 검증 실패: 다른 서버로 보내도 같은 결과 → 호출자의 기존 오류 계약으로 전파.
                    log.debug("[AI-FAILOVER] contract failure endpoint={} upstream={} reason={} (no failover)",
                            endpoint, up.name(), describe(e));
                    throw e;
                }
                lastError = e;
                if (hasNext) {
                    logUpstreamFailed(endpoint, up, order.get(i + 1), describe(e), i);
                    continue;
                }
                if (lastRetryableResponse != null) {
                    log.error("[AI-FAILOVER] AI_ALL_UPSTREAMS_FAILED endpoint={} attempts={} lastUpstream={} reason={} → 앞선 구조화 실패 응답 반환",
                            endpoint, i + 1, up.name(), describe(e));
                    return lastRetryableResponse;
                }
                log.error("[AI-FAILOVER] AI_ALL_UPSTREAMS_FAILED endpoint={} attempts={} lastUpstream={} reason={}",
                        endpoint, i + 1, up.name(), describe(e));
                throw e;
            }
            String retryReason = policy.retryReason(value);
            if (retryReason != null && hasNext) {
                lastRetryableResponse = new Result<>(value, up, i + 1);
                logUpstreamFailed(endpoint, up, order.get(i + 1), "response:" + retryReason, i);
                continue;
            }
            if (i > 0) {
                log.info("[AI-FAILOVER] AI_SECONDARY_SELECTED endpoint={} upstream={} attempts={}{}",
                        endpoint, up.name(), i + 1, retryReason != null ? " responseFailure=" + retryReason : "");
            }
            if (retryReason != null) {
                log.error("[AI-FAILOVER] AI_ALL_UPSTREAMS_FAILED endpoint={} attempts={} lastUpstream={} reason=response:{}",
                        endpoint, i + 1, up.name(), retryReason);
            }
            return new Result<>(value, up, i + 1);
        }
        // ordered 는 최소 1개이므로 여기 도달하면 항상 lastError 가 있다.
        throw lastError != null ? lastError : new IllegalStateException("no AI upstream configured");
    }

    private void logUpstreamFailed(String endpoint, AiUpstream failed, AiUpstream next, String reason, int index) {
        String event = index == 0 ? "AI_PRIMARY_FAILED" : "AI_UPSTREAM_FAILED";
        log.warn("[AI-FAILOVER] {} endpoint={} upstream={} reason={} nextUpstream={}",
                event, endpoint, failed.name(), reason, next.name().toUpperCase(Locale.ROOT));
    }

    // ───────────────────────── 분류/설명 ─────────────────────────

    /** AiMultiChatFailoverService.classify 와 같은 정책(단발성 호출용 사본). */
    public static FailureKind classify(Throwable err) {
        if (err instanceof WebClientResponseException wre) {
            int s = wre.getStatusCode().value();
            if (s == 404 || s == 405 || s >= 500) {
                return FailureKind.FAILOVER;
            }
            if (s >= 400) {
                return FailureKind.CONTRACT; // 400/401/403/409/422 + 그 외 4xx
            }
            return FailureKind.FAILOVER; // 2xx 뒤 본문 절단
        }
        // WebClientRequestException(refused/connect/read timeout), TimeoutException,
        // IllegalStateException(block(Duration) timeout), 디코딩 실패 등 → 다른 서버에서 성공할 여지가 있다.
        return FailureKind.FAILOVER;
    }

    /** 로그용 짧은 사유. 상태코드/예외 클래스/경로만 담고 헤더·본문·키는 담지 않는다. */
    public static String describe(Throwable err) {
        if (err == null) {
            return "null";
        }
        if (err instanceof WebClientResponseException wre) {
            String path = wre.getRequest() != null ? " " + wre.getRequest().getMethod() + " " + wre.getRequest().getURI().getPath() : "";
            if (wre.getStatusCode().is2xxSuccessful()) {
                return "body aborted after HTTP 2xx" + path;
            }
            return "HTTP " + wre.getStatusCode().value() + path;
        }
        if (err instanceof WebClientRequestException) {
            Throwable c = err.getCause();
            return "request: " + (c != null ? c.getClass().getSimpleName() + ": " + trim(c.getMessage()) : trim(err.getMessage()));
        }
        if (err instanceof TimeoutException || (err.getCause() instanceof TimeoutException)) {
            return "timeout";
        }
        String m = err.getMessage();
        if (err instanceof IllegalStateException && m != null && m.toLowerCase(Locale.ROOT).contains("timeout")) {
            return "timeout(block)";
        }
        return err.getClass().getSimpleName() + (m != null ? ": " + trim(m) : "");
    }

    private static String trim(String s) {
        if (s == null) return "";
        return s.length() > 160 ? s.substring(0, 160) : s;
    }
}
