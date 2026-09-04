package com.studybridge.api.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;
import java.util.Map;

/** AI 계획 분석 API 계약 DTO. */
public class PlanAnalysisDTO {

    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class Item {
        private Long id;
        private Integer orderIndex;
        private String type;          // SENTENCE | ACTION
        private String text;
        private String sourceText;
        private String sourceType;    // PDF | PLANNER | ROADMAP
        private Integer pageNumber;
        private Integer chunkIndex;
        private boolean completed;
        private boolean hidden;
    }

    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class Progress {
        private int totalCount;       // deleted=false 항목 수
        private int completedCount;   // completed=true (hidden 포함)
        private int hiddenCount;      // hidden=true 항목 수
        private int visibleCount;     // hidden=false & deleted=false
        private int percent;
    }

    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class Response {
        private Long analysisId;
        private Long materialId;
        private String sourceType;    // PDF | PLANNER | ROADMAP | MIXED
        private String summary;
        private String recommendation;
        private boolean empty;        // 분석 결과가 아직 없음
        private String errorCode;     // null 이면 정상
        private List<Item> items;     // deleted=false 전체(숨김 포함, hidden 플래그로 구분)
        private List<String> recommendations;
        private PlannerAnalysisData plannerAnalysisData;
        private Progress progress;
        private Meta meta;
    }

    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class Meta {
        private int plannerCount;
        private int pdfTextLength;
        private int sourceTextCount;
        private int chunkCount;
        private int sentenceCount;
        private int itemCount;
        private int taskCount;
        private int scheduleCount;
        private int analysisContentLength;
        private long elapsedMs;
        private String requestId;
        private String fastApiEndpoint;
        private Integer fastApiResponseStatus;
    }

    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class PlannerAnalysisData {
        private Long plannerId;
        private String title;
        private List<String> keywords;
        private String learningGoal;
        private List<String> schedule;
        private List<String> checklist;
        private Integer progress;
        private String aiFeedback;
        private List<String> scheduleAnalysis;
        private List<String> problemPoints;
        private String balanceAssessment;
        private List<String> improvementActions;
        private List<String> nextRecommendations;
        private List<String> unfinishedItems;
        private String message;
    }

    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class PlannerAnalysisRequest {
        private Long plannerId;
        private String title;
        private String plannerTitle;
        private String subject;
        private String category;
        private String content;
        private String todo;
        private String memo;
        private String goal;
        private String goalTime;
        private String netStudyTime;
        private String dDay;
        private String deadline;
        private String date;
        private String studyType;
        private String priority;
        private List<String> checklist;
        private List<String> completedTasks;
        private List<String> incompleteTasks;
        private Integer progress;
        private Map<String, Object> plannerMeta;
    }

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    public static class ItemPatchRequest {
        private Boolean completed;
        private Boolean hidden;
    }

    @Data
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class RecommendationResponse {
        private Long analysisId;
        private List<String> recommendations;
        private String errorCode;
    }
}
