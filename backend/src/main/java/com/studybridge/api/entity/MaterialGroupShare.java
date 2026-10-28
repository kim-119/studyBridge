package com.studybridge.api.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;

import java.time.LocalDateTime;

/**
 * 개인 자료(Material)를 스터디 그룹에 명시적으로 공유한 관계. 퀴즈 응시·결과·랭킹을 그 그룹의 JOINED 멤버에게 허용하는 유일한 근거다.
 * 그룹 자료(GroupStudyMaterial)와는 별개이며 ID 를 섞지 않는다. 공유는 자료 소유자가, 자신이 JOINED 멤버인 그룹에만 만든다.
 * 소유자가 그룹을 떠나거나 강퇴되면 공유는 효력을 잃는다(접근 판정 시 소유자 멤버십을 함께 확인). ddl-auto=update 로 생성된다.
 */
@Entity
@Table(name = "material_group_shares",
        uniqueConstraints = @UniqueConstraint(name = "uk_material_group_share", columnNames = {"material_id", "group_study_id"}),
        indexes = @Index(name = "idx_material_group_share_group", columnList = "group_study_id"))
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class MaterialGroupShare {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "share_id")
    private Long id;

    @Column(name = "material_id", nullable = false)
    private Long materialId;

    @Column(name = "group_study_id", nullable = false)
    private Long groupStudyId;

    @Column(name = "shared_by_user_id", nullable = false)
    private Long sharedByUserId;

    @CreationTimestamp
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt;
}
