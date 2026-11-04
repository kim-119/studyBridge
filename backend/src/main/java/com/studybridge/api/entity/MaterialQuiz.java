package com.studybridge.api.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;

import java.time.LocalDateTime;

@Entity
@Table(name = "material_quizzes")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class MaterialQuiz {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long quizId;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "material_id", nullable = false)
    private Material material;

    private String difficulty;
    private Integer questionCount;
    private String pageRange;

    @Column(columnDefinition = "TEXT")
    private String quizData;

    // Spring 품질 게이트(response-quality.v1, PDF_QUIZ) 판정. APPROVED 만 기록(null = 게이트 OFF 시기/레거시).
    // 게이트 ON 에서 APPROVED 가 아닌 퀴즈는 문항·보기·해설(AI 생성 필드)을 가리고 식별자·채점 기록만 내보낸다.
    @Column(name = "quality_status", length = 24)
    private String qualityStatus;

    @Column(name = "quality_score")
    private Double qualityScore;

    @CreationTimestamp
    private LocalDateTime createdAt;
}
