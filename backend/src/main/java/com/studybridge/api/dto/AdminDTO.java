package com.studybridge.api.dto;

import lombok.*;

import java.time.LocalDateTime;

public class AdminDTO {

    @Getter
    @Setter
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class UserSuspendRequest {
        private int days;
        private String reason;
        private String memo;
    }

    @Getter
    @Setter
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class UserBanRequest {
        private String reason;
        private String memo;
    }

    @Getter
    @Setter
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class ModerationResponse {
        private Long targetId;
        private String targetType; // USER or POST
        private String action; // SUSPEND, BAN, DELETE
        private String message;
        private LocalDateTime executionTime;
    }
}
