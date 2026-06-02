package com.studybridge.api.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;
import java.time.LocalDateTime;

@Entity
@Table(name = "study_recruitments")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class StudyRecruitment {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "study_recruitment_id")
    private Long id;

    @Column(nullable = false, length = 255)
    private String title; // 모집글 제목

    @Column(nullable = false, columnDefinition = "TEXT")
    private String objective; // 스터디 목표 및 설명

    @Column(nullable = false)
    private LocalDateTime deadline; // 모집 마감일

    @Column(name = "max_members", nullable = false)
    private Integer maxMembers; // 모집 정원 (최대 인원)

    @Builder.Default
    @Column(name = "current_members", nullable = false)
    private Integer currentMembers = 1; // 현재 승인된 인원 (리더 본인 기본 포함 1)

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "leader_id", nullable = false)
    private User leader; // 모집글 작성자 (스터디 리더)

    @Builder.Default
    @Column(nullable = false, length = 20)
    private String status = "RECRUITING"; // RECRUITING, COMPLETED, CANCELLED

    @CreationTimestamp
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt;
}
