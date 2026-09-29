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
}
