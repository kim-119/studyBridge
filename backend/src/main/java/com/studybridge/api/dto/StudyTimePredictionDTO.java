package com.studybridge.api.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

/**
 * 학습 시간 예측 계약.
 *  - {@link Request}         : Spring → FastAPI 요청. FastAPI 스키마(StudyTimePredictRequest) 기준으로 통일:
 *                              weeklyStudySeconds = 최근 7일 학습 시간(초), 정확히 7개.
 *  - {@link FastApiResponse} : FastAPI 응답(StudyTimePredictResponse) 그대로.
 *  - {@link Response}        : 프론트(StudyStatistics) 응답. 기존 필드(predictedSeconds/confidence/message) 유지 — 명시적 어댑터로 변환.
 */
public class StudyTimePredictionDTO {

    public static final int WEEK_DAYS = 7;

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class Request {
        private Long userId;
        /** 최근 7일(오래된 날 → 오늘) 학습 시간, 초 단위. 정확히 7개. */
        private List<Double> weeklyStudySeconds;
    }

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class FastApiResponse {
        private Double predictedStudySeconds;
        /** "transformer" 또는 "weighted_average_fallback" */
        private String method;
        private Double confidence;
        private Boolean modelAvailable;
    }

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class Response {
        private Long userId;
        private Double predictedSeconds;
        private Double confidence;
        private String message;
        /** 예측 출처: fastapi:transformer / fastapi:weighted_average_fallback / spring:local_fallback */
        private String source;
    }
}
