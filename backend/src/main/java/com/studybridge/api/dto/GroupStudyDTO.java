package com.studybridge.api.dto;

import com.studybridge.api.entity.GroupStudyJoinStatus;
import com.studybridge.api.entity.GroupStudyRole;
import com.studybridge.api.entity.GroupStudyStatus;
import com.studybridge.api.entity.GroupStudyType;
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

        // ── 운영 정책(선택). 구 클라이언트(미전송)는 GENERAL/240분/OFF 로 생성된다. 값 검증은 GroupStudySettingsPolicy.
        @Builder.Default
        private GroupStudyType studyType = GroupStudyType.GENERAL;

        @Builder.Default
        private Integer targetStudyMinutes = 240;

        @Builder.Default
        private boolean joinQuestionEnabled = false;

        private String joinQuestion;

        @Builder.Default
        private boolean nicknameRuleEnabled = false;

        private String nicknameRule;

        private String studyIconId;
    }

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class JoinApplyRequest {
        @NotBlank(message = "가입 소개글(각오)은 필수입니다.")
        private String introduction;

        // 그룹이 가입 질문을 켠 경우 필수(서버 검증). 질문 OFF 그룹이면 무시된다.
        private String joinAnswer;

        // 그룹이 닉네임 규칙을 켠 경우 필수(서버 검증). OFF 그룹이면 선택.
        private String nickname;
    }

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class MemberNicknameRequest {
        private String nickname; // null/빈 값이면 별칭 해제(단, 닉네임 규칙 ON 그룹은 해제 불가)
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
        private String leaderPhotoUrl;

        // ── 운영 정책(항상 non-null: 구 row 는 DB default). enabled=false 이면 question/rule 은 null.
        private GroupStudyType studyType;
        private Integer targetStudyMinutes;
        private Boolean joinQuestionEnabled;
        private String joinQuestion;
        private Boolean nicknameRuleEnabled;
        private String nicknameRule;
        private String studyIconId;

        // ── 활동 지표(최근 activityWindowDays 일, 서버 계산·프론트 포맷). 기록이 없으면 0.
        private Integer memberCount;      // == currentCount (앱 계약용 별칭)
        private Integer maxMembers;       // == capacity (앱 계약용 별칭)
        private Double attendanceRate;    // 0.0 ~ 100.0 (소수 1자리)
        private Long avgStudySeconds;     // 그룹원 1인·1일 평균 공부시간(초)
        private Integer activityWindowDays;
    }

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class MemberResponse {
        private Long userId;
        private String displayName;
        private String nickname; // 그룹 내 별칭(없으면 null → displayName 사용)
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
        private String joinQuestion; // 지원 당시 그룹 질문(현재 설정 기준). OFF 면 null
        private String joinAnswer;
        private String nickname;
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

        // ── 운영 정책(부분 수정: null 이면 유지). enabled 를 false 로 바꾸면 question/rule 은 null 로 정규화.
        private GroupStudyType studyType;
        private Integer targetStudyMinutes;
        private Boolean joinQuestionEnabled;
        private String joinQuestion;
        private Boolean nicknameRuleEnabled;
        private String nicknameRule;
        private String studyIconId;
        private Boolean clearStudyIcon;
    }
}

