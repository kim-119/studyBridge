package com.studybridge.api.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

/**
 * 오답노트 응답 DTO. 프론트 ReviewNotesPage 가 기대하는 필드명에 맞춘다.
 */
@Getter
@Builder
@NoArgsConstructor
@AllArgsConstructor
public class ReviewNoteDTO {
    private Long id;
    private String title;
    private String sourceName;             // 원본 자료 제목
    private String originalMaterialTitle;  // 동일값(스펙 호환 별칭)
    private Long sourceMaterialId;
    private Long quizId;                    // 생성에 사용된 퀴즈(quizSessionId) — 프론트 "이미 생성됨" 판별용
    private Long archiveMaterialId;         // 자료보관함 노출용 Material id
    private Integer wrongCount;
    private Integer unansweredCount;       // 미응답(안 푼) 문제 수
    private Integer reviewCount;           // 복습 필요 수 = wrongCount + unansweredCount
    private String difficulty;             // easy | medium | hard
    private String memo;
    private String aiStatus;               // PENDING | DONE | FALLBACK | null(구버전) — AI 해설 보강 진행 상태
    private String pdfUrl;                 // S3 presigned URL (열람/다운로드용)
    private String downloadUrl;            // 다운로드 API 경로 (/api/review-notes/{id}/download)
    // ── 복습 필요/일정(DB 기준) ──
    private Integer recommendReviewInDays;         // 추천 복습 간격(일)
    private java.time.LocalDate recommendedReviewDate; // DB 저장 추천 복습일(source of truth)
    private String reviewReason;                   // 추천 근거(결정적 규칙)
    private String reviewNeededText;               // 저장된 "복습 필요" AI 분석(없으면 null)
    private Boolean reviewNeeded;                  // 오늘 기준 복습 필요(추천일 도래 & 미등록/미완료)
    private Boolean reviewScheduled;               // 주간 일정(todos)에 이미 등록됨
    private Long reviewTodoId;                     // 등록된 주간 일정 row id
    private java.time.LocalDate reviewScheduledDate; // 등록된 주간 일정 날짜
    private Boolean reviewCompleted;               // 등록된 주간 일정 완료 여부
    private LocalDateTime createdAt;
}
