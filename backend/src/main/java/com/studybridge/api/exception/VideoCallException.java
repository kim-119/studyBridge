package com.studybridge.api.exception;

import lombok.Getter;
import org.springframework.http.HttpStatus;

/**
 * 그룹 화상통화(OpenVidu) API 의 계약 오류. 응답 본문 {status, code, message} 의 code 는 웹·Android 가 분기에 쓰는 안정 값이다.
 */
@Getter
public class VideoCallException extends RuntimeException {

    private final HttpStatus status;
    private final String code;

    public VideoCallException(HttpStatus status, String code, String message) {
        super(message);
        this.status = status;
        this.code = code;
    }
}
