package com.studybridge.api.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;

import java.time.LocalDateTime;

@Entity
@Table(name = "material_feedbacks")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class MaterialFeedback {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long feedbackId;

    @OneToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "material_id", nullable = false)
    private Material material;

    @Column(columnDefinition = "TEXT")
    private String feedbackData;

    @CreationTimestamp
    private LocalDateTime createdAt;

    // 재생성은 delete+insert 가 아니라 같은 행 갱신이다(nullable — ddl-auto 가 컬럼 추가, 기존 행은 NULL).
    @UpdateTimestamp
    @Column(name = "updated_at")
    private LocalDateTime updatedAt;

    /** 품질 게이트 판정(APPROVED 만 게이트 ON 에서 노출). NULL = 게이트 도입 전/OFF 에서 저장된 레거시 행. nullable 신규 컬럼. */
    @Column(name = "quality_status", length = 24)
    private String qualityStatus;

    @Column(name = "quality_score")
    private Double qualityScore;
}
