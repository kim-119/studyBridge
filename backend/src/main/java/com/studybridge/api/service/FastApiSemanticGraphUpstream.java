package com.studybridge.api.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.ai.AiFailoverExecutor;
import com.studybridge.api.dto.MindMapAiDTO.MindMapAiRequest;
import com.studybridge.api.dto.MindMapAiDTO.MindMapAiResponse;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientResponseException;

import java.time.Duration;

/**
 * AI07 semantic-graph 업스트림 기본 구현. 새 HTTP 클라이언트를 만들지 않고 {@link AiFailoverExecutor} 가 가진
 * PRIMARY(ai07 터널) → SECONDARY(EC2 hot-standby) {@code AiUpstreams} 를 순서대로 사용한다.
 *
 * <ul>
 *   <li>인증: {@code ai.server.api-key}(env AI_SERVER_API_KEY) 가 설정되어 있으면 두 업스트림 모두에
 *       {@code Authorization: Bearer} 로 전달(동일 내부 credential). 키는 서버 설정에서만 읽고 로그/응답/브라우저 어디에도 싣지 않는다.</li>
 *   <li>failover: 연결 실패/timeout/404/5xx 는 SECONDARY 로 넘어간다. 422(EMPTY_ANSWER/NO_VALID_CONCEPTS/schema)·401/403 은
 *       다른 서버로 보내도 같은 결과이므로 failover 하지 않는다. 200 DEGRADED 는 정상 렌더 응답이라 failover 사유가 아니다.</li>
 *   <li>4xx/5xx: {@code retrieve()} 가 던지는 WebClientResponseException 본문을 AI07 FAILED DTO 로 복원해
 *       {@link UpstreamException}(httpStatus + reasonCode) 으로 올린다. 토큰/키워드 폴백 그래프는 만들지 않는다.</li>
 * </ul>
 */
@Slf4j
@Component
public class FastApiSemanticGraphUpstream implements SemanticGraphUpstream {

    public static final String PATH = "/api/ai/mindmap/semantic-graph";

    private final AiFailoverExecutor failover;
    private final ObjectMapper objectMapper;
    private final long timeoutSeconds;
    private final String apiKey;

    @Autowired
    public FastApiSemanticGraphUpstream(AiFailoverExecutor failover,
                                        ObjectMapper objectMapper,
                                        @Value("${ai.mindmap.semantic-timeout-seconds:60}") long timeoutSeconds,
                                        @Value("${ai.server.api-key:${AI_SERVER_API_KEY:}}") String apiKey) {
        this.failover = failover;
        this.objectMapper = objectMapper;
        this.timeoutSeconds = Math.max(5, timeoutSeconds);
        this.apiKey = apiKey == null ? "" : apiKey.trim();
    }

    /** 단일 WebClient(primary 단독) 구성 — 기존 단위 테스트/호환용. */
    FastApiSemanticGraphUpstream(WebClient fastApiWebClient, ObjectMapper objectMapper, long timeoutSeconds, String apiKey) {
        this(AiFailoverExecutor.single(fastApiWebClient), objectMapper, timeoutSeconds, apiKey);
    }

    boolean hasApiKey() { return !apiKey.isEmpty(); }

    @Override
    public MindMapAiResponse semanticGraph(MindMapAiRequest request) throws UpstreamException {
        try {
            AiFailoverExecutor.Result<MindMapAiResponse> result = failover.execute(PATH,
                    up -> callOnce(up.client(), request),
                    // 200 인데 본문이 비면 해당 업스트림의 결함 → 다음 업스트림 시도. 최종 null 은 아래에서 실패로 처리.
                    res -> res == null ? "EMPTY_UPSTREAM_RESPONSE" : null);
            MindMapAiResponse res = result.value();
            if (res == null) {
                throw new UpstreamException("EMPTY_UPSTREAM_RESPONSE", 200, null, "empty body", null);
            }
            return res;
        } catch (UpstreamException e) {
            throw e;
        } catch (WebClientResponseException e) {
            int code = e.getStatusCode().value();
            MindMapAiResponse failed = parseFailedBody(e.getResponseBodyAsString());
            String reason = failed != null && failed.getDegradedReason() != null ? failed.getDegradedReason()
                    : failed != null && failed.getErrorCode() != null ? failed.getErrorCode()
                    : code == 404 ? "UPSTREAM_ROUTE_NOT_FOUND"
                    : code == 422 ? "UPSTREAM_CONTRACT_REJECTED"
                    : code == 504 ? "TIMEOUT"
                    : code == 401 || code == 403 ? "UPSTREAM_AUTH"
                    : code >= 500 ? "INTERNAL_ERROR" : "UPSTREAM_HTTP_" + code;
            log.warn("[MINDMAP_SEMANTIC] upstream http error status={} reason={} apiKey={}", code, reason, hasApiKey() ? "set" : "none");
            throw new UpstreamException(reason, code, failed, "upstream " + code, e);
        } catch (Exception e) {
            String msg = String.valueOf(e.getMessage()).toLowerCase();
            boolean timeout = msg.contains("timeout") || msg.contains("timed out");
            String reason = timeout ? "TIMEOUT"
                    : (msg.contains("connection refused") || msg.contains("connect")) ? "UPSTREAM_UNREACHABLE"
                    : "UPSTREAM_ERROR";
            log.warn("[MINDMAP_SEMANTIC] upstream call failed reason={} error={}", reason, e.getClass().getSimpleName());
            throw new UpstreamException(reason, timeout ? 504 : null, null, e.getMessage(), e);
        }
    }

    /** 업스트림 1개 호출. 4xx/5xx 는 WebClientResponseException, 네트워크/timeout 은 런타임 예외로 그대로 올라간다. */
    private MindMapAiResponse callOnce(WebClient client, MindMapAiRequest request) {
        WebClient.RequestBodySpec spec = client.post().uri(PATH);
        if (hasApiKey()) {
            spec = spec.header(HttpHeaders.AUTHORIZATION, "Bearer " + apiKey);
        }
        return spec.bodyValue(request)
                .retrieve()
                .bodyToMono(MindMapAiResponse.class)
                .block(Duration.ofSeconds(timeoutSeconds));
    }

    /** AI07 FAILED 본문(빈 graph + status/degradedReason) 복원. JSON 이 아니면 null. */
    MindMapAiResponse parseFailedBody(String body) {
        if (body == null || body.isBlank()) return null;
        try {
            MindMapAiResponse r = objectMapper.readValue(body, MindMapAiResponse.class);
            // FastAPI 검증 오류({"detail":[...]}) 는 status 가 없다 → 계약 위반으로 표기.
            if (r.getStatus() == null && r.getDegradedReason() == null && r.getDetail() != null) {
                r.setStatus("FAILED");
                r.setDegradedReason("UPSTREAM_CONTRACT_REJECTED");
            }
            return r;
        } catch (Exception e) {
            return null;
        }
    }
}
