package com.studybridge.api.dto;

import lombok.*;
import java.time.LocalDateTime;

public class StudyGroupDTO {

    public static class Request {
        // 모집 완료 후 스터디 결성 시 설정 값이 더 이상 불필요하여 비워둡니다.
    }

    @Getter
    @Setter
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class Response {
        private Long id;
        private Long studyRecruitmentId;
        private String title;
        private String status;
        private LocalDateTime createdAt;
    }

    @Getter
    @Setter
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class MemberResponse {
        private Long userId;
        private String email;
        private String displayName;
        private String photoUrl;
        private String major;
        private String role; // LEADER, MEMBER
    }
}
