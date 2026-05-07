package com.studybridge.api.dto;

import com.studybridge.api.entity.TimerStatus;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

public class TimerDTO {

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class StartRequest {
        private Long userId;
        private LocalDateTime startTime;
    }

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class EndRequest {
        private Long userId;
        private LocalDateTime endTime;
        private Long durationMinutes;
    }

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class Response {
        private Long id;
        private Long userId;
        private LocalDateTime startTime;
        private LocalDateTime endTime;
        private Long durationMinutes;
        private TimerStatus status;
        private LocalDateTime createdAt;
        private LocalDateTime updatedAt;
    }
}
