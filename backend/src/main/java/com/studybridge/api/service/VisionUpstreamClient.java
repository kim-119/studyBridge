package com.studybridge.api.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.exception.ScreenAiException;
import io.netty.handler.timeout.ReadTimeoutException;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientRequestException;
import reactor.core.publisher.Mono;

import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.TimeoutException;

/**
 * ai07 멀티모달 Vision API 클라이언트 — POST {PRIMARY}/api/ai/vision/analyze (연동 계약: fastapi/docs/vision/화면공유_비전API_연동계약.md).
 *
 * <ul>
 *   <li>PRIMARY 전용: secondary(EC2 :8000)는 키가 다르고 비전 데몬이 없으므로 failover 하지 않는다.</li>
 *   <li>전용 WebClient(visionWebClient)·전용 타임아웃(ai.vision.timeout-seconds, 기본 260초 ≥ ai07 최악 대기 120+30+추론 90).
 *       공용 FASTAPI_TIMEOUT(180초)·fastApiWebClient(1800초)는 건드리지 않는다.</li>
 *   <li>인증: Authorization: Bearer AI_SERVER_API_KEY(키가 없으면 호출하지 않는다) + 공정성 식별자 X-AI-User-Id/X-AI-Group-Id(JWT·DB 에서 확인한 값).</li>
 *   <li>오류: ai07 의 {error:{code,retryable}} 와 Retry-After 를 사용자용 안정 코드로 바꾼다(ai07 내부 코드는 details.upstreamCode).</li>
 *   <li>개인정보: 요청 본문(이미지·질문)과 답변은 로그에 남기지 않는다.</li>
 * </ul>
 */
@Slf4j
@Component
public class VisionUpstreamClient {

    /** ai07 에 보내는 한 건. image 는 data URI 접두사를 뗀 Base64. */
    public record VisionCall(String requestId, long groupId, String streamId, long sharerUserId, long askerUserId,
                             String question, String imageBase64, String mime) {
        @Override
        public String toString() {
            return "VisionCall[requestId=" + requestId + ", groupId=" + groupId + ", streamId=" + streamId + "]";
        }
    }

    public record VisionResult(String requestId, String answer, String model, Long latencyMs, Long queueWaitMs, Long inferenceMs) {
        @Override
        public String toString() {
            return "VisionResult[requestId=" + requestId + ", model=" + model + ", answerChars=" + (answer == null ? 0 : answer.length()) + "]";
        }
    }

    private static final Set<String> UPSTREAM_CONFIG = Set.of("VISION_UNAUTHORIZED", "VISION_AUTH_NOT_CONFIGURED", "AI_NETWORK_FORBIDDEN");
    private static final Set<String> BUSY = Set.of("VISION_GROUP_LIMIT", "VISION_QUEUE_FULL");
    private static final Set<String> OVERLOADED = Set.of("VISION_QUEUE_TIMEOUT", "VISION_RESOURCE_EXHAUSTED",
            "VISION_BACKEND_UNAVAILABLE", "VISION_SHUTTING_DOWN");
    private static final Set<String> IMAGE_REJECTED = Set.of("VISION_IMAGE_MISSING", "VISION_UNSUPPORTED_MIME", "VISION_INVALID_BASE64",
            "VISION_MIME_MISMATCH", "VISION_IMAGE_CORRUPT", "VISION_IMAGE_DIMENSIONS");
    private static final Set<String> IMAGE_TOO_LARGE = Set.of("VISION_IMAGE_TOO_LARGE", "VISION_BODY_TOO_LARGE");
    private static final Set<String> QUESTION_REJECTED = Set.of("VISION_QUESTION_EMPTY", "VISION_QUESTION_TOO_LONG");

    private final WebClient webClient;
    private final ObjectMapper objectMapper;
    private final String path;
    private final String apiKey;
    private final Duration timeout;

    public VisionUpstreamClient(@Qualifier("visionWebClient") WebClient visionWebClient,
                                ObjectMapper objectMapper,
                                @Value("${ai.vision.path:/api/ai/vision/analyze}") String path,
                                @Value("${ai.server.api-key:${AI_SERVER_API_KEY:}}") String apiKey,
                                @Value("${ai.vision.timeout-seconds:260}") long timeoutSeconds) {
        this.webClient = visionWebClient;
        this.objectMapper = objectMapper;
        this.path = path;
        this.apiKey = apiKey == null ? "" : apiKey.trim();
        this.timeout = Duration.ofSeconds(Math.max(30, timeoutSeconds));
    }

    public boolean configured() {
        return !apiKey.isEmpty();
    }

    public Duration timeout() {
        return timeout;
    }

    public Mono<VisionResult> analyze(VisionCall call) {
        if (!configured()) {
            log.error("[SCREEN-AI] AI_SERVER_API_KEY 미설정 — ai07 Vision 을 호출하지 않는다 requestId={}", call.requestId());
            return Mono.error(new ScreenAiException(HttpStatus.SERVICE_UNAVAILABLE, "SCREEN_AI_NOT_CONFIGURED",
                    "AI 화면 분석 서버 연동이 설정되지 않았습니다. 관리자에게 문의해 주세요."));
        }
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("requestId", call.requestId());
        body.put("groupId", call.groupId());
        if (call.streamId() != null) body.put("streamId", call.streamId());
        body.put("sharerUserId", call.sharerUserId());
        body.put("askerUserId", call.askerUserId());
        body.put("question", call.question());
        body.put("image", call.imageBase64());
        body.put("mime", call.mime());
        return webClient.post()
                .uri(path)
                .contentType(MediaType.APPLICATION_JSON)
                .accept(MediaType.APPLICATION_JSON)
                .header(HttpHeaders.AUTHORIZATION, "Bearer " + apiKey)
                .header("X-AI-User-Id", String.valueOf(call.askerUserId()))
                .header("X-AI-Group-Id", String.valueOf(call.groupId()))
                .header("X-Request-ID", call.requestId())
                .bodyValue(body)
                .exchangeToMono(resp -> resp.bodyToMono(String.class).defaultIfEmpty("")
                        .map(text -> toResult(call.requestId(), resp.statusCode().value(),
                                resp.headers().asHttpHeaders().getFirst(HttpHeaders.RETRY_AFTER), text)))
                .timeout(timeout)
                .onErrorMap(e -> !(e instanceof ScreenAiException), e -> mapTransportError(call.requestId(), e));
    }

    VisionResult toResult(String requestId, int status, String retryAfterHeader, String text) {
        JsonNode json = parse(text);
        if (status >= 200 && status < 300) {
            String answer = json == null ? null : json.path("answer").asText(null);
            if (answer == null || answer.isBlank()) {
                log.warn("[SCREEN-AI] upstream empty answer requestId={} status={}", requestId, status);
                throw new ScreenAiException(HttpStatus.BAD_GATEWAY, "SCREEN_AI_UPSTREAM_ERROR",
                        "AI 분석 결과가 비어 있습니다. 잠시 후 다시 시도해 주세요.", true, null);
            }
            return new VisionResult(json.path("requestId").asText(requestId), answer, json.path("model").asText(null),
                    longOrNull(json, "latencyMs"), longOrNull(json, "queueWaitMs"), longOrNull(json, "inferenceMs"));
        }
        JsonNode err = json == null ? null : json.path("error");
        String code = err != null && err.hasNonNull("code") ? err.get("code").asText() : null;
        boolean upstreamRetryable = err != null && err.path("retryable").asBoolean(false);
        Integer retryAfter = parseRetryAfter(retryAfterHeader);
        log.warn("[SCREEN-AI] upstream error requestId={} status={} code={} retryable={} retryAfter={}",
                requestId, status, code, upstreamRetryable, retryAfter);
        throw mapUpstreamError(status, code, upstreamRetryable, retryAfter, err == null ? null : err.path("message").asText(null));
    }

    static ScreenAiException mapUpstreamError(int status, String code, boolean retryable, Integer retryAfter, String upstreamMessage) {
        Map<String, Object> details = new LinkedHashMap<>();
        details.put("upstreamStatus", status);
        if (code != null) details.put("upstreamCode", code);
        if (code != null && UPSTREAM_CONFIG.contains(code)) {
            return new ScreenAiException(HttpStatus.BAD_GATEWAY, "SCREEN_AI_UPSTREAM_CONFIG",
                    "AI 서버 연동 설정에 문제가 있습니다. 관리자에게 문의해 주세요.", false, null, details);
        }
        if ("VISION_DISABLED".equals(code)) {
            return new ScreenAiException(HttpStatus.SERVICE_UNAVAILABLE, "SCREEN_AI_DISABLED",
                    "AI 화면 분석 기능이 지금은 꺼져 있습니다.", false, null, details);
        }
        if (code != null && BUSY.contains(code)) {
            return new ScreenAiException(HttpStatus.TOO_MANY_REQUESTS, "SCREEN_AI_BUSY",
                    "지금 AI 화면 분석 요청이 많습니다. 잠시 후 다시 시도해 주세요.", true, retryAfter == null ? 5 : retryAfter, details);
        }
        if (code != null && OVERLOADED.contains(code)) {
            return new ScreenAiException(HttpStatus.SERVICE_UNAVAILABLE, "SCREEN_AI_OVERLOADED",
                    "AI 서버가 혼잡해 분석을 시작하지 못했습니다. 잠시 후 다시 시도해 주세요.", true, retryAfter == null ? 10 : retryAfter, details);
        }
        if ("VISION_INFERENCE_TIMEOUT".equals(code)) {
            return new ScreenAiException(HttpStatus.GATEWAY_TIMEOUT, "SCREEN_AI_TIMEOUT",
                    "AI 분석 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.", true, retryAfter, details);
        }
        if ("VISION_MODEL_UNAVAILABLE".equals(code)) {
            return new ScreenAiException(HttpStatus.SERVICE_UNAVAILABLE, "SCREEN_AI_UNAVAILABLE",
                    "AI 화면 분석 모델을 사용할 수 없습니다. 관리자에게 문의해 주세요.", false, null, details);
        }
        if (code != null && IMAGE_TOO_LARGE.contains(code)) {
            return new ScreenAiException(HttpStatus.PAYLOAD_TOO_LARGE, "SCREEN_AI_IMAGE_TOO_LARGE",
                    "화면 이미지가 너무 큽니다.", false, null, details);
        }
        if (code != null && IMAGE_REJECTED.contains(code)) {
            // ai07 메시지에는 입력값이 들어가지 않는다(계약 6절) — 원인 안내에 그대로 쓴다.
            return new ScreenAiException(HttpStatus.UNPROCESSABLE_ENTITY, "SCREEN_AI_IMAGE_INVALID",
                    upstreamMessage != null && !upstreamMessage.isBlank() ? upstreamMessage : "화면 이미지를 분석할 수 없습니다.", false, null, details);
        }
        if (code != null && QUESTION_REJECTED.contains(code)) {
            return new ScreenAiException(HttpStatus.UNPROCESSABLE_ENTITY, "SCREEN_AI_QUESTION_INVALID",
                    upstreamMessage != null && !upstreamMessage.isBlank() ? upstreamMessage : "질문을 확인해 주세요.", false, null, details);
        }
        if (status == 404) {
            // 라우트 부재(ai07 구버전 회귀) — 운영 장애로 본다.
            return new ScreenAiException(HttpStatus.SERVICE_UNAVAILABLE, "SCREEN_AI_UNAVAILABLE",
                    "AI 화면 분석 서버가 응답하지 않습니다. 잠시 후 다시 시도해 주세요.", true, 30, details);
        }
        boolean serverSide = status >= 500 || retryable;
        return new ScreenAiException(HttpStatus.BAD_GATEWAY, "SCREEN_AI_UPSTREAM_ERROR",
                "AI 화면 분석에 실패했습니다. 잠시 후 다시 시도해 주세요.", serverSide, retryAfter, details);
    }

    static ScreenAiException mapTransportError(String requestId, Throwable e) {
        Throwable root = e;
        while (root.getCause() != null && root.getCause() != root) root = root.getCause();
        if (e instanceof TimeoutException || root instanceof TimeoutException || root instanceof ReadTimeoutException) {
            log.warn("[SCREEN-AI] upstream timeout requestId={}", requestId);
            return new ScreenAiException(HttpStatus.GATEWAY_TIMEOUT, "SCREEN_AI_TIMEOUT",
                    "AI 분석 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.", true, null);
        }
        if (e instanceof WebClientRequestException) {
            log.warn("[SCREEN-AI] upstream unreachable requestId={} type={}", requestId, root.getClass().getSimpleName());
            return new ScreenAiException(HttpStatus.SERVICE_UNAVAILABLE, "SCREEN_AI_UNAVAILABLE",
                    "AI 화면 분석 서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.", true, 15);
        }
        log.warn("[SCREEN-AI] upstream failure requestId={} type={}", requestId, e.getClass().getSimpleName());
        return new ScreenAiException(HttpStatus.BAD_GATEWAY, "SCREEN_AI_UPSTREAM_ERROR",
                "AI 화면 분석에 실패했습니다. 잠시 후 다시 시도해 주세요.", true, null);
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

    private static Long longOrNull(JsonNode n, String field) {
        JsonNode v = n.get(field);
        return v != null && v.canConvertToLong() ? v.asLong() : null;
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
}
