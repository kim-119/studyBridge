package com.studybridge.api.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;

import java.time.LocalDateTime;

/**
 * 오답노트 메타데이터. PDF 본문은 S3에 두고 DB에는 메타만 보관한다(요구 H).
 *  - sourceMaterialId : 원본 자료(PDF) id
 *  - quizId           : 오답노트를 만든 퀴즈(MaterialQuiz) id (= 프론트가 보내는 quizSessionId)
 *  - archiveMaterialId: 자료보관함 노출용으로 자동 생성한 Material(REVIEW_NOTE) id
 *  - s3Key            : 오답노트 PDF의 S3 key
 *  - retryJson        : 다시 풀기용 재출제 문제 JSON
 *  - retryResultJson  : 다시 풀기(문제당 1회) 채점 결과 JSON. 없으면 재풀이 기록이 없는 것이다.
 */
@Entity
@Table(name = "review_notes")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class ReviewNote {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long reviewNoteId;

    @Column(nullable = false)
    private Long userId;

    @Column(nullable = false)
    private Long sourceMaterialId;

    private String sourceTitle;

    private Long quizId;

    private Long archiveMaterialId;

    @Column(nullable = false)
    private String title;

    @Column(name = "s3_key", length = 500)
    private String s3Key;

    private Integer wrongCount;

    // 미응답(안 푼) 문제 수 — 복습 대상에 포함. (ddl-auto=update 로 nullable 컬럼 추가)
    private Integer unansweredCount;

    // easy | medium | hard (프론트 DIFFICULTY_LABEL과 동기화)
    private String difficulty;

    @Column(columnDefinition = "TEXT")
    private String memo;

    @Column(columnDefinition = "TEXT")
    private String retryJson;

    // 다시 풀기 결과(문제당 정확히 1회). [{index,userAnswer,correct,answeredAt}]
    // 재풀이는 1회뿐이므로 시도 횟수/힌트 같은 필드는 두지 않는다. (ddl-auto=update 로 컬럼 추가)
    @Column(columnDefinition = "TEXT")
    private String retryResultJson;

    // ── 복습 필요 판정의 source of truth(브라우저 임시 state 아님) ──────────────────
    //  · 오답노트 생성(=복습 세션 완료) 트랜잭션에서 난이도/오답수 기반 추천일을 결정적으로 저장한다(ai07 무관).
    //  · "복습 필요" AI 분석 결과(reviewNeededText)도 같은 row 에 저장돼 새로고침 후 유지된다.
    //  · ddl-auto=update 로 nullable 컬럼 자동 추가(기존 row 는 null → 조회 시 서비스 폴백 계산).
    @Column(name = "recommend_review_in_days")
    private Integer recommendReviewInDays;

    @Column(name = "recommended_review_date")
    private java.time.LocalDate recommendedReviewDate;

    @Column(name = "review_reason", length = 300)
    private String reviewReason;

    @Column(name = "review_needed_text", columnDefinition = "TEXT")
    private String reviewNeededText;

    @Column(name = "review_needed_at")
    private LocalDateTime reviewNeededAt;

    @CreationTimestamp
    private LocalDateTime createdAt;
}
