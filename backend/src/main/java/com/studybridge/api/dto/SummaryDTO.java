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
public class SummaryDTO {
    private Long summaryId;
    private Long materialId;
    private String overview;
    private String coreContents; // JSON
    private String summary;
    private List<String> key_points;
    private String gpt_raw;
    private List<String> keywords;
    private List<Map<String, Object>> sections;
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
}
