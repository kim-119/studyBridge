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

    /**
     * 학습 실행 관리 AI 피드백 (POST /api/planners/{id}/ai-assist).
     *  - 플래너를 "실행 가능한 계획"으로 정리 + 피드백한다. 로드맵/퀴즈/문서질문 없음.
     *  - 사용자 원본 메모는 보존하고, AI 결과만 별도로 담는다.
     */
    @Getter
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class AssistResponse {
        private Boolean success;
        private Long plannerId;
        private String aiSummary;             // AI 요약
        private String refinedGoal;           // 정리된 학습 목표
        private List<String> taskBreakdown;   // 할 일 정리
        private String timeFeedback;          // 시간 진행 상태 피드백 (부족/적정/초과)
        private List<String> strengths;       // 장점
        private List<String> concerns;        // 우려사항
        private List<String> recommendations; // 권장사항
        private List<String> nextActions;     // 다음 학습 행동
        private Boolean usedFallback;         // ai07 미배포/오류 시 로컬 기본 피드백 사용 여부
        private String errorCode;
        private String message;
        // 품질 게이트(PLANNER_COACHING). 게이트 OFF 면 전부 null → JSON 에 나가지 않는다(기존 응답과 동일).
        @com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
        private String qualityStatus;
        @com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
        private Double qualityScore;
        @com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
        private Boolean verified;
        // true = 미검증 저장본이라 AI 생성 필드를 내보내지 않았다(게이트 ON).
        @com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
        private Boolean qualityRedacted;
        @com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
        private Boolean retryable;
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
        // 신(新) 84일(12주x7일) 구조: ai07 원본 응답(weeks[].days[])을 그대로 실어 보낸다.
        private Object roadmapData;
        private String errorCode;
        private String message;
    }
}
