package com.studybridge.api.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

public class QuestionDTO {

    @Getter
    @NoArgsConstructor
    @AllArgsConstructor
    public static class Request {
        private String userQuestion;
    }

    @Getter
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class Response {
        private Long questionId;
        private Long materialId;
        private String userQuestion;
        private String aiAnswer;
        private LocalDateTime createdAt;
        // AI 상태 전파 필드 (nullable, 하위호환 additive)
        private Boolean success;
        private String errorCode;
        private String message;
        private Boolean retryable;
        private Map<String, Object> textStatus;
        private List<String> warnings;
        private Map<String, Object> metadata;
        private String provider;
        private String model;
        private Long elapsedMs;
        private Boolean usedFallback;
        private Boolean cacheHit;
    }
}
