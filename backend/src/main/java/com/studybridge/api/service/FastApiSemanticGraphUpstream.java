package com.studybridge.api.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.dto.MindMapAiDTO.MindMapAiRequest;
import com.studybridge.api.dto.MindMapAiDTO.MindMapAiResponse;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientResponseException;

import java.time.Duration;

/**
 * AI07 semantic-graph 업스트림 기본 구현. 기존 {@code fastApiWebClient}(PRIMARY 업스트림) 를 재사용하며
 * 새 HTTP 클라이언트를 만들지 않는다.
 *
 * <ul>
 *   <li>인증: {@code ai.server.api-key}(env AI_SERVER_API_KEY) 가 설정되어 있으면 {@code Authorization: Bearer} 로 전달.
 *       키는 서버 설정에서만 읽고 로그/응답/브라우저 어디에도 싣지 않는다.</li>
 *   <li>4xx/5xx: {@code retrieve()} 가 던지는 WebClientResponseException 본문을 AI07 FAILED DTO 로 복원해
 *       {@link UpstreamException}(httpStatus + reasonCode) 으로 올린다. 토큰/키워드 폴백 그래프는 만들지 않는다.</li>
 * </ul>
 */
@Slf4j
@Component
public class FastApiSemanticGraphUpstream implements SemanticGraphUpstream {

    public static final String PATH = "/api/ai/mindmap/semantic-graph";

    private final WebClient fastApiWebClient;
    private final ObjectMapper objectMapper;
    private final long timeoutSeconds;
    private final String apiKey;

    public FastApiSemanticGraphUpstream(WebClient fastApiWebClient,
                                        ObjectMapper objectMapper,
                                        @Value("${ai.mindmap.semantic-timeout-seconds:60}") long timeoutSeconds,
                                        @Value("${ai.server.api-key:${AI_SERVER_API_KEY:}}") String apiKey) {
        this.fastApiWebClient = fastApiWebClient;
        this.objectMapper = objectMapper;
        this.timeoutSeconds = Math.max(5, timeoutSeconds);
        this.apiKey = apiKey == null ? "" : apiKey.trim();
    }

    boolean hasApiKey() { return !apiKey.isEmpty(); }

    @Override
    public MindMapAiResponse semanticGraph(MindMapAiRequest request) throws UpstreamException {
        try {
            WebClient.RequestBodySpec spec = fastApiWebClient.post().uri(PATH);
            if (hasApiKey()) {
                spec = spec.header(HttpHeaders.AUTHORIZATION, "Bearer " + apiKey);
            }
            MindMapAiResponse res = spec.bodyValue(request)
                    .retrieve()
                    .bodyToMono(MindMapAiResponse.class)
                    .block(Duration.ofSeconds(timeoutSeconds));
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
