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
        // 난이도 검증 (G/H): 요청/적용 난이도 + 정책 + 검증 결과 (ai07이 제공하면 전파, 없으면 null)
        private String difficultyRequested;   // easy | normal | hard
        private String difficultyApplied;     // ai07이 실제 적용한 난이도
        private String difficultyPolicy;      // 난이도 정책 설명
        private Map<String, Object> difficultyValidation; // { passed, reason }
        private Map<String, Object> sourceTrace;          // 출제 근거 (source_type=PDF_BASED, based_on, concepts, evidence)
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
