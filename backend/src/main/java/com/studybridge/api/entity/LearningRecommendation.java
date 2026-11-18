package com.studybridge.api.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;

import java.time.LocalDateTime;

/**
 * 학습 추천 결과 1건(사용자에게 제안된 후보) + 승인 상태.
 *
 * <pre>
 *  GENERATED ──accept──▶ ACCEPTED ──complete──▶ COMPLETED
 *      │
 *      └────reject────▶ REJECTED
 *  DISCARDED = AI 후보가 EC2 검증(근거 ID/목차/DAG)에서 탈락 — 사용자에게 제시하지 않음(환각률 측정용)
 * </pre>
 * 기존 테이블(learning_loop_events 는 append-only 이벤트 로그)로는 상태 전이·중복 방지를 표현할 수 없어 새 테이블을 둔다.
 * 모든 조회는 user_id 로 제한한다. (user_id, dedup_key) unique 로 같은 후보의 중복 저장을 막는다.
 */
@Entity
@Table(name = "learning_recommendations",
        uniqueConstraints = @UniqueConstraint(name = "uk_learning_rec_user_dedup", columnNames = {"user_id", "dedup_key"}),
        indexes = {
                @Index(name = "idx_learning_rec_user_planner", columnList = "user_id, planner_id"),
                @Index(name = "idx_learning_rec_user_material", columnList = "user_id, material_id")
        })
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class LearningRecommendation {

    public enum Status { GENERATED, ACCEPTED, REJECTED, COMPLETED, DISCARDED }

    /** 추천 출처(기능 책임 분리). */
    public enum Source { USER_PLANNER, ROADMAP_PLANNER, DOCUMENT }

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "recommendation_id")
    private Long id;

    @Column(name = "user_id", nullable = false)
    private Long userId;

    @Enumerated(EnumType.STRING)
    @Column(name = "source_kind", nullable = false, length = 20)
    private Source sourceKind;

    /** NEXT_CHAPTER / CONCEPT_REVIEW / PRACTICE / PREREQUISITE_GAP / APPLICATION / WRONG_ANSWER_REVIEW / ROADMAP_NODE / DEEP_DIVE ... */
    @Column(name = "recommendation_type", nullable = false, length = 40)
    private String recommendationType;

    @Column(name = "planner_id")
    private Long plannerId;

    @Column(name = "material_id")
    private Long materialId;

    /** 로드맵 그룹 키(sourceRoadmapId 또는 m{sourceMaterialId}). */
    @Column(name = "roadmap_key", length = 40)
    private String roadmapKey;

    /** 로드맵 노드 키(예: w3d2) 또는 대상 장 번호 등 후보 식별자. */
    @Column(name = "target_key", length = 60)
    private String targetKey;

    @Column(nullable = false, length = 200)
    private String title;

    @Column(columnDefinition = "TEXT")
    private String reason;

    /** [{type, id, label}] — 근거 데이터 ID 목록(JSON). */
    @Column(name = "evidence_json", columnDefinition = "TEXT")
    private String evidenceJson;

    /** 순위/진입 조건 계산 근거(JSON) — 로드맵 노드 점수, eligibility 등. */
    @Column(name = "score_json", columnDefinition = "TEXT")
    private String scoreJson;

    @Column(name = "verification_required", nullable = false)
    private boolean verificationRequired;

    @Column(name = "verification_note", length = 300)
    private String verificationNote;

    /** RULE(EC2 결정적) | AI(AI07 후보 + EC2 검증 통과) */
    @Column(nullable = false, length = 10)
    private String generator;

    @Column(name = "model_provider", length = 40)
    private String modelProvider;

    @Column(name = "model_name", length = 80)
    private String modelName;

    @Column(name = "contract_version", length = 20)
    private String contractVersion;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 20)
    private Status status;

    @Column(name = "discard_reason", length = 60)
    private String discardReason;

    @Column(name = "dedup_key", nullable = false, length = 200)
    private String dedupKey;

    /** 같은 후보가 다시 제시된 횟수(중복률 측정). */
    @Column(name = "presented_count", nullable = false)
    private int presentedCount;

    @Column(name = "accepted_planner_id")
    private Long acceptedPlannerId;

    @Column(name = "request_id", length = 64)
    private String requestId;

    @CreationTimestamp
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt;

    @UpdateTimestamp
    @Column(name = "updated_at")
    private LocalDateTime updatedAt;

    @Column(name = "decided_at")
    private LocalDateTime decidedAt;

    @Column(name = "completed_at")
    private LocalDateTime completedAt;
}
