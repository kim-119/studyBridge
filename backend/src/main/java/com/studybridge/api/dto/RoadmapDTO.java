package com.studybridge.api.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.util.List;
import java.util.Map;

@Getter
@Builder(toBuilder = true)
@NoArgsConstructor
@AllArgsConstructor
public class RoadmapDTO {
    private Long roadmapId;
    private Long materialId;
    private String title;

    private List<RoadmapStepDTO> steps;
    private Object roadmapData;
    private Integer totalWeeks;

    // AI 상태 전파 필드 (nullable, 하위호환 additive)
    private Boolean success;
    private String errorCode;
    private String message;
    private Boolean retryable;
    private Map<String, Object> textStatus;
    private List<String> warnings;
    private Map<String, Object> metadata;
    private String provider;
    private String model;
    private Long elapsedMs;
    private Boolean usedFallback;
    private Boolean cacheHit;

    // 품질 게이트(Phase D, 게이트 ON 에서만 채움 — OFF 응답 형태 불변). qualityRedacted=true: 미검증 저장본이라 AI 본문을 가림.
    @com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
    private String qualityStatus;
    @com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
    private Double qualityScore;
    @com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
    private Boolean verified;
    @com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
    private Boolean qualityRedacted;

    @Getter
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class RoadmapStepDTO {
        private Long stepId;
        private Integer stepOrder; // 1주차, 2주차...
        private String title;
        private String description;
        private List<RoadmapTaskDTO> tasks;
    }

    @Getter
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class RoadmapTaskDTO {
        private Long taskId;
        private Integer taskOrder;
        private String content; // 학습 목표, 학습 활동 등
        private Boolean isCompleted; // 완료 여부 체크
        // 게이트 ON: 레거시(steps/tasks) 로드맵 과제 문구는 검증 기록이 없어 가린다(진행 상태는 유지).
        @com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
        private Boolean qualityRedacted;
    }
}
