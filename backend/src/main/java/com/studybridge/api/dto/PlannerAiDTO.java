package com.studybridge.api.dto;

import lombok.*;

import java.util.List;

/**
 * 공부 플래너 전용 AI DTO.
 *  - ExpandResponse: 학습 실행 계획 / 플래너 기반 AI 질문 / 회고 프롬프트.
 *  - RoadmapResponse: 플래너 기반 12주 로드맵 (자료보관함 RoadmapDTO와 별개로 planner 연결).
 */
public class PlannerAiDTO {

    @Getter
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class ExpandResponse {
        private Boolean success;
        private Long plannerId;
        private String expandedGoal;
        private List<String> expandedTodos;
        private String estimatedTime;
        private List<String> studyOrder;
        private List<String> riskPoints;
        private List<String> todayCheckpoints;
        private List<String> aiQuestions;
        private List<String> reflectionPrompts;
        // 실패 시
        private String errorCode;
        private String message;
    }

    @Getter
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class Week {
        private Integer week;
        private String title;
        private String goal;
        private List<String> tasks;
    }

    @Getter
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class RoadmapResponse {
        private Boolean success;
        private Long plannerId;
        private Long roadmapId;
        private String title;
        private List<Week> weeks;
        private String errorCode;
        private String message;
    }
}
