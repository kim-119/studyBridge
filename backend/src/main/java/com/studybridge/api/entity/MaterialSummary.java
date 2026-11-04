package com.studybridge.api.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;

import java.time.LocalDateTime;

@Entity
@Table(name = "material_summaries")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class MaterialSummary {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long summaryId;

    @OneToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "material_id", nullable = false)
    private Material material;

    @Column(columnDefinition = "TEXT")
    private String overview;

    @Column(columnDefinition = "TEXT")
    private String coreContents;

    // Spring 품질 게이트 판정. APPROVED 만 기록(null = 게이트 OFF 시기/레거시 → 게이트 ON 에서는 캐시 재노출 금지, 재생성).
    @Column(name = "quality_status", length = 24)
    private String qualityStatus;

    @Column(name = "quality_score")
    private Double qualityScore;

    @CreationTimestamp
    private LocalDateTime createdAt;
}
