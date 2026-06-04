package com.studybridge.api.dto;

import com.studybridge.api.entity.GroupStudyJoinStatus;
import com.studybridge.api.entity.GroupStudyRole;
import com.studybridge.api.entity.GroupStudyStatus;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDate;
import java.time.LocalDateTime;

public class GroupStudyDTO {

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class CreateRequest {
        @NotBlank(message = "그룹 제목은 필수입니다.")
        private String title;

        @NotBlank(message = "세부 사항은 필수입니다.")
        private String description;

        @NotNull(message = "시작 기간은 필수입니다.")
        @org.springframework.format.annotation.DateTimeFormat(iso = org.springframework.format.annotation.DateTimeFormat.ISO.DATE)
        private LocalDate startDate;

        @NotNull(message = "종료 기간은 필수입니다.")
        @org.springframework.format.annotation.DateTimeFormat(iso = org.springframework.format.annotation.DateTimeFormat.ISO.DATE)
        private LocalDate endDate;

        @NotNull(message = "정원은 필수입니다.")
        @Min(value = 2, message = "최소 인원은 2명입니다.")
        @Max(value = 10, message = "최대 정원은 10명입니다. (화상통화 안정 성능 보장)")
        private Integer capacity;

        @NotNull(message = "공개 방 여부는 필수입니다.")
        private Boolean isPublic;

        private String hashtags;
    }

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class JoinApplyRequest {
        @NotBlank(message = "가입 소개글(각오)은 필수입니다.")
        private String introduction;
    }

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class Response {
        private Long id;
        private String title;
        private String description;
        private LocalDate startDate;
        private LocalDate endDate;
        private Integer capacity;
        private Integer currentCount;
        private Boolean isPublic;
        private Long leaderId;
        private String leaderName;
        private GroupStudyStatus status;
        private LocalDateTime createdAt;
        private String hashtags;
        private String coverImageUrl;
    }

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class MemberResponse {
        private Long userId;
        private String displayName;
        private String photoUrl;
        private String major;
        private GroupStudyRole role;
        private Integer points;
        private LocalDateTime joinedAt;
        private LocalDateTime recentAttendanceTime;
        private Long recentStudyTimeSeconds;
        private Long cumulativeStudyTimeSeconds;
    }

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class ApplicationResponse {
        private Long applicationId;
        private Long groupStudyId;
        private Long applicantId;
        private String applicantName;
        private String applicantPhotoUrl;
        private String introduction;
        private GroupStudyJoinStatus status;
        private LocalDateTime createdAt;
    }

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class UpdateRequest {
        private String title;
        private String description;
        @org.springframework.format.annotation.DateTimeFormat(iso = org.springframework.format.annotation.DateTimeFormat.ISO.DATE)
        private LocalDate startDate;
        @org.springframework.format.annotation.DateTimeFormat(iso = org.springframework.format.annotation.DateTimeFormat.ISO.DATE)
        private LocalDate endDate;
        @Min(value = 2, message = "최소 인원은 2명입니다.")
        @Max(value = 10, message = "최대 정원은 10명입니다. (화상통화 안정 성능 보장)")
        private Integer capacity;
        private Boolean isPublic;
        private String hashtags;
    }
}

