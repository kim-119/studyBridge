package com.studybridge.api.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;

import java.time.LocalDateTime;

/**
 * AI 계획 분석 결과(헤더). PDF/플래너 텍스트를 문장/행동 단위로 분해한 분석의 메타.
 *  - 실제 체크리스트 항목은 {@link PlanAnalysisItem} 에 저장된다.
 *  - ddl-auto=update 로 테이블이 자동 생성된다(plan_analysis).
 */
@Entity
@Table(name = "plan_analysis")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class PlanAnalysis {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "analysis_id")
    private Long id;

    @Column(name = "user_id", nullable = false)
    private Long userId;

    @Column(name = "material_id", nullable = false)
    private Long materialId;

    @Column(name = "planner_id")
    private Long plannerId;            // nullable — 연결된 대표 플래너

    /** PDF | PLANNER | ROADMAP | MIXED */
    @Column(name = "source_type", length = 20)
    private String sourceType;

    @Column(columnDefinition = "TEXT")
    private String summary;

    @Column(columnDefinition = "TEXT")
    private String recommendation;

    @Column(name = "planner_analysis_json", columnDefinition = "TEXT")
    private String plannerAnalysisJson;

    @CreationTimestamp
    private LocalDateTime createdAt;

    @UpdateTimestamp
    private LocalDateTime updatedAt;
}
