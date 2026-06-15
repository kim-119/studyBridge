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

    @Column(columnDefinition = "TEXT")
    private String extractedText;

    @Enumerated(EnumType.STRING)
    @Builder.Default
    private ExtractionStatus extractionStatus = ExtractionStatus.PENDING;

    @CreationTimestamp
    private LocalDateTime uploadedAt;

    @UpdateTimestamp
    private LocalDateTime updatedAt;

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