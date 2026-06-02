package com.studybridge.api.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;

@Entity
@Table(name = "study_groups")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class StudyGroup {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "study_group_id")
    private Long id;

    @OneToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "study_recruitment_id", nullable = false)
    private StudyRecruitment studyRecruitment; // 생성 주체가 된 모집글 참조

    @Column(nullable = false, length = 255)
    private String title; // 스터디방 명칭

    @Builder.Default
    @Column(nullable = false, length = 20)
    private String status = "ACTIVE"; // ACTIVE, COMPLETED

    @ManyToMany(fetch = FetchType.LAZY)
    @Builder.Default
    private List<User> members = new ArrayList<>(); // 최종 합류된 멤버 목록 (유저와 다이렉트 ManyToMany 매핑)

    @CreationTimestamp
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt;
}
