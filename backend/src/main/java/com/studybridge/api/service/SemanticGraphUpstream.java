package com.studybridge.api.service;

import com.studybridge.api.dto.MindMapAiDTO.MindMapAiRequest;
import com.studybridge.api.dto.MindMapAiDTO.MindMapAiResponse;

/**
 * AI07 {@code POST /api/ai/mindmap/semantic-graph} 호출 seam(typed).
 * 실제 구현은 {@link FastApiSemanticGraphUpstream}(기존 fastApiWebClient + Bearer AI_SERVER_API_KEY) 이고,
 * 단위 테스트는 이 인터페이스를 stub 해 WebClient 없이 정규화/캐시/상태 매핑을 검증한다.
 */
public interface SemanticGraphUpstream {

    /**
     * @return HTTP 200 본문(status OK|DEGRADED). 4xx/5xx/네트워크 오류는 {@link UpstreamException} 으로 던진다.
     */
    MindMapAiResponse semanticGraph(MindMapAiRequest request) throws UpstreamException;

    /**
     * 업스트림 실패. httpStatus(422/500/504/404/null) + AI07 FAILED 본문(복원 가능하면) + reasonCode.
     *  reasonCode 우선순위: FAILED 본문 degradedReason(EMPTY_ANSWER/NO_VALID_CONCEPTS/GRAPH_VALIDATION_FAILED/INTERNAL_ERROR/TIMEOUT)
     *  → 없으면 전송 계층 코드(UPSTREAM_ROUTE_NOT_FOUND/UPSTREAM_TIMEOUT/UPSTREAM_UNREACHABLE/...).
     */
    class UpstreamException extends Exception {
        private final String reasonCode;
        private final Integer httpStatus;
        private final MindMapAiResponse failedBody;

        public UpstreamException(String reasonCode, Integer httpStatus, MindMapAiResponse failedBody, String message, Throwable cause) {
            super(message, cause);
            this.reasonCode = reasonCode;
            this.httpStatus = httpStatus;
            this.failedBody = failedBody;
        }

        public String getReasonCode() { return reasonCode; }
        public Integer getHttpStatus() { return httpStatus; }
        public MindMapAiResponse getFailedBody() { return failedBody; }
    }
}
