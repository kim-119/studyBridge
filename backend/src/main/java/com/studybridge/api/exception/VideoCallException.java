package com.studybridge.api.exception;

import lombok.Getter;
import org.springframework.http.HttpStatus;

import java.util.Map;

/**
 * 그룹 화상통화(OpenVidu) API 의 계약 오류. 응답 본문 {status, code, message[, details]} 의 code 는 웹·Android 가 분기에 쓰는 안정 값이다.
 */
@Getter
public class VideoCallException extends RuntimeException {

    private final HttpStatus status;
    private final String code;
    /** 클라이언트가 후속 조치에 쓰는 부가 정보(예: SCREEN_ALREADY_ACTIVE 의 기존 connectionId). 없으면 빈 맵. */
    private final Map<String, Object> details;

    public VideoCallException(HttpStatus status, String code, String message) {
        this(status, code, message, Map.of());
    }

    public VideoCallException(HttpStatus status, String code, String message, Map<String, Object> details) {
        super(message);
        this.status = status;
        this.code = code;
        this.details = details == null ? Map.of() : details;
    }
}
