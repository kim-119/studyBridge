package com.studybridge.api.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.*;

import java.time.LocalDateTime;

/**
 * 학습일지 관련 DTO 모음.
 * - 응답에는 메타데이터 + (상세 조회 시에만) S3에서 읽은 원문 content를 담는다.
 * - 검증 실패 응답에는 원문을 담지 않는다.
 */
public class StudyJournalDTO {

    private StudyJournalDTO() {}

    /** 학습일지 저장 요청. */
    @Getter
    @Setter
    @NoArgsConstructor
    @AllArgsConstructor
    public static class CreateRequest {
        private String content;
    }

    /** 목록/저장 성공 응답(메타데이터). content는 상세 조회에서만 채운다. */
    @Getter
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class Response {
        private Long id;
        private Long materialId;
        private String type;
        private String s3Key;
        private String validationDecision;
        private String validationCategory;
        private String relationType;
        private String relationPath;
        private Double confidence;
        private Long byteSize;
        private String content;   // 상세 조회 시에만 S3에서 읽어 채움
        private LocalDateTime createdAt;
        private LocalDateTime updatedAt;
        // 품질 게이트(게이트 ON 에서만 — NON_NULL 이라 OFF 응답 불변). qualityRedacted=true: 미검증 AI 판정 문구(relationPath)를 가림.
        private String qualityStatus;
        private Boolean qualityRedacted;
    }

    /** 검증 실패(REQUEST_REVISION/BLOCK) 응답. 원문 미포함. */
    @Getter
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    @JsonInclude(JsonInclude.Include.NON_NULL)
    public static class RejectionResponse {
        private String decision;
        private String category;
        private String relationType;
        private String relationPath;
        private String reason;
        private String suggestion;
        // 품질 게이트(게이트 ON 에서만). qualityRedacted=true: AI 사유/제안이 평가를 통과하지 못해 Spring 고정 문구로 바꿨다(판정 자체는 그대로).
        private String qualityStatus;
        private Boolean qualityRedacted;
    }
}
