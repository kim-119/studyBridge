package com.studybridge.api.security.exhibit;

import lombok.Getter;
import org.springframework.http.HttpStatus;

/** 체험 계정 세션 슬롯을 열 수 없을 때(동시 접속 한도 409 / Redis 장애 503). */
@Getter
public class ExhibitSessionException extends RuntimeException {

    private final HttpStatus status;
    private final String code;

    public ExhibitSessionException(HttpStatus status, String code, String message) {
        super(message);
        this.status = status;
        this.code = code;
    }
}
