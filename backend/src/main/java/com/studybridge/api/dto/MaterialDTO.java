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
    }

    @Getter
    @NoArgsConstructor
    public static class UpdateRequest {
        private String title;
        private String keywords;
    }

    private Long materialId;
    private String title;
    private com.studybridge.api.entity.MaterialType materialType;
    private String keywords;
    
    // 학습일지
    private java.time.LocalDate studyDate;
    private String learningContent;
    private String nextPlan;

    // 공통 및 파일 관련
    private String originalFileName;
    private Long fileSize;
    private ExtractionStatus extractionStatus;
    private String s3PresignedUrl;
    private LocalDateTime uploadedAt;
    private String extractedText;
    private LocalDateTime updatedAt;
}