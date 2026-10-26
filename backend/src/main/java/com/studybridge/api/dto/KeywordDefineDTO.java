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
    }
}
