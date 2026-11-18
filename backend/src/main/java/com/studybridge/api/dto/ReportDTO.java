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

    /**
     * 내 신고 내역 1건(GET /api/reports/me). 신고자 본인에게만 내려가는 안전한 요약이다.
     *  - source: KNOWLEDGE(지식보드 게시글/댓글/유저 신고, reports 테이블) | GROUP(그룹스터디 유저 신고, group_study_reports 테이블)
     *  - targetType: USER | POST | COMMENT
     *  - targetSummary: 게시글 제목 / 댓글 앞 30자 / 피신고자 닉네임. 대상이 사라졌으면 targetAvailable=false + 대체 라벨.
     *  - status: reports 의 실제 enum(PENDING/RESOLVED/REJECTED). 그룹스터디 신고는 상태 컬럼이 없어 null(프론트 "접수됨").
     *  - 관리자 메모·타인 신고·피신고자 이메일 등 민감 정보는 포함하지 않는다.
     */
    @Getter
    @Setter
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class MyReportResponse {
        private Long reportId;
        private String source;
        private String targetType;
        private Long targetId;
        private String targetSummary;
        private boolean targetAvailable;
        private Long groupId;
        private String groupTitle;
        private ReportReason reason;
        private String details;
        private ReportStatus status;
        private LocalDateTime createdAt;
    }
}
