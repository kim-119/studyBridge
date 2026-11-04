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
    /** Spring 로컬 폴백/저장 보류가 만든 결과(문구가 Spring 고정 문구 — AI 생성 아님). ai07 응답이 보낸 engine 문자열로 판단하지 않는다. */
    private final boolean localOrigin;
    /** 품질 게이트(게이트 ON 에서만): 사용자 노출 판정 문구 평가 결과(APPROVED 등) / 문구를 고정 문구로 바꿨는지. OFF 면 null. */
    private final String qualityStatus;
    private final Boolean qualityRedacted;

    public boolean isAccepted() {
        return "ACCEPT".equalsIgnoreCase(decision);
    }
}
