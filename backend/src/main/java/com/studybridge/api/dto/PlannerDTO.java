package com.studybridge.api.dto;

import com.fasterxml.jackson.annotation.JsonProperty;
import lombok.*;

import java.time.LocalDate;
import java.time.LocalDateTime;

public class PlannerDTO {

    @Getter
    @Setter
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class Request {
        private String title;
        private Integer year;
        private Integer month;
        private Integer day;
        private String dayOfWeek;
        private LocalDate plannerDate;
        private String goalTime;
        private String netStudyTime;
        private String wakeUpTime;
        @JsonProperty("dDay")
        private String dDay;
        private String subject;
        private String content;
        private String tmi;
        private String timeTableJson; // 10분 단위 시간 체크표 (JSON 문자열)
    }

    @Getter
    @Setter
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class Response {
        private Long id;
        private Long userId;
        private String title;
        private Integer year;
        private Integer month;
        private Integer day;
        private String dayOfWeek;
        private LocalDate plannerDate;
        private String goalTime;
        private String netStudyTime;
        private String wakeUpTime;
        @JsonProperty("dDay")
        private String dDay;
        private String subject;
        private String content;
        private String tmi;
        private String timeTableJson;
        private String s3Key;
        private Long materialId;
        private String downloadUrl;   // S3 presigned URL (있을 때만)
        private LocalDateTime createdAt;
        private LocalDateTime updatedAt;
    }
}
