package com.studybridge.api.dto;

import lombok.*;

import java.util.List;

/**
 * 핵심 키워드 개념 정의 (자료보관함 chip 클릭).
 * 브라우저 → Spring → FastAPI /api/ai/keyword/define.
 */
public class KeywordDefineDTO {

    @Getter
    @Setter
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class Request {
        private String keyword;
        private String source;   // auto | gpt | wikipedia
        private String level;    // undergraduate 등
        private String context;  // 문서 맥락 (선택)
    }

    @Getter
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class Response {
        private Boolean success;
        private String name;
        private String shortDefinition;
        private String detailedDefinition;
        private String importance;
        private List<String> examples;
        private List<String> relatedConcepts;
        private String sourceUsed;   // GPT | Wikipedia | Mixed
        private String wikiUrl;
        // 실패 시
        private String errorCode;
        private String message;
        // 품질 게이트(Phase D, 게이트 ON 에서만 채움 — OFF 응답 형태 불변)
        @com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
        private Boolean retryable;
        @com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
        private String qualityStatus;
        @com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
        private Double qualityScore;
        @com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
        private Boolean verified;
    }
}
