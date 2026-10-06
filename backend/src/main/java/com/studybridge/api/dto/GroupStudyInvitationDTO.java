package com.studybridge.api.dto;

import com.studybridge.api.entity.GroupStudyType;
import lombok.*;

import java.time.LocalDateTime;

public class GroupStudyInvitationDTO {

    /** 초대 링크 생성 요청(모두 선택). expiresInDays 1~30(기본 7), maxUses null=무제한. */
    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class CreateRequest {
        private Integer expiresInDays;
        private Integer maxUses;
    }

    /** 방장에게 보여 주는 초대 링크. inviteUrl 은 클라이언트가 현재 오리진(데스크톱/모바일/앱)으로 조립한다. */
    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class Response {
        private Long id;
        private Long groupId;
        private String token;
        private String invitePath;      // "/groups/invite/{token}"
        private Long createdBy;
        private LocalDateTime createdAt;
        private LocalDateTime expiresAt;
        private boolean active;
        private int usedCount;
        private Integer maxUses;
    }

    /** 초대 링크 미리보기(수락 전). valid=false 면 reason 에 사유. */
    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class Preview {
        private boolean valid;
        private String reason;
        private Long groupId;
        private String title;
        private String description;
        private GroupStudyType studyType;
        private Boolean isPublic;
        private Integer capacity;
        private Integer currentCount;
        private String leaderName;
        private String coverImageUrl;
        private Boolean nicknameRuleEnabled;
        private String nicknameRule;
        private boolean alreadyMember;
        private LocalDateTime expiresAt;
    }

    /** 초대 수락 요청. nickname 은 그룹 닉네임 규칙 ON 일 때 필수(서버 검증). */
    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class AcceptRequest {
        private String nickname;
        private String introduction;
    }
}
