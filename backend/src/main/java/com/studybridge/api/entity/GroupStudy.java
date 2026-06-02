package com.studybridge.api.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;

import java.time.LocalDate;
import java.time.LocalDateTime;

@Entity
@Table(name = "group_studies")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class GroupStudy {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "group_study_id")
    private Long id;

    @Column(nullable = false, length = 100)
    private String title;

    @Column(nullable = false, length = 200)
    private String goal;

    @Column(nullable = false, columnDefinition = "TEXT")
    private String description;

    @Column(nullable = false)
    private LocalDate startDate;

    @Column(nullable = false)
    private LocalDate endDate;

    @Column(nullable = false)
    private Integer capacity;

    @Builder.Default
    @Column(nullable = false)
    private Integer currentCount = 0;

    @Column(nullable = false)
    private Boolean isPublic;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "leader_id", nullable = false)
    private User leader;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 20)
    private GroupStudyStatus status;

    @Builder.Default
    @OneToMany(mappedBy = "groupStudy", cascade = CascadeType.ALL, orphanRemoval = true)
    private java.util.List<GroupStudyMember> members = new java.util.ArrayList<>();

    @Builder.Default
    @OneToMany(mappedBy = "groupStudy", cascade = CascadeType.ALL, orphanRemoval = true)
    private java.util.List<GroupStudyJoinApplication> applications = new java.util.ArrayList<>();

    @Builder.Default
    @OneToMany(mappedBy = "groupStudy", cascade = CascadeType.ALL, orphanRemoval = true)
    private java.util.List<GroupStudyMaterial> materials = new java.util.ArrayList<>();

    @Builder.Default
    @OneToMany(mappedBy = "groupStudy", cascade = CascadeType.ALL, orphanRemoval = true)
    private java.util.List<GroupStudyAttendance> attendances = new java.util.ArrayList<>();

    @Builder.Default
    @OneToMany(mappedBy = "groupStudy", cascade = CascadeType.ALL, orphanRemoval = true)
    private java.util.List<GroupStudyReport> reports = new java.util.ArrayList<>();

    @Builder.Default
    @OneToMany(mappedBy = "groupStudy", cascade = CascadeType.ALL, orphanRemoval = true)
    private java.util.List<GroupStudyQuiz> quizzes = new java.util.ArrayList<>();

    @CreationTimestamp
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt;

    @UpdateTimestamp
    @Column(name = "updated_at")
    private LocalDateTime updatedAt;
}
