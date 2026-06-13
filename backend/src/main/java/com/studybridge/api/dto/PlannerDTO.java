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
        private String studyType;     // 학습 유형
        private String priority;      // 우선순위
        private String term;          // 학기/주차
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
        private String studyType;     // 학습 유형
        private String priority;      // 우선순위
        private String term;          // 학기/주차
        private String subject;
        private String content;
        private String tmi;
        private String timeTableJson;
        private String s3Key;
        private Long materialId;
        // 로드맵 자동 생성 추적용 (프론트에서 자료 기반 플래너 식별 + 전체삭제 대상 계산)
        private String sourceType;        // ROADMAP_AUTO 또는 null(수동)
        private Long sourceMaterialId;
        private Long sourceRoadmapId;
        private String downloadUrl;   // S3 presigned URL (있을 때만)
        private LocalDateTime createdAt;
        private LocalDateTime updatedAt;
    }

    // ---------- 자료 기반(ROADMAP_AUTO) 플래너 전체삭제 ----------
    // 현재 화면에 표시 중인 자료 기반 플래너만 삭제한다. 수동 플래너/주간일정/다른 유저 데이터는 절대 건드리지 않는다.
    @Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
    public static class BulkDeleteRequest {
        private String scope;                    // "VISIBLE_ROADMAP_AUTO" 만 허용
        private Long materialId;                 // 선택: 자료 필터 (있으면 일치 검증)
        private Long sourceRoadmapId;            // 선택: 로드맵 필터 (있으면 일치 검증)
        private String sourceType;               // "ROADMAP_AUTO" 만 허용
        private java.util.List<Long> plannerIds; // 현재 화면에 렌더링 중인 삭제 대상 id
    }

    @Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
    public static class BulkDeleteResponse {
        private boolean success;
        private Integer deletedCount;
        private String message;
        @JsonProperty("error_code")
        private String errorCode;
    }

    // ---------- 로드맵 기반 84개 플래너 자동 생성 ----------
    @Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
    public static class FromRoadmapRequest {
        private Long materialId;
        private Long roadmapId;
        private LocalDate startDate;     // 기본 오늘
        private String subject;          // 없으면 자료 제목
        private Boolean force;           // 중복 무시하고 추가 생성
        private java.util.List<RoadmapItem> items;
    }

    @Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
    public static class RoadmapItem {
        private Integer week;
        private Integer dayIndex;
        private String title;
        private String objective;
        private java.util.List<String> tasks;
        private java.util.List<String> coreConcepts;
        private java.util.List<String> reviewQuestions;
        private String checkpoint;
        private String deliverable;
        private Integer targetMinutes;   // tasks estimated_minutes 합산(프론트 계산), 없으면 null
    }

    @Getter @Setter @NoArgsConstructor @AllArgsConstructor @Builder
    public static class FromRoadmapResponse {
        private Integer createdCount;
        private String message;
        private Boolean duplicate;       // 기존 자동생성 플래너 존재 + force 아님
        private Long existingCount;
    }
}
