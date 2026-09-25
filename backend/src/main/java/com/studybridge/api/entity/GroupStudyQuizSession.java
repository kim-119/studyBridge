package com.studybridge.api.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;

import java.time.LocalDateTime;

@Entity
@Table(name = "group_study_quiz_sessions")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class GroupStudyQuizSession {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "group_study_quiz_session_id")
    private Long id;

    @ManyToOne(fetch = FetchType.EAGER)
    @JoinColumn(name = "group_study_id", nullable = false)
    private GroupStudy groupStudy;

    @ManyToOne(fetch = FetchType.EAGER)
    @JoinColumn(name = "quiz_id", nullable = false)
    private GroupStudyQuiz quiz;

    @Column(name = "quiz_title_snapshot", nullable = false, length = 255)
    private String quizTitleSnapshot;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 20)
    @Builder.Default
    private GroupStudyQuizSessionStatus status = GroupStudyQuizSessionStatus.QUESTION;

    @Column(nullable = false)
    @Builder.Default
    private Integer currentQuestionIndex = 0;

    @Column(nullable = false)
    @Builder.Default
    private Integer questionDurationSeconds = 15;

    @Column(name = "question_order_json", columnDefinition = "TEXT", nullable = false)
    private String questionOrderJson;

    @Column(name = "current_question_id")
    private Long currentQuestionId;

    @Column(name = "question_started_at")
    private LocalDateTime questionStartedAt;

    @Column(name = "question_ends_at")
    private LocalDateTime questionEndsAt;

    @Column(name = "reveal_at")
    private LocalDateTime revealAt;

    @Column(name = "next_question_at")
    private LocalDateTime nextQuestionAt;

    @Column(name = "completed_at")
    private LocalDateTime completedAt;

    @Version
    private Long version;

    @CreationTimestamp
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt;

    @UpdateTimestamp
    @Column(name = "updated_at")
    private LocalDateTime updatedAt;
}
