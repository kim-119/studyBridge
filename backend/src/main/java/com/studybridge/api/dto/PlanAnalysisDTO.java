package com.studybridge.api.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

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
        private long elapsedMs;
        private String requestId;
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
