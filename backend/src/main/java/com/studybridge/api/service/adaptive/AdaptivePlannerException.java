package com.studybridge.api.service.adaptive;

import lombok.Getter;
import org.springframework.http.HttpStatus;

import java.util.Map;

/**
 * AI 학습 내비게이터(적응형 학습 엔진) 오류. 컨트롤러가 {error:{code,message,retryable,requestId[,retryAfterSeconds][,details]}} 로 바꾼다.
 * message 는 사용자에게 그대로 보여 줄 수 있는 문장만 담는다(입력값·내부 키 없음).
 */
@Getter
public class AdaptivePlannerException extends RuntimeException {

    private final HttpStatus status;
    private final String code;
    private final boolean retryable;
    private final Integer retryAfterSeconds;
    private final Map<String, Object> details;

    public AdaptivePlannerException(HttpStatus status, String code, String message) {
        this(status, code, message, false, null, null);
    }

    public AdaptivePlannerException(HttpStatus status, String code, String message, boolean retryable, Integer retryAfterSeconds,
                                    Map<String, Object> details) {
        super(message);
        this.status = status;
        this.code = code;
        this.retryable = retryable;
        this.retryAfterSeconds = retryAfterSeconds;
        this.details = details;
    }
}
