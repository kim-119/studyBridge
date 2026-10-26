package com.studybridge.api.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;

import java.time.LocalDateTime;

/**
 * 마인드맵(자료보관함 MINDMAP material) 노드별 사용자 메모.
 *  · 기존 Material.contentJson(저장 그래프)을 건드리지 않고 별도 테이블에 보관 → 구버전 데이터 호환.
 *  · (user_id, material_id, node_id) 유니크 → 사용자별/자료별/노드별 단일 최신 메모.
 *  · ddl-auto=update 로 신규 테이블 자동 생성(운영 RDS 안전: 기존 테이블 변경 없음).
 */
@Entity
@Table(
        name = "mindmap_node_memo",
        uniqueConstraints = @UniqueConstraint(
                name = "uk_mindmap_node_memo_user_material_node",
                columnNames = {"user_id", "material_id", "node_id"}
        )
)
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class MindmapNodeMemo {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long nodeMemoId;

    @Column(name = "user_id", nullable = false)
    private Long userId;

    @Column(name = "material_id", nullable = false)
    private Long materialId;

    @Column(name = "node_id", nullable = false, length = 255)
    private String nodeId;

    @Column(name = "node_label", length = 500)
    private String nodeLabel;

    @Column(name = "content", columnDefinition = "TEXT", nullable = false)
    private String content;

    @CreationTimestamp
    @Column(updatable = false)
    private LocalDateTime createdAt;

    @UpdateTimestamp
    private LocalDateTime updatedAt;
}
