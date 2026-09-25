package com.studybridge.api.dto;

import com.studybridge.api.entity.ExtractionStatus;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

@Getter
@Builder
public class MaterialDTO {

    @Getter
    @NoArgsConstructor
    public static class StudyLogRequest {
        private String title;
        private String keywords;
        private java.time.LocalDate studyDate;
        private String learningContent;
        private String nextPlan;
        private Long folderId;
    }

    /** 마인드맵(Obsidian Graph) 저장 요청. PDF 가 아니라 그래프 JSON 으로 보관한다. */
    @Getter
    @NoArgsConstructor
    public static class MindMapRequest {
        private String title;
        private String keywords;
        private Long folderId;
        private String sourceType;
        private String sourceId;
        private Integer nodeCount;
        private Integer edgeCount;
        private String rawGraphJson;
        private String obsidianMarkdown;
        private String canvasJson;
    }

    @Getter
    @NoArgsConstructor
    public static class MoveRequest {
        private Long folderId; // null 이면 루트(홈)로 이동
    }

    @Getter
    @NoArgsConstructor
    public static class UpdateRequest {
        private String title;
        private String keywords;
        private String learningContent;
        private String nextPlan;
    }

    private Long materialId;
    private String title;
    private com.studybridge.api.entity.MaterialType materialType;
    private String keywords;
    private Long folderId;

    // 구조화 자료(PLANNER/ROADMAP) — PDF 가 아니라 데이터 원형으로 보관/표시한다.
    private Long plannerId;
    private String contentJson;

    // 학습일지
    private java.time.LocalDate studyDate;
    private String learningContent;
    private String nextPlan;

    // 공통 및 파일 관련
    private String originalFileName;
    private Long fileSize;
    private ExtractionStatus extractionStatus;
    private String s3PresignedUrl;
    private String plannerPdfS3Key;
    private LocalDateTime uploadedAt;
    private String extractedText;
    private LocalDateTime updatedAt;
}