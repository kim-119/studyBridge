package com.studybridge.api.dto;

import com.studybridge.api.entity.ReportReason;
import com.studybridge.api.entity.ReportStatus;
import com.studybridge.api.entity.ReportType;
import lombok.*;

import java.time.LocalDateTime;

public class ReportDTO {

    @Getter
    @Setter
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class UserReportRequest {
        private Long reportedUserId;
        private ReportReason reason;
        private String details;
    }

    @Getter
    @Setter
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class PostReportRequest {
        private Long reportedBlogId;
        private ReportReason reason;
        private String details;
    }

    @Getter
    @Setter
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class CommentReportRequest {
        private Long reportedCommentId;
        private ReportReason reason;
        private String details;
    }

    @Getter
    @Setter
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class Response {
        private Long reportId;
        private Long reporterId;
        private String reporterNickname;
        private ReportType reportType;
        private Long targetId; // reportedUserId or reportedBlogId
        private String targetTitleOrName; // user nickname or blog title
        private ReportReason reason;
        private String details;
        private ReportStatus status;
        private LocalDateTime createdAt;
    }
}
