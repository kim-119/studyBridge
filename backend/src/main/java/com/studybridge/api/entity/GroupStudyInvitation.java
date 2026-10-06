package com.studybridge.api.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;

import java.time.LocalDateTime;

/**
 * 비공개 그룹스터디 초대 링크.
 *  · token 은 SecureRandom 32바이트(base64url, 43자) — 추측 불가. 그룹당 활성 링크는 1개(재생성 시 이전 링크 비활성).
 *  · 유효 조건: active && (expiresAt == null || now < expiresAt) && (maxUses == null || usedCount < maxUses) && 그룹 존재.
 *  · 그룹 삭제 시 GroupStudy.invitations cascade 로 함께 삭제된다(삭제된 그룹의 토큰은 404).
 */
@Entity
@Table(name = "group_study_invitations",
        uniqueConstraints = @UniqueConstraint(name = "uk_group_study_invitations_token", columnNames = "token"),
        indexes = @Index(name = "idx_group_study_invitations_group", columnList = "group_study_id"))
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class GroupStudyInvitation {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "group_study_invitation_id")
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "group_study_id", nullable = false)
    private GroupStudy groupStudy;

    @Column(name = "token", nullable = false, length = 64)
    private String token;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "created_by", nullable = false)
    private User createdBy;

    @CreationTimestamp
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt;

    @Column(name = "expires_at")
    private LocalDateTime expiresAt;

    @Builder.Default
    @Column(name = "active", nullable = false)
    private boolean active = true;

    @Builder.Default
    @Column(name = "used_count", nullable = false)
    private int usedCount = 0;

    @Column(name = "max_uses")
    private Integer maxUses;

    public boolean isExpired(LocalDateTime now) {
        return expiresAt != null && !now.isBefore(expiresAt);
    }

    public boolean isExhausted() {
        return maxUses != null && usedCount >= maxUses;
    }

    public boolean isUsable(LocalDateTime now) {
        return active && !isExpired(now) && !isExhausted();
    }
}
