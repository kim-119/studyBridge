package com.studybridge.api.exception;

import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.NoSuchElementException;

/**
 * 서비스 계층에서 던지는 비즈니스 예외를 적절한 HTTP 상태코드 + 메시지 본문으로 변환한다.
 * 매핑되지 않은 예외는 그대로 전파되어 기본 500 처리된다.
 *
 * <p>Content-Type 을 application/json 으로 명시하는 이유: SSE 컨트롤러({@code produces=text/event-stream}, 요청 Accept 도
 * text/event-stream)에서 403/404/400 이 나면 Spring 이 이 핸들러의 Map 본문을 text/event-stream 으로 쓸 수 없어
 * "Failure in @ExceptionHandler" 로 실패하고 빈 본문 500 으로 새어 나갔다(방 소유자 아님/없는 방/잘못된 targetAgentId 가 모두 500).
 * ResponseEntity 에 Content-Type 이 미리 지정돼 있으면 Accept 협상을 건너뛰고 그대로 쓰므로 상태코드가 보존된다.</p>
 */
@Slf4j
@RestControllerAdvice
public class GlobalExceptionHandler {

    private ResponseEntity<Map<String, Object>> body(HttpStatus status, String message) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("status", status.value());
        payload.put("message", message);
        return ResponseEntity.status(status).contentType(MediaType.APPLICATION_JSON).body(payload);
    }

    // 비즈니스 규칙 위반(예: 정원 마감, 이미 가입됨) → 409
    @ExceptionHandler(IllegalStateException.class)
    public ResponseEntity<Map<String, Object>> handleIllegalState(IllegalStateException ex) {
        log.warn("Business rule violation: {}", ex.getMessage());
        return body(HttpStatus.CONFLICT, ex.getMessage());
    }

    // 잘못된 입력(예: 정원 범위 초과) → 400
    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseEntity<Map<String, Object>> handleIllegalArgument(IllegalArgumentException ex) {
        log.warn("Invalid argument: {}", ex.getMessage());
        return body(HttpStatus.BAD_REQUEST, ex.getMessage());
    }

    // @Valid 검증 실패(빈 message, 20000자 초과 등) → 400 + 첫 위반 메시지. 기본 처리는 본문 없는 400 이라 프론트가 원인을 못 보여줬다.
    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<Map<String, Object>> handleValidation(MethodArgumentNotValidException ex) {
        String message = ex.getBindingResult().getFieldErrors().stream()
                .map(fe -> fe.getDefaultMessage() != null ? fe.getDefaultMessage() : fe.getField() + " 값이 올바르지 않습니다.")
                .findFirst()
                .orElse("요청 값이 올바르지 않습니다.");
        log.warn("Validation failed: {}", message);
        return body(HttpStatus.BAD_REQUEST, message);
    }

    // 대상 없음 → 404
    @ExceptionHandler(NoSuchElementException.class)
    public ResponseEntity<Map<String, Object>> handleNotFound(NoSuchElementException ex) {
        log.warn("Resource not found: {}", ex.getMessage());
        return body(HttpStatus.NOT_FOUND, ex.getMessage());
    }

    // 비밀번호 찾기(이메일 인증) 흐름: 예외가 지정한 상태코드 + reason 코드. 인증번호/비밀번호는 메시지에 포함되지 않는다.
    @ExceptionHandler(PasswordResetException.class)
    public ResponseEntity<Map<String, Object>> handlePasswordReset(PasswordResetException ex) {
        log.warn("Password reset rejected: reason={} message={}", ex.getReason(), ex.getMessage());
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("status", ex.getStatus().value());
        payload.put("message", ex.getMessage());
        payload.put("reason", ex.getReason().name());
        ResponseEntity.BodyBuilder builder = ResponseEntity.status(ex.getStatus()).contentType(MediaType.APPLICATION_JSON);
        if (ex.getRetryAfterSeconds() != null) {
            payload.put("retryAfterSeconds", ex.getRetryAfterSeconds());
            builder.header("Retry-After", String.valueOf(ex.getRetryAfterSeconds()));
        }
        return builder.body(payload);
    }

    // AI 업스트림 사전(pre-stream) 실패 → 업스트림 상태 보존/매핑 + JSON. SSE 200 으로 위장하지 않는다.
    //  (스트림이 이미 열린 뒤의 실패는 ChatService 가 error/done 이벤트로 처리한다.)
    @ExceptionHandler(AiUpstreamException.class)
    public ResponseEntity<Map<String, Object>> handleAiUpstream(AiUpstreamException ex) {
        log.warn("AI upstream pre-stream failure: status={} code={} upstreamStatus={} upstreamCode={} requestId={}",
                ex.getStatus().value(), ex.getCode(), ex.getUpstreamStatus(), ex.getUpstreamCode(), ex.getRequestId());
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("status", ex.getStatus().value());
        payload.put("code", ex.getCode());
        payload.put("message", ex.getMessage());
        payload.put("retryable", ex.isRetryable());
        if (ex.getRequestId() != null) {
            payload.put("requestId", ex.getRequestId());
        }
        if (ex.getUpstreamCode() != null) {
            payload.put("upstreamCode", ex.getUpstreamCode());
        }
        ResponseEntity.BodyBuilder builder = ResponseEntity.status(ex.getStatus()).contentType(MediaType.APPLICATION_JSON);
        if (ex.getRequestId() != null) {
            builder.header("X-Request-ID", ex.getRequestId());
        }
        if (ex.isRetryable()) {
            builder.header("Retry-After", "5");
        }
        return builder.body(payload);
    }

    // 권한 없음(서비스 계층에서 던지는 SecurityException) → 403
    @ExceptionHandler(SecurityException.class)
    public ResponseEntity<Map<String, Object>> handleForbidden(SecurityException ex) {
        log.warn("Access denied: {}", ex.getMessage());
        return body(HttpStatus.FORBIDDEN, ex.getMessage());
    }
}
