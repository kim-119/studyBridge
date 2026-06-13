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

    @CreationTimestamp
    private LocalDateTime createdAt;
}
