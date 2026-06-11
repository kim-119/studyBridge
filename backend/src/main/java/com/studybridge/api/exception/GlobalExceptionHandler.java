package com.studybridge.api.exception;

import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.NoSuchElementException;

/**
 * 서비스 계층에서 던지는 비즈니스 예외를 적절한 HTTP 상태코드 + 메시지 본문으로 변환한다.
 * 매핑되지 않은 예외는 그대로 전파되어 기본 500 처리된다.
 */
@Slf4j
@RestControllerAdvice
public class GlobalExceptionHandler {

    private ResponseEntity<Map<String, Object>> body(HttpStatus status, String message) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("status", status.value());
        payload.put("message", message);
        return ResponseEntity.status(status).body(payload);
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

    // 대상 없음 → 404
    @ExceptionHandler(NoSuchElementException.class)
    public ResponseEntity<Map<String, Object>> handleNotFound(NoSuchElementException ex) {
        log.warn("Resource not found: {}", ex.getMessage());
        return body(HttpStatus.NOT_FOUND, ex.getMessage());
    }

    // 권한 없음(서비스 계층에서 던지는 SecurityException) → 403
    @ExceptionHandler(SecurityException.class)
    public ResponseEntity<Map<String, Object>> handleForbidden(SecurityException ex) {
        log.warn("Access denied: {}", ex.getMessage());
        return body(HttpStatus.FORBIDDEN, ex.getMessage());
    }
}
