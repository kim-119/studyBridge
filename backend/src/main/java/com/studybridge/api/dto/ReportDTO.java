package com.studybridge.api.dto;

import com.studybridge.api.entity.ReportStatus;
import com.studybridge.api.entity.ReportTargetType;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import lombok.Builder;
import lombok.Getter;
import lombok.Setter;

import java.time.LocalDateTime;

public class ReportDTO {

    @Getter
    @Setter
    public static class ReportRequest {
        @NotNull(message = "신고 대상 타입은 필수입니다.")
        private ReportTargetType targetType;

        @NotNull(message = "신고 대상 ID는 필수입니다.")
        private Long targetId;

        @NotBlank(message = "신고 사유는 필수입니다.")
        private String reason;
    }

    @Getter
    @Setter
    @Builder
    public static class ReportResponse {
        private Long reportId;
        private Long reporterUserId;
        private String reporterEmail;
        private ReportTargetType targetType;
        private Long targetId;
        private String targetContent; // 신고 대상의 내용 (예: 자료 파일명, 유저 닉네임, 댓글 내용)
        private String targetUrl; // 신고 대상의 URL (예: 자료 다운로드 URL)
        private String reason;
        private ReportStatus status;
        private LocalDateTime reportedAt;
    }
}