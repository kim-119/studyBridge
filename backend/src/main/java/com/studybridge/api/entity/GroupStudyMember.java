package com.studybridge.api.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;

import java.time.LocalDateTime;

@Entity
@Table(name = "group_study_members", uniqueConstraints = {
        @UniqueConstraint(columnNames = {"group_study_id", "user_id"})
})
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class GroupStudyMember {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "group_study_member_id")
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "group_study_id", nullable = false)
    private GroupStudy groupStudy;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "user_id", nullable = false)
    private User user;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 20)
    private GroupStudyRole role; // LEADER, MEMBER

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 20)
    private GroupStudyMemberStatus status; // JOINED, KICKED

    @Builder.Default
    @Column(nullable = false)
    private Integer points = 0; // 그룹 내에서 획득한 포인트 (퀴즈 게임용)

    @CreationTimestamp
    @Column(name = "joined_at", updatable = false)
    private LocalDateTime joinedAt;
}
