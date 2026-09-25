package com.studybridge.api.dto;

import lombok.*;
import java.time.LocalDateTime;

public class TodoDTO {

    @Getter
    @Setter
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class Request {
        private String text;
        private Boolean completed;
        private LocalDateTime startDate;
        private LocalDateTime endDate;
    }

    @Getter
    @Setter
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class Response {
        private Long id;
        private String text;
        private Boolean completed;
        private LocalDateTime startDate;
        private LocalDateTime endDate;
        private LocalDateTime createdAt;
        // 출처(주간 일정 화면의 플래너/복습 구분용). 수동 Todo 는 null.
        private String sourceType;   // REVIEW_NOTE | PLANNER | null
        private Long sourceId;
        private java.time.LocalDate scheduleDate;
    }
}
