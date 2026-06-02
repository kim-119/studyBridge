package com.studybridge.api.dto;

import lombok.*;
import java.time.LocalDateTime;

public class StudyRecruitmentDTO {

    @Getter
    @Setter
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class Request {
        private String title;
        private String objective;
        private LocalDateTime deadline;
        private Integer maxMembers;
    }

    @Getter
    @Setter
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class Response {
        private Long id;
        private String title;
        private String objective;
        private LocalDateTime deadline;
        private Integer maxMembers;
        private Integer currentMembers;
        private Long leaderId;
        private String leaderName;
        private String leaderPhotoUrl;
        private String status;
        private LocalDateTime createdAt;
    }
}
