package com.studybridge.api.dto;

import com.studybridge.api.entity.TimerStatus;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;
import java.util.List;

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

    // --- 추가된 DTO ---

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class TodayStudyTimeResponse {
        private Long userId;
        private Long todayMinutes;
    }

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class WeeklyStudyTimeResponse {
        private Long userId;
        private List<DailyStudyTime> data;
    }

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class DailyStudyTime {
        private String day; // 요일 (월, 화, 수...)
        private Long minutes; // 해당 요일의 학습 시간 (분)
    }
}
