package com.studybridge.api.entity;

import jakarta.persistence.*;
import lombok.*;

@Entity
@Table(name = "group_study_quiz_questions")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class GroupStudyQuizQuestion {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "group_study_quiz_question_id")
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "quiz_id", nullable = false)
    private GroupStudyQuiz quiz;

    @Column(nullable = false, columnDefinition = "TEXT")
    private String question; // 퀴즈 문항

    @Column(nullable = false, columnDefinition = "TEXT")
    private String optionsJson; // 객관식 문항 보기 목록 (JSON String: e.g. ["A", "B", "C", "D"])

    @Column(nullable = false)
    private Integer correctAnswer; // 정답 번호 (0-based Index)

    @Builder.Default
    @Column(nullable = false)
    private Integer timeLimitSeconds = 30; // 제한시간 (초 단위)
}
