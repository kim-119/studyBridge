package com.studybridge.api.exception;

import org.springframework.http.HttpStatus;

import java.util.NoSuchElementException;

/**
 * 자료 퀴즈·공유 접근 오류(코드 포함). 기존 예외 계층(NoSuchElementException → 404, SecurityException → 403,
 * IllegalArgumentException → 400)을 그대로 상속해 기존 호출부·핸들러 동작을 바꾸지 않고, 응답 본문에 code 만 더한다.
 * 코드: MATERIAL_NOT_FOUND · QUIZ_NOT_FOUND · GROUP_NOT_FOUND · FORBIDDEN · INVALID_LIMIT · NOT_SHAREABLE · GROUP_REQUIRED.
 */
public final class QuizAccessException {

    private QuizAccessException() {}

    public interface Coded {
        HttpStatus getStatus();

        String getCode();
    }

    public static class NotFound extends NoSuchElementException implements Coded {
        private final String code;

        public NotFound(String code, String message) {
            super(message);
            this.code = code;
        }

        public HttpStatus getStatus() { return HttpStatus.NOT_FOUND; }

        public String getCode() { return code; }
    }

    public static class Forbidden extends SecurityException implements Coded {
        private final String code;

        public Forbidden(String code, String message) {
            super(message);
            this.code = code;
        }

        public HttpStatus getStatus() { return HttpStatus.FORBIDDEN; }

        public String getCode() { return code; }
    }

    public static class BadRequest extends IllegalArgumentException implements Coded {
        private final String code;

        public BadRequest(String code, String message) {
            super(message);
            this.code = code;
        }

        public HttpStatus getStatus() { return HttpStatus.BAD_REQUEST; }

        public String getCode() { return code; }
    }

    public static RuntimeException of(HttpStatus status, String code, String message) {
        return switch (status) {
            case NOT_FOUND -> new NotFound(code, message);
            case FORBIDDEN -> new Forbidden(code, message);
            case BAD_REQUEST -> new BadRequest(code, message);
            default -> throw new IllegalArgumentException("unsupported status " + status);
        };
    }
}
