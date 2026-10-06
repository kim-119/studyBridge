package com.studybridge.api.exception;

import lombok.Getter;
import org.springframework.http.HttpStatus;

/**
 * 비밀번호 찾기(이메일 인증번호) 흐름의 비즈니스 예외.
 *  - status : 클라이언트에 돌려줄 HTTP 상태코드
 *  - reason : 프론트가 상태(만료/오류/제한/미인증)를 문구가 아닌 코드로 분기할 수 있게 하는 식별자
 *  - retryAfterSeconds : 재전송 제한 등 대기 시간(없으면 null)
 * GlobalExceptionHandler 가 {status, message, reason, retryAfterSeconds} JSON 으로 변환한다.
 */
@Getter
public class PasswordResetException extends RuntimeException {

    public enum Reason {
        INVALID_EMAIL,
        RESEND_COOLDOWN,
        TOO_MANY_REQUESTS,
        CODE_EXPIRED,
        CODE_MISMATCH,
        CODE_ATTEMPTS_EXCEEDED,
        NOT_VERIFIED,
        PASSWORD_POLICY,
        PASSWORD_CONFIRM_MISMATCH,
        PASSWORD_SAME_AS_OLD,
        USER_NOT_FOUND,
        MAIL_NOT_CONFIGURED,
        MAIL_SEND_FAILED,
        STORE_UNAVAILABLE
    }

    private final HttpStatus status;
    private final Reason reason;
    private final Long retryAfterSeconds;

    public PasswordResetException(HttpStatus status, Reason reason, String message) {
        this(status, reason, message, null);
    }

    public PasswordResetException(HttpStatus status, Reason reason, String message, Long retryAfterSeconds) {
        super(message);
        this.status = status;
        this.reason = reason;
        this.retryAfterSeconds = retryAfterSeconds;
    }
}
