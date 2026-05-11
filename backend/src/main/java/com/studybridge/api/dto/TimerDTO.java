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
        private Long totalMinutes; // 총 공부 시간 추가
        private Long averageMinutes; // 평균 공부 시간 추가
        private Integer attendanceDays; // 출석일 수 추가
        private List<DailyStudyTime> dailyStats; // data 필드명을 dailyStats로 변경
    }

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class DailyStudyTime {
        private String date; // 날짜 추가 (YYYY-MM-DD)
        private String day; // 요일 (MONDAY, TUESDAY...)
        private Long minutes; // 해당 요일의 학습 시간 (분)
    }
}
