package com.studybridge.api.dto;

import lombok.*;
import java.time.LocalDateTime;

public class StudyApplicationDTO {

    @Getter
    @Setter
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class Request {
        private String status; // APPROVED, REJECTED
    }

    @Getter
    @Setter
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class Response {
        private Long id;
        private Long studyRecruitmentId;
        private Long userId;
        private String userDisplayName;
        private String userEmail;
        private String userMajor;
        private String status;
        private LocalDateTime appliedAt;
    }
}
