package com.studybridge.api.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class GroupStudyMaterialDTO {
    private Long id;
    private Long groupStudyId;
    private String title;
    private String s3Key;
    private Long fileSize;
    private String originalFileName;
    private String presignedUrl;
    private Long uploaderId;
    private String uploaderName;
    private LocalDateTime createdAt;
}
