package com.studybridge.api.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.util.List;
import java.util.Map;

@Getter
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class RoadmapDTO {
    private Long roadmapId;
    private Long materialId;
    private String title;

    private List<RoadmapStepDTO> steps;

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
    }
}
