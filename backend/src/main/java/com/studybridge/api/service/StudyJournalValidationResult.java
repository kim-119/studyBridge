package com.studybridge.api.service;

import lombok.Builder;
import lombok.Getter;

/**
 * ai07 FastAPI 학습일지 검증 결과(또는 Spring 로컬 폴백 결과)를 담는 값 객체.
 * 원문/비밀값을 담지 않는다.
 */
@Getter
@Builder
public class StudyJournalValidationResult {

    private final String decision;        // ACCEPT | REQUEST_REVISION | BLOCK
    private final String category;
    private final String relationType;
    private final String relationPath;
    private final boolean studyRelated;
    private final boolean pdfGrounded;
    private final boolean conceptExpanded;
    private final double confidence;
    private final String reason;
    private final String suggestion;
    private final String engine;          // openai | ollama | deterministic | spring-fallback

    public boolean isAccepted() {
        return "ACCEPT".equalsIgnoreCase(decision);
    }
}
