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

    @Column(name = "hashtags", length = 200)
    private String hashtags;

    @Column(name = "cover_image_key", length = 300)
    private String coverImageKey;

    // ── 운영 정책(2026-09-30 추가). 모두 additive + DB default → 기존 row 는 GENERAL/240분/OFF 로 읽힌다.
    //    ddl-auto=update 가 컬럼을 추가하고, 운영(RDS) 수동 적용 스크립트는 db/migration/V20260930__group_study_settings.sql.
    @Builder.Default
    @Enumerated(EnumType.STRING)
    @Column(name = "study_type", nullable = false, columnDefinition = "varchar(20) default 'GENERAL'")
    private GroupStudyType studyType = GroupStudyType.GENERAL;

    // 하루 목표 공부시간(분). 화면 문자열이 아닌 숫자 저장. 허용 범위는 GroupStudySettingsPolicy 가 단일 관리.
    @Builder.Default
    @Column(name = "target_study_minutes", nullable = false, columnDefinition = "integer default 240")
    private Integer targetStudyMinutes = 240;

    // 가입 질문: enabled=false 이면 joinQuestion 은 항상 null 로 정규화한다.
    @Builder.Default
    @Column(name = "join_question_enabled", nullable = false, columnDefinition = "boolean default false")
    private Boolean joinQuestionEnabled = false;

    @Column(name = "join_question", length = 200)
    private String joinQuestion;

    // 그룹 닉네임 규칙 "안내 문자열"(실제 그룹 내 별칭은 GroupStudyMember.nickname). enabled=false 이면 null.
    @Builder.Default
    @Column(name = "nickname_rule_enabled", nullable = false, columnDefinition = "boolean default false")
    private Boolean nicknameRuleEnabled = false;

    @Column(name = "nickname_rule", length = 100)
    private String nicknameRule;

    // 스터디 아이콘 식별자(추후 사용자 제공 asset 연결용). 현재는 null → 클라이언트 기본 아이콘.
    @Column(name = "study_icon_id", length = 50)
    private String studyIconId;

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
