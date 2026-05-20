package com.studybridge.api.dto;

import com.studybridge.api.entity.ExtractionStatus;
import lombok.Builder;
import lombok.Getter;

import java.time.LocalDateTime;

@Getter
@Builder
public class MaterialDTO {
    private Long materialId;
    private String originalFileName;
    private Long fileSize;
    private ExtractionStatus extractionStatus;
    private String s3PresignedUrl;
    private LocalDateTime uploadedAt;
    private String extractedText;
    private LocalDateTime updatedAt;
}