package com.studybridge.api.service;

import lombok.Getter;

/** AI 계획 분석 전용 예외 — errorCode 를 그대로 클라이언트에 전달한다. */
@Getter
public class PlanAnalysisException extends RuntimeException {
    private final String errorCode;

    public PlanAnalysisException(String errorCode, String message) {
        super(message);
        this.errorCode = errorCode;
    }
}
