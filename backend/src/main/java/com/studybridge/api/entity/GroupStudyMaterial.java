package com.studybridge.api.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;

import java.time.LocalDateTime;

@Entity
@Table(name = "group_study_materials")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class GroupStudyMaterial {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    @Column(name = "group_study_material_id")
    private Long id;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "group_study_id", nullable = false)
    private GroupStudy groupStudy;

    @ManyToOne(fetch = FetchType.LAZY)
    @JoinColumn(name = "uploader_id", nullable = false)
    private User uploader;

    @Column(nullable = false, length = 100)
    private String title;

    @Column(nullable = false, length = 255)
    private String s3Key; // S3에 저장된 고유 Key

    @Column(nullable = false)
    private Long fileSize;

    @Column(length = 255)
    private String originalFileName;

    // 업로드 파일의 MIME 타입 (예: application/pdf). 기존 레코드 호환을 위해 nullable.
    @Column(length = 100)
    private String contentType;

    @CreationTimestamp
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt;
}
