package com.studybridge.api.dto;

import lombok.Builder;
import lombok.Getter;

import java.util.List;
import java.util.Map;

/**
 * AI 핵심 요약 노트(전공 분야·핵심 객체 중심) 조회 응답.
 * 리스트/객체 필드는 파싱된 형태로 내려준다(프론트가 그대로 렌더).
 */
@Getter
@Builder
public class StudyNoteAnalysisDTO {
    private Long materialId;
    private String status;            // PENDING | RUNNING | SUCCESS | FAILED
    private boolean fallback;         // ai07 200 정보부족 fallback 여부(status=SUCCESS 와 공존 가능)
    private String fallbackReason;    // 예: INSUFFICIENT_INPUT
    private String mode;              // DOMAIN_OBJECT_CENTERED_STUDY_NOTE
    private String domain;
    private String domainLabel;
    private String coreObject;
    private String coreObjectLabel;
    private String disclaimer;
    private String documentOverview;
    private List<String> keywords;
    private List<String> coreContents;
    private List<Map<String, Object>> detailedCoreContents; // [{title, content}]
    private List<Map<String, Object>> pageSummaries;        // [{page,title,detectedTextSource,pageOverview,keyConcepts,summaryBullets,studyFocus}]
    private List<String> studyPoints;
    private List<String> aiStudyQuestions;
    private List<Map<String, Object>> wikiSummaries;        // [{title, summary}]
    private List<String> limitations;
    private String errorMessage;
    // 품질 게이트(Phase D, 게이트 ON 에서만 채움 — OFF 응답 형태 불변). qualityRedacted=true: 미검증 저장본이라 AI 필드를 가림.
    @com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
    private String qualityStatus;
    @com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
    private Boolean qualityRedacted;
}
