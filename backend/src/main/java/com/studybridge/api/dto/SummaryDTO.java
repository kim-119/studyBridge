package com.studybridge.api.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

@Getter
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class SummaryDTO {
    private Long summaryId;
    private Long materialId;
    private String overview;
    private String coreContents; // JSON
}
