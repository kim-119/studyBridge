package com.studybridge.api.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;

import java.time.LocalDateTime;

/**
 * 자료(PDF) 전공 분야·핵심 객체 중심 학습 노트 분석 결과.
 * 기존 MaterialSummary(요약)와 별도 테이블이며 기존 material id 체계/요약/퀴즈/로드맵/메모를 건드리지 않는다.
 * status: PENDING(대기) / RUNNING(생성중) / SUCCESS / FAILED. 리스트·객체 필드는 JSON 문자열(TEXT)로 보관.
 * ddl-auto=update 로 material_study_note_analysis 테이블 자동 생성.
 */
@Entity
@Table(name = "material_study_note_analysis",
        uniqueConstraints = @UniqueConstraint(name = "uk_study_note_material", columnNames = "material_id"))
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class MaterialStudyNoteAnalysis {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "material_id", nullable = false)
    private Long materialId;

    @Column(name = "user_id", nullable = false)
    private Long userId;

    @Column(nullable = false, length = 20)
    private String status; // PENDING | RUNNING | SUCCESS | FAILED

    // ai07 200 fallback(정보 부족) 여부. status=SUCCESS 이면서 fallback=true 인 경우가 있음.
    @Builder.Default
    private Boolean fallback = false;

    private String fallbackReason; // 예: INSUFFICIENT_INPUT

    private String domain;
    private String domainLabel;
    private String coreObject;
    private String coreObjectLabel;

    @Column(columnDefinition = "TEXT")
    private String disclaimer;

    @Column(columnDefinition = "TEXT")
    private String documentOverview;

    @Column(columnDefinition = "TEXT")
    private String keywordsJson;

    @Column(columnDefinition = "TEXT")
    private String coreContentsJson;

    @Column(columnDefinition = "TEXT")
    private String detailedCoreContentsJson;

    @Column(columnDefinition = "TEXT")
    private String pageSummariesJson;

    @Column(columnDefinition = "TEXT")
    private String studyPointsJson;

    @Column(columnDefinition = "TEXT")
    private String aiStudyQuestionsJson;

    @Column(columnDefinition = "TEXT")
    private String wikiSummariesJson;

    @Column(columnDefinition = "TEXT")
    private String limitationsJson;

    @Column(columnDefinition = "TEXT")
    private String errorMessage;

    @CreationTimestamp
    private LocalDateTime createdAt;

    @UpdateTimestamp
    private LocalDateTime updatedAt;
}
