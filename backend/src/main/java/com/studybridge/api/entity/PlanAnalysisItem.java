package com.studybridge.api.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;

import java.time.LocalDateTime;

/**
 * AI 계획 분석의 문장/행동 단위 체크리스트 항목.
 *  - completed/hidden/deleted 상태가 DB에 영속화되어 새로고침 후에도 유지된다.
 *  - ddl-auto=update 로 테이블이 자동 생성된다(plan_analysis_item).
 */
@Entity
@Table(name = "plan_analysis_item")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class PlanAnalysisItem {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "item_id")
    private Long id;

    @Column(name = "analysis_id", nullable = false)
    private Long analysisId;

    @Column(name = "order_index")
    private Integer orderIndex;

    /** SENTENCE | ACTION | KEYWORD */
    @Column(length = 20)
    private String type;

    @Column(columnDefinition = "TEXT")
    private String text;

    @Column(name = "source_text", columnDefinition = "TEXT")
    private String sourceText;

    /** PDF | PLANNER | ROADMAP */
    @Column(name = "source_type", length = 20)
    private String sourceType;

    @Column(name = "page_number")
    private Integer pageNumber;       // nullable

    @Column(name = "chunk_index")
    private Integer chunkIndex;

    @Column(nullable = false)
    private boolean completed;

    @Column(nullable = false)
    private boolean hidden;

    @Column(nullable = false)
    private boolean deleted;

    @Column(name = "completed_at")
    private LocalDateTime completedAt;

    @Column(name = "deleted_at")
    private LocalDateTime deletedAt;

    @CreationTimestamp
    private LocalDateTime createdAt;

    @UpdateTimestamp
    private LocalDateTime updatedAt;
}
