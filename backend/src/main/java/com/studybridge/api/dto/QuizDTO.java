package com.studybridge.api.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

public class QuizDTO {

    @Getter
    @NoArgsConstructor
    @AllArgsConstructor
    public static class Request {
        private String difficulty; // 쉬움, 보통, 어려움
        private Integer questionCount; // 문항 수
        private String pageRange; // 전체 또는 특정 범위
    }

    @Getter
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class Response {
        private Long quizId;
        private Long materialId;
        private String difficulty;
        private Integer questionCount;
        private String pageRange;
        private String quizData; // JSON 형식의 퀴즈 데이터
        private List<Map<String, Object>> quizzes;
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
