package com.studybridge.api.exception;

import org.springframework.http.HttpStatus;

/**
 * AI 업스트림(AI07 FastAPI) 호출이 "스트림을 열기 전"에 실패했을 때 컨트롤러로 전파하는 예외.
 *
 * <p>SSE 응답이 아직 커밋되지 않았으면(이벤트/주석 0건) Spring 은 정상 SSE(200 + error 이벤트)로 위장하지 않고
 * 상태코드 + JSON 으로 응답한다(§10 pre-stream error). 이미 이벤트가 나간 뒤의 실패는 error/done 이벤트로 알린다.</p>
 *
 * <ul>
 *   <li>CONTRACT(422/400/409): 업스트림 상태코드를 그대로 보존한다(요청 검증 실패 — 예: TARGET_AGENT_NOT_FOUND, UNSUPPORTED_MODE).</li>
 *   <li>업스트림 401/403: 브라우저 세션 문제가 아니므로 502(AI_UPSTREAM_AUTH)로 매핑한다(401 로 내리면 프론트가 토큰 갱신을 시도한다).</li>
 *   <li>UNAVAILABLE(모든 업스트림 소진): 503 + retryable=true.</li>
 * </ul>
 * 메시지는 중립 문구만 담고 URL/모델/스택은 담지 않는다.
 */
public class AiUpstreamException extends RuntimeException {

    private final HttpStatus status;
    private final String code;
    private final String requestId;
    private final boolean retryable;
    private final Integer upstreamStatus;
    private final String upstreamCode;

    public AiUpstreamException(HttpStatus status, String code, String message, String requestId,
                               boolean retryable, Integer upstreamStatus, String upstreamCode) {
        super(message);
        this.status = status;
        this.code = code;
        this.requestId = requestId;
        this.retryable = retryable;
        this.upstreamStatus = upstreamStatus;
        this.upstreamCode = upstreamCode;
    }

    /** 업스트림 4xx(contract) → 상태 보존/매핑. */
    public static AiUpstreamException contract(int upstreamStatus, String upstreamCode, String upstreamMessage, String requestId) {
        HttpStatus mapped;
        String code;
        String message;
        switch (upstreamStatus) {
            case 422 -> { mapped = HttpStatus.UNPROCESSABLE_ENTITY; code = "AI_REQUEST_REJECTED"; message = neutral(upstreamCode, upstreamMessage, "AI 서버가 요청을 처리할 수 없습니다. 입력 값을 확인해 주세요."); }
            case 400 -> { mapped = HttpStatus.BAD_REQUEST; code = "AI_REQUEST_REJECTED"; message = neutral(upstreamCode, upstreamMessage, "AI 서버가 요청을 거절했습니다. 입력 값을 확인해 주세요."); }
            case 409 -> { mapped = HttpStatus.CONFLICT; code = "AI_REQUEST_CONFLICT"; message = neutral(upstreamCode, upstreamMessage, "AI 서버에서 요청이 충돌했습니다. 잠시 후 다시 시도해 주세요."); }
            case 401, 403 -> { mapped = HttpStatus.BAD_GATEWAY; code = "AI_UPSTREAM_AUTH"; message = "AI 서버 인증 설정 오류가 발생했습니다. 관리자에게 문의해 주세요."; }
            default -> { mapped = HttpStatus.BAD_GATEWAY; code = "AI_UPSTREAM_REJECTED"; message = "AI 서버가 요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요."; }
        }
        return new AiUpstreamException(mapped, code, message, requestId, false, upstreamStatus, upstreamCode);
    }

    public static AiUpstreamException unavailable(String requestId, Integer lastUpstreamStatus) {
        return new AiUpstreamException(HttpStatus.SERVICE_UNAVAILABLE, "AI_UPSTREAM_UNAVAILABLE",
                "AI 서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.", requestId, true, lastUpstreamStatus, null);
    }

    /** 업스트림 message 는 사용자 언어의 검증 문구(422 detail.message)만 통과시킨다. 내부 정보 패턴이 있으면 기본 문구. */
    private static String neutral(String upstreamCode, String upstreamMessage, String fallback) {
        if (upstreamMessage == null || upstreamMessage.isBlank()) {
            return fallback;
        }
        String m = upstreamMessage.trim();
        String low = m.toLowerCase();
        if (m.length() > 200 || low.contains("traceback") || low.contains("http://") || low.contains("https://")
                || low.contains("exception") || low.contains("ollama") || low.contains("qwen") || low.contains("num_ctx")
                || low.contains("localhost") || low.contains("127.0.0.1")) {
            return fallback;
        }
        return m;
    }

    public HttpStatus getStatus() { return status; }
    public String getCode() { return code; }
    public String getRequestId() { return requestId; }
    public boolean isRetryable() { return retryable; }
    public Integer getUpstreamStatus() { return upstreamStatus; }
    public String getUpstreamCode() { return upstreamCode; }
}
