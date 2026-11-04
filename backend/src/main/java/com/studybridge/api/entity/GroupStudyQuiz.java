package com.studybridge.api.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;

import java.time.LocalDateTime;

@Entity
@Table(name = "group_study_quizzes")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class GroupStudyQuiz {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "group_study_quiz_id")
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "group_study_id", nullable = false)
    private GroupStudy groupStudy;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "creator_id", nullable = false)
    private User creator;

    @Column(nullable = false, length = 100)
    private String title;

    @Builder.Default
    @Column(nullable = false)
    private Integer rewardPoints = 10; // 정답 시 제공할 스터디 포인트

    @Builder.Default
    @OneToMany(mappedBy = "quiz", cascade = CascadeType.ALL, orphanRemoval = true)
    private java.util.List<GroupStudyQuizQuestion> questions = new java.util.ArrayList<>();

    // Spring 품질 게이트(response-quality.v1, PDF_QUIZ) 판정. APPROVED 만 기록(null = 게이트 OFF 시기/레거시).
    // 게이트 ON 에서 APPROVED 가 아닌 퀴즈는 목록에서 AI 생성 제목을 가린다.
    @Column(name = "quality_status", length = 24)
    private String qualityStatus;

    @Column(name = "quality_score")
    private Double qualityScore;

    @CreationTimestamp
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt;
}
