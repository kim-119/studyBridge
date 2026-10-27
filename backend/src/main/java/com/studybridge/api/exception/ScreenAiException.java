package com.studybridge.api.exception;

import lombok.Getter;
import org.springframework.http.HttpStatus;

import java.util.Map;

/**
 * 화면공유 AI 분석 API 의 계약 오류. 응답 본문 {status, code, message, retryable[, retryAfterSeconds][, details]}.
 * code 는 웹이 분기에 쓰는 안정 값이고, message 에는 질문·이미지 같은 사용자 입력을 넣지 않는다.
 */
@Getter
public class ScreenAiException extends RuntimeException {

    private final HttpStatus status;
    private final String code;
    private final boolean retryable;
    /** 재시도까지 기다릴 초(429/503). 없으면 null. */
    private final Integer retryAfterSeconds;
    private final Map<String, Object> details;

    public ScreenAiException(HttpStatus status, String code, String message) {
        this(status, code, message, false, null, Map.of());
    }

    public ScreenAiException(HttpStatus status, String code, String message, boolean retryable, Integer retryAfterSeconds) {
        this(status, code, message, retryable, retryAfterSeconds, Map.of());
    }

    public ScreenAiException(HttpStatus status, String code, String message, boolean retryable, Integer retryAfterSeconds,
                             Map<String, Object> details) {
        super(message);
        this.status = status;
        this.code = code;
        this.retryable = retryable;
        this.retryAfterSeconds = retryAfterSeconds;
        this.details = details == null ? Map.of() : details;
    }
}
