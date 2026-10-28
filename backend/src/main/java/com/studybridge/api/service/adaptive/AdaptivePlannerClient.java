package com.studybridge.api.service.adaptive;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.netty.handler.timeout.ReadTimeoutException;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientRequestException;

import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.TimeoutException;

/**
 * ai07 적응형 학습 엔진 클라이언트 — POST {PRIMARY}/api/ai/planner/adaptive
 * (계약: fastapi/docs/planner/적응형_학습엔진_API_연동계약.md, adaptive-planner.v1).
 *
 * <ul>
 *   <li>PRIMARY 전용. secondary(EC2 :8000)는 키가 달라 failover 하지 않는다(계약 14절).</li>
 *   <li>인증: 다른 ai07 호출과 같은 내부 키(ai.server.api-key = AI_SERVER_API_KEY)를 Bearer 로 붙인다. 키가 없으면 호출하지 않는다.</li>
 *   <li>시간: 전용 WebClient(adaptivePlannerWebClient)·전용 응답 상한(ai.planner.adaptive.timeout-seconds, 기본 45초).
 *       ai07 요청 예산 30초(LLM 이 늦으면 규칙 결과로 200)보다 길고, 다른 AI 기능의 타임아웃은 건드리지 않는다.</li>
 *   <li>재시도: 429/503 중 retryable=true 이고 Retry-After 가 retry-max-wait-seconds 이하일 때만 1회.
 *       응답 전에 닫힌 연결(keep-alive 경합)은 ai07 이 DB 를 쓰지 않는 계산 API 라 즉시 1회 재시도한다.
 *       인증·무결성 4xx 는 재시도하거나 규칙 추천으로 우회하지 않고 그대로 오류로 올린다.</li>
 *   <li>개인정보: 요청·응답 본문은 로그에 남기지 않는다(requestId·상태·코드·지연만).</li>
 * </ul>
 */
@Slf4j
@Component
public class AdaptivePlannerClient {

    public static final String CONTRACT_VERSION = "adaptive-planner.v1";

    /** ai07 서버 요청 예산(ADAPTIVE_REQUEST_TIMEOUT_S). 재시도는 남은 시간이 이 예산 + 대기보다 클 때만 한다. */
    static final long AI_REQUEST_BUDGET_SECONDS = 30L;

    private static final Set<String> UPSTREAM_CONFIG = Set.of("ADAPTIVE_UNAUTHORIZED", "ADAPTIVE_AUTH_NOT_CONFIGURED", "AI_NETWORK_FORBIDDEN");

    /** ai07 응답 원문(상태·Retry-After·본문). */
    record Raw(int status, Integer retryAfter, String body) {}

    private final WebClient webClient;
    private final ObjectMapper objectMapper;
    private final String path;
    private final String apiKey;
    private final Duration timeout;
    private final int retryMaxWaitSeconds;

    @Autowired
    public AdaptivePlannerClient(@Qualifier("adaptivePlannerWebClient") WebClient webClient,
                                 ObjectMapper objectMapper,
                                 @Value("${ai.planner.adaptive.path:/api/ai/planner/adaptive}") String path,
                                 @Value("${ai.server.api-key:${AI_SERVER_API_KEY:}}") String apiKey,
                                 @Value("${ai.planner.adaptive.timeout-seconds:45}") long timeoutSeconds,
                                 @Value("${ai.planner.adaptive.retry-max-wait-seconds:3}") int retryMaxWaitSeconds) {
        this(webClient, objectMapper, path, apiKey, Duration.ofSeconds(Math.max(40, timeoutSeconds)), retryMaxWaitSeconds);
    }

    /** 테스트용: 응답 상한을 직접 준다(운영 생성자는 40초 미만을 허용하지 않는다). */
    AdaptivePlannerClient(WebClient webClient, ObjectMapper objectMapper, String path, String apiKey, Duration timeout, int retryMaxWaitSeconds) {
        this.webClient = webClient;
        this.objectMapper = objectMapper;
        this.path = path;
        this.apiKey = apiKey == null ? "" : apiKey.trim();
        this.timeout = timeout;
        this.retryMaxWaitSeconds = Math.max(0, Math.min(10, retryMaxWaitSeconds));
    }

    public boolean configured() {
        return !apiKey.isEmpty();
    }

    public Duration timeout() {
        return timeout;
    }

    /** 성공(2xx + 계약 버전 일치) 응답 JSON. 그 밖은 {@link AdaptivePlannerException}. */
    public JsonNode recommend(Map<String, Object> body, String requestId) {
        if (!configured()) {
            log.error("[ADAPTIVE] AI_SERVER_API_KEY 미설정 — ai07 을 호출하지 않는다 requestId={}", requestId);
            throw new AdaptivePlannerException(HttpStatus.SERVICE_UNAVAILABLE, "ADAPTIVE_NOT_CONFIGURED",
                    "AI 학습 내비게이터 서버 연동이 설정되지 않았습니다. 관리자에게 문의해 주세요.");
        }
        long started = System.nanoTime();
        boolean retried = false;
        while (true) {
            Raw raw;
            try {
                raw = send(body, requestId, retried ? remaining(started) : timeout);
            } catch (AdaptivePlannerException e) {
                throw e;
            } catch (Exception e) {
                if (!retried && isClosedBeforeResponse(e) && remaining(started).toMillis() > 5_000) {
                    retried = true;
                    log.info("[ADAPTIVE] connection closed before response → 1회 재시도 requestId={}", requestId);
                    continue;
                }
                throw mapTransportError(requestId, e);
            }
            long elapsedMs = (System.nanoTime() - started) / 1_000_000;
            if (raw.status() >= 200 && raw.status() < 300) {
                JsonNode json = parse(raw.body());
                if (json == null || !json.path("contractVersion").asText("").startsWith(CONTRACT_VERSION)) {
                    log.warn("[ADAPTIVE] invalid response requestId={} status={} elapsedMs={}", requestId, raw.status(), elapsedMs);
                    throw new AdaptivePlannerException(HttpStatus.BAD_GATEWAY, "ADAPTIVE_INVALID_RESPONSE",
                            "AI 학습 내비게이터 응답을 해석하지 못했습니다. 잠시 후 다시 시도해 주세요.", true, null, null);
                }
                log.info("[ADAPTIVE] ok requestId={} status={} source={} elapsedMs={} retried={}", requestId,
                        json.path("status").asText(null), json.path("source").asText(null), elapsedMs, retried);
                return json;
            }
            JsonNode err = errorNode(raw.body());
            String code = err == null ? null : textOrNull(err, "code");
            boolean upstreamRetryable = err != null && err.path("retryable").asBoolean(false);
            log.warn("[ADAPTIVE] upstream error requestId={} status={} code={} retryable={} retryAfter={} field={} elapsedMs={}",
                    requestId, raw.status(), code, upstreamRetryable, raw.retryAfter(), err == null ? null : textOrNull(err, "field"), elapsedMs);
            if (!retried && shouldRetry(raw.status(), upstreamRetryable, raw.retryAfter(), started)) {
                retried = true;
                sleepSeconds(raw.retryAfter() == null ? 1 : raw.retryAfter());
                continue;
            }
            throw mapUpstreamError(raw.status(), code, upstreamRetryable, raw.retryAfter(), err == null ? null : textOrNull(err, "field"));
        }
    }

    private Raw send(Map<String, Object> body, String requestId, Duration limit) {
        return webClient.post()
                .uri(path)
                .contentType(MediaType.APPLICATION_JSON)
                .accept(MediaType.APPLICATION_JSON)
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + apiKey)
                .header("X-Request-ID", requestId)
                .bodyValue(body)
                .exchangeToMono(resp -> resp.bodyToMono(String.class).defaultIfEmpty("")
                        .map(text -> new Raw(resp.statusCode().value(),
                                parseRetryAfter(resp.headers().asHttpHeaders().getFirst(HttpHeaders.RETRY_AFTER)), text)))
                .timeout(limit.isNegative() || limit.isZero() ? Duration.ofSeconds(1) : limit)
                .block();
    }

    /** 429/503 + retryable + Retry-After ≤ 상한 + 남은 예산이 (대기 + ai07 예산 30초)보다 클 때만. */
    boolean shouldRetry(int status, boolean retryable, Integer retryAfter, long startedNanos) {
        if (!retryable || (status != 429 && status != 503)) return false;
        int wait = retryAfter == null ? 1 : retryAfter;
        if (wait > retryMaxWaitSeconds) return false;
        return remaining(startedNanos).toSeconds() > wait + AI_REQUEST_BUDGET_SECONDS;
    }

    private Duration remaining(long startedNanos) {
        return timeout.minusNanos(System.nanoTime() - startedNanos);
    }

    static AdaptivePlannerException mapUpstreamError(int status, String code, boolean retryable, Integer retryAfter, String field) {
        Map<String, Object> details = new LinkedHashMap<>();
        details.put("upstreamStatus", status);
        if (code != null) details.put("upstreamCode", code);
        if (field != null) details.put("field", field);
        if (code != null && UPSTREAM_CONFIG.contains(code)) {
            return new AdaptivePlannerException(HttpStatus.BAD_GATEWAY, "ADAPTIVE_UPSTREAM_CONFIG",
                    "AI 서버 연동 설정에 문제가 있습니다. 관리자에게 문의해 주세요.", false, null, details);
        }
        if ("ADAPTIVE_DISABLED".equals(code)) {
            return new AdaptivePlannerException(HttpStatus.SERVICE_UNAVAILABLE, "ADAPTIVE_DISABLED",
                    "AI 학습 내비게이터가 지금은 꺼져 있습니다.", false, null, details);
        }
        if (status == 429) {
            return new AdaptivePlannerException(HttpStatus.TOO_MANY_REQUESTS, "ADAPTIVE_BUSY",
                    "요청이 많아 잠시 후 다시 시도해 주세요.", true, retryAfter == null ? 2 : retryAfter, details);
        }
        if (status == 503 && retryable) {
            return new AdaptivePlannerException(HttpStatus.SERVICE_UNAVAILABLE, "ADAPTIVE_OVERLOADED",
                    "AI 서버가 혼잡합니다. 잠시 후 다시 시도해 주세요.", true, retryAfter == null ? 5 : retryAfter, details);
        }
        if (status == 504) {
            return new AdaptivePlannerException(HttpStatus.GATEWAY_TIMEOUT, "ADAPTIVE_TIMEOUT",
                    "AI 응답 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.", true, retryAfter, details);
        }
        if (status == 404) {
            // 라우트 부재(ai07 구버전 회귀) — 운영 장애로 본다.
            return new AdaptivePlannerException(HttpStatus.SERVICE_UNAVAILABLE, "ADAPTIVE_UNAVAILABLE",
                    "AI 학습 내비게이터 서버가 응답하지 않습니다. 잠시 후 다시 시도해 주세요.", true, 30, details);
        }
        if (status >= 400 && status < 500) {
            // 형식·무결성 거절은 Spring 매핑 결함이다 — 규칙 추천으로 우회하지 않고 그대로 알린다.
            return new AdaptivePlannerException(HttpStatus.BAD_GATEWAY, "ADAPTIVE_REQUEST_REJECTED",
                    "학습 데이터를 AI 엔진이 처리하지 못했습니다. 문제가 계속되면 관리자에게 알려 주세요.", false, null, details);
        }
        return new AdaptivePlannerException(HttpStatus.BAD_GATEWAY, "ADAPTIVE_UPSTREAM_ERROR",
                "AI 학습 내비게이터 요청에 실패했습니다. 잠시 후 다시 시도해 주세요.", true, retryAfter, details);
    }

    static AdaptivePlannerException mapTransportError(String requestId, Throwable e) {
        Throwable root = rootCause(e);
        if (e instanceof TimeoutException || root instanceof TimeoutException || root instanceof ReadTimeoutException) {
            log.warn("[ADAPTIVE] upstream timeout requestId={}", requestId);
            return new AdaptivePlannerException(HttpStatus.GATEWAY_TIMEOUT, "ADAPTIVE_TIMEOUT",
                    "AI 응답 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.", true, null, null);
        }
        String rootType = root.getClass().getSimpleName();
        if ("PoolAcquirePendingLimitException".equals(rootType) || "PoolAcquireTimeoutException".equals(rootType)) {
            log.warn("[ADAPTIVE] connection pool saturated requestId={} type={}", requestId, rootType);
            return new AdaptivePlannerException(HttpStatus.TOO_MANY_REQUESTS, "ADAPTIVE_BUSY",
                    "요청이 많아 잠시 후 다시 시도해 주세요.", true, 3, null);
        }
        if (e instanceof WebClientRequestException || isClosedBeforeResponse(e)) {
            log.warn("[ADAPTIVE] upstream unreachable requestId={} type={}", requestId, rootType);
            return new AdaptivePlannerException(HttpStatus.SERVICE_UNAVAILABLE, "ADAPTIVE_UNAVAILABLE",
                    "AI 학습 내비게이터 서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.", true, 15, null);
        }
        log.warn("[ADAPTIVE] upstream failure requestId={} type={}", requestId, e.getClass().getSimpleName());
        return new AdaptivePlannerException(HttpStatus.BAD_GATEWAY, "ADAPTIVE_UPSTREAM_ERROR",
                "AI 학습 내비게이터 요청에 실패했습니다. 잠시 후 다시 시도해 주세요.", true, null, null);
    }

    /** reactor-netty PrematureCloseException("Connection prematurely closed BEFORE response") — 요청이 처리되기 전 닫힌 연결. */
    static boolean isClosedBeforeResponse(Throwable e) {
        for (Throwable t = e; t != null; t = t.getCause() == t ? null : t.getCause()) {
            if ("PrematureCloseException".equals(t.getClass().getSimpleName())) {
                String m = t.getMessage();
                return m == null || m.contains("BEFORE response");
            }
        }
        return false;
    }

    private static Throwable rootCause(Throwable e) {
        Throwable root = e;
        while (root.getCause() != null && root.getCause() != root) root = root.getCause();
        return root;
    }

    private JsonNode parse(String text) {
        if (text == null || text.isBlank()) return null;
        try {
            JsonNode n = objectMapper.readTree(text);
            return n != null && n.isObject() ? n : null;
        } catch (Exception e) {
            return null;
        }
    }

    private JsonNode errorNode(String text) {
        JsonNode json = parse(text);
        if (json == null) return null;
        JsonNode err = json.get("error");
        return err != null && err.isObject() ? err : null;
    }

    private static String textOrNull(JsonNode n, String field) {
        JsonNode v = n.get(field);
        return v == null || v.isNull() ? null : v.asText();
    }

    static Integer parseRetryAfter(String header) {
        if (header == null || header.isBlank()) return null;
        try {
            int v = Integer.parseInt(header.trim());
            return v >= 0 ? Math.min(v, 300) : null;
        } catch (NumberFormatException e) {
            return null;
        }
    }

    private static void sleepSeconds(int seconds) {
        try {
            Thread.sleep(Math.max(0, seconds) * 1000L);
        } catch (InterruptedException ie) {
            Thread.currentThread().interrupt();
            throw new AdaptivePlannerException(HttpStatus.SERVICE_UNAVAILABLE, "ADAPTIVE_UNAVAILABLE",
                    "요청이 중단되었습니다. 다시 시도해 주세요.", true, 1, null);
        }
    }
}
