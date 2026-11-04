package com.studybridge.api.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

@Getter
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class FeedbackDTO {
    private Long feedbackId;
    private Long materialId;
    private String feedbackData; // JSON (스토리보드의 1, 2, 3번 피드백 리스트)
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;   // 재생성(갱신) 시각 — 재생성은 같은 행을 갱신한다
    private String requestId;          // 생성/재생성 요청 상관 ID(조회 시 null)
    private String provider;           // AI07 metadata.provider (있을 때만)
    private String model;              // AI07 metadata.model (있을 때만)
    private String qualityStatus;      // 게이트 ON: APPROVED(노출 승인). 게이트 OFF: null(기존 응답과 동일)
    private Double qualityScore;
    private Boolean verified;
}
