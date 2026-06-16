package com.studybridge.api.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;

import java.time.LocalDate;
import java.time.LocalDateTime;

/**
 * 학습 왕복 루프(Learning Loop) 공통 이벤트.
 *
 * AI 생성물이 화면에 한 번 표시되고 끝나는 것이 아니라, 사용자의 학습 행동과 함께 DB에 저장되어
 * 다음 AI 호출(요약/퀴즈/오답복습/채팅 등)의 근거(컨텍스트)가 되도록 추적 기록을 남긴다.
 *
 *  - 소유권은 userId 로 검증한다(다른 엔티티와 동일 컨벤션).
 *  - 모든 부가 컬럼은 nullable. ddl-auto=update 로 테이블/컬럼이 자동 생성되며 기존 데이터에 영향 없음.
 *  - 기록은 항상 best-effort: 이벤트 저장 실패가 본래 학습 기능을 깨뜨리면 안 된다.
 */
@Entity
@Table(name = "learning_loop_events", indexes = {
        @Index(name = "idx_lle_user_material", columnList = "user_id, material_id"),
        @Index(name = "idx_lle_user_source", columnList = "user_id, source_type, source_id"),
        @Index(name = "idx_lle_user_created", columnList = "user_id, created_at")
})
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class LearningLoopEvent {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "user_id", nullable = false)
    private Long userId;

    @Enumerated(EnumType.STRING)
    @Column(name = "event_type", nullable = false, length = 40)
    private LearningEventType eventType;

    @Enumerated(EnumType.STRING)
    @Column(name = "source_type", length = 20)
    private LearningSourceType sourceType;

    @Column(name = "source_id")
    private Long sourceId;

    // 연결 키 (있는 것만 채움)
    @Column(name = "material_id")
    private Long materialId;
    @Column(name = "document_id")
    private Long documentId;
    @Column(name = "room_id")
    private Long roomId;
    @Column(name = "planner_id")
    private Long plannerId;
    @Column(name = "wrong_note_id")
    private Long wrongNoteId;
    @Column(name = "quiz_id")
    private Long quizId;
    @Column(name = "question_id")
    private Long questionId;

    // 학습 내용/AI 산출물 (검색·컨텍스트 재사용용)
    @Column(name = "input_text", columnDefinition = "TEXT")
    private String inputText;
    @Column(name = "ai_output_summary", columnDefinition = "TEXT")
    private String aiOutputSummary;
    @Column(name = "ai_output_json", columnDefinition = "TEXT")
    private String aiOutputJson;

    @Column(name = "user_action", length = 100)
    private String userAction;
    @Column(name = "user_memo", columnDefinition = "TEXT")
    private String userMemo;

    // 채점/난이도/복습 추천 보조값
    @Column(name = "is_correct")
    private Boolean isCorrect;
    @Column(name = "score")
    private Integer score;
    @Column(name = "difficulty", length = 20)
    private String difficulty;
    @Column(name = "recommend_review_in_days")
    private Integer recommendReviewInDays;
    @Column(name = "recommended_review_date")
    private LocalDate recommendedReviewDate;

    @CreationTimestamp
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt;

    @UpdateTimestamp
    @Column(name = "updated_at")
    private LocalDateTime updatedAt;
}
