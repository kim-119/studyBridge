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
        // Intent Router 라우팅 결과 (nullable, additive). routeReason은 사용자 비노출이라 내려보내지 않는다.
        private String routeAction;        // DIRECT_REPLY/WARN/BLOCK/CLARIFY/QUIZ_PIPELINE/SUMMARY_PIPELINE/ROADMAP_PIPELINE 등
        private String routeMessage;       // 터미널/경고 시 사용자에게 보여줄 문구
        private Object pipeline;           // QUIZ/SUMMARY/ROADMAP 내부 실행 결과 페이로드
    }
}
