package com.studybridge.api.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

public class GroupStudyReportDTO {

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class Request {
        private Long reportedUserId; // 선택적 (특정 유저 신고인 경우)
        private String reason; // 신고 사유
    }

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class Response {
        private Long id;
        private Long groupStudyId;
        private Long reporterId;
        private String reporterName;
        private Long reportedUserId;
        private String reportedUserName;
        private String reason;
        private LocalDateTime createdAt;
    }
}
