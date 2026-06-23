package com.studybridge.api.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;

import java.time.LocalDateTime;

@Entity
@Table(name = "materials")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class Material {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long materialId;

    @Column(nullable = false)
    private Long userId;

    @Column(nullable = false)
    private String title;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false)
    private MaterialType materialType;

    @Column(length = 1000)
    private String keywords;

    private java.time.LocalDate studyDate;

    @Column(columnDefinition = "TEXT")
    private String learningContent;

    @Column(columnDefinition = "TEXT")
    private String nextPlan;

    @Column(name = "original_file_name")
    private String originalFileName;

    @Column(name = "stored_file_name")
    private String storedFileName;

    @Column(name = "s3_file_url", length = 500)
    private String s3FileUrl;

    @Column(name = "file_size")
    private Long fileSize;

    /** 소속 폴더 id. null 이면 루트(홈) 위치. 자료보관함 폴더 기능용(ddl-auto 로 nullable 컬럼 자동 추가). */
    @Column(name = "folder_id")
    private Long folderId;

    /**
     * 구조화 자료(PLANNER 등)의 원본 식별자. PLANNER 타입에서 원본 planners.planner_id 를 가리킨다.
     * PDF/문서 자료는 null. (ddl-auto 로 nullable 컬럼 자동 추가)
     */
    @Column(name = "planner_id")
    private Long plannerId;

    /**
     * 구조화 자료(PLANNER/ROADMAP 등)의 스냅샷 JSON. PDF 로 변환하지 않고 데이터 원형 그대로 보관한다.
     * PDF/문서 자료는 null. (ddl-auto 로 nullable 컬럼 자동 추가)
     */
    @Column(name = "content_json", columnDefinition = "TEXT")
    private String contentJson;

    @Column(columnDefinition = "TEXT")
    private String extractedText;

    @Enumerated(EnumType.STRING)
    @Builder.Default
    private ExtractionStatus extractionStatus = ExtractionStatus.PENDING;

    @CreationTimestamp
    private LocalDateTime uploadedAt;

    @UpdateTimestamp
    private LocalDateTime updatedAt;

    /**
     * 영속 시점 타입 불변식(회귀 방어).
     *  · 플래너/구조화 자료(plannerId 또는 contentJson 보유)는 절대 PDF 타입으로 저장되지 않는다.
     *    → 과거 "플래너가 자료보관함에 PDF로 저장되던" 오염(2026-06-23 복구)을 영속 경계에서 차단한다.
     *  · PLANNER 타입은 파일이 없는 구조화 자료이므로 PDF 파일 메타가 남아 있으면 방어적으로 정리한다.
     * 어느 서비스가 저장하든(MaterialService/PlannerService 등) 이 가드를 통과해야 한다.
     */
    @PrePersist
    @PreUpdate
    private void enforceTypeInvariant() {
        boolean structured = plannerId != null || (contentJson != null && !contentJson.isBlank());
        if (structured && materialType == MaterialType.PDF) {
            throw new IllegalStateException(
                    "플래너/구조화 자료는 PDF 타입으로 저장할 수 없습니다. (title=" + title + ")");
        }
        if (materialType == MaterialType.PLANNER) {
            // 구조화 PLANNER 자료에는 PDF 파일 메타가 존재하면 안 된다 → 잔재 제거
            originalFileName = null;
            storedFileName = null;
            s3FileUrl = null;
            fileSize = null;
        }
    }

    @OneToOne(mappedBy = "material", cascade = CascadeType.ALL, orphanRemoval = true)
    private MaterialSummary summary;

    @OneToOne(mappedBy = "material", cascade = CascadeType.ALL, orphanRemoval = true)
    private MaterialFeedback feedback;

    @OneToOne(mappedBy = "material", cascade = CascadeType.ALL, orphanRemoval = true)
    private MaterialMemo memo;

    @OneToOne(mappedBy = "material", cascade = CascadeType.ALL, orphanRemoval = true)
    private Roadmap roadmap;

    @Builder.Default
    @OneToMany(mappedBy = "material", cascade = CascadeType.ALL, orphanRemoval = true)
    private java.util.List<MaterialQuiz> quizzes = new java.util.ArrayList<>();

    @Builder.Default
    @OneToMany(mappedBy = "material", cascade = CascadeType.ALL, orphanRemoval = true)
    private java.util.List<MaterialQuestion> questions = new java.util.ArrayList<>();
}