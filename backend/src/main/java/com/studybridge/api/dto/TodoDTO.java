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
        private Long userId;
        private String text;
        private Boolean completed;
        private LocalDateTime startDate;
        private LocalDateTime endDate;
        private String viewType;
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
        private String viewType;
        private LocalDateTime createdAt;
    }
}
