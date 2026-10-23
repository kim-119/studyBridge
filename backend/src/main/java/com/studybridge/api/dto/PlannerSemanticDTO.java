package com.studybridge.api.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.*;
import java.util.List;

/** Mirrors AI07 app/schemas/planner_analysis_schema.py; schedule metadata is server-owned. */
public class PlannerSemanticDTO {
    public enum Level { HIGH, MEDIUM, LOW }
    public enum TaskType { CONCEPT, PRACTICE, ANALYSIS, COMPARISON, REVIEW, OUTPUT }
    @Data @NoArgsConstructor @AllArgsConstructor
    public static class GoalAlignment { private Level level; private String reason; }
    @Data @NoArgsConstructor @AllArgsConstructor
    public static class PlanGoalAlignment { private Level level; private String reason; private String summary; private List<String> issues; }
    @Data @NoArgsConstructor @AllArgsConstructor
    public static class Prerequisite { private String name; private String reason; private boolean includedInPlanTime; }
    @Data @NoArgsConstructor @AllArgsConstructor
    public static class Task {
        private String id; private Integer order; private String title; private String description;
        private TaskType type; private Integer recommendedMinutes; private GoalAlignment goalAlignment;
        private String whyImportant; private List<Prerequisite> prerequisites; private List<String> learningSequence;
    }
    @Data @NoArgsConstructor @AllArgsConstructor
    public static class Summary { private String title; private String subject; private Integer targetMinutes; private String sourceType; }
    @Data @NoArgsConstructor @AllArgsConstructor
    public static class ChecklistLink { private String id; private String text; private Boolean completed; private List<String> taskIds; }
    @Data @NoArgsConstructor @AllArgsConstructor
    public static class InputItem { private String id; private String title; private String description; private Boolean completed; }
    @Data @NoArgsConstructor @AllArgsConstructor
    public static class RoadmapContext {
        private Integer currentWeek; private Integer currentDay; private String term; private String learningGoal;
        private List<String> previousLearning; private List<String> nextLearning;
    }
    /**
     * AI07 analyze-semantic 요청. 신뢰 우선순위(ROADMAP): topic/title/subject → 해당 week/day objective →
     * 해당 day 의 개념형 core concepts / tasks → content/memo(보조 컨텍스트).
     *  - coreConcepts: 오늘 학습할 개념(개념형만). 선행 개념이 아니다.
     *  - priorConcepts: 로드맵에서 오늘보다 앞선 날에 다룬 개념형 개념(선행 개념 후보).
     *  - excludedFragments: 개념명이 아니라 문장/예제로 판정되어 제외한 원문 조각(AI07 전송·지문 계산에서 제외).
     */
    @Data @NoArgsConstructor @AllArgsConstructor @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class Request {
        private Long plannerId; private String title; private String topic; private String subject; private String learningType;
        private String priority; private Integer targetMinutes; private String learningGoal; private String content;
        private String memo; private List<InputItem> detailTasks; private List<InputItem> checklist;
        private List<String> reviewQuestions; private List<String> outputs; private List<String> coreConcepts;
        private List<String> priorConcepts;
        private String sourceType; private RoadmapContext roadmapContext;
        @com.fasterxml.jackson.annotation.JsonIgnore private List<String> excludedFragments;
    }
    @Data @NoArgsConstructor
    public static class ScheduleRequest { private String startTime; }
    public record ScheduleRow(String taskId, String title, TaskType type, int recommendedMinutes,
                              String startTime, String endTime, int startDayOffset, int endDayOffset) {}
    public record Schedule(Long plannerId, String title, String date, int totalMinutes,
                           String startTime, List<ScheduleRow> rows) {}
    public record Download(String downloadUrl, String fileName, Schedule schedule) {}

    /** Ordered node in the "학습 Data Flow" visual; taskId links back to a Task detail. */
    @Data @NoArgsConstructor @AllArgsConstructor @Builder
    public static class FlowNode { private String taskId; private String title; private TaskType type; private Integer recommendedMinutes; }

    @Data @NoArgsConstructor @AllArgsConstructor @Builder
    public static class ChecklistProgress { private int total; private int completed; private int percent; }

    /** Full AI 계획 분석 payload returned to the client and cached on the planner. */
    @Data @Builder @NoArgsConstructor @AllArgsConstructor
    @JsonInclude(JsonInclude.Include.NON_NULL)
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class AnalysisResponse {
        private Long plannerId;
        private String title;
        private String subject;
        private String sourceType;               // ROADMAP | MANUAL
        private String learningGoal;
        private Integer targetMinutes;           // authoritative when present
        private boolean targetMinutesEstimated;  // true -> UI shows "AI 예상 학습시간"
        private Integer totalRecommendedMinutes;
        private String summary;
        private PlanGoalAlignment goalAlignment;
        private List<Prerequisite> prerequisites;
        private List<Task> tasks;
        private List<FlowNode> flow;
        private ChecklistProgress checklistProgress;
        private List<String> warnings;
        private String sourceFingerprint;
        private boolean stale;
        private boolean empty;                    // no analysis yet
        private String errorCode;                 // null when OK
        private String aiSource;                  // AI07 | FALLBACK
        private Integer narrativeVersion;         // 사용자 노출 문장 규칙 버전(구버전 캐시는 조회 시 문장만 재생성)
    }
}
