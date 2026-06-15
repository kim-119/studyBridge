package com.studybridge.api.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;

import java.time.LocalDateTime;

/**
 * 학습일지 메타데이터.
 *
 * 중요: 학습일지 원문은 이 테이블에 저장하지 않는다. 원문은 검증(ACCEPT) 통과 후 S3에 JSON으로 저장하고,
 * 여기에는 S3 객체를 찾기 위한 메타데이터(s3Key)와 검증 결과만 보관한다.
 * content/원문/욕설/PDF 전문/비밀값은 절대 컬럼으로 두지 않는다.
 */
@Entity
@Table(name = "study_journals")
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class StudyJournal {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "material_id", nullable = false)
    private Long materialId;

    @Column(name = "user_id", nullable = false)
    private Long userId;

    /** 항상 STUDY_JOURNAL. 메모 등 다른 타입과 구분. */
    @Column(nullable = false, length = 40)
    @Builder.Default
    private String type = "STUDY_JOURNAL";

    /** S3 객체 키. bucket/region/prefix는 설정값으로 관리하므로 키만 저장. */
    @Column(name = "s3_key", nullable = false, length = 500)
    private String s3Key;

    /** 원문 SHA-256 (중복/무결성 식별용). 원문 자체는 저장하지 않는다. */
    @Column(name = "content_hash", length = 64)
    private String contentHash;

    @Column(name = "byte_size")
    private Long byteSize;

    @Column(name = "content_type", length = 100)
    @Builder.Default
    private String contentType = "application/json";

    @Column(name = "validation_decision", length = 30)
    private String validationDecision;

    @Column(name = "validation_category", length = 50)
    private String validationCategory;

    @Column(name = "relation_type", length = 40)
    private String relationType;

    @Column(name = "relation_path", length = 300)
    private String relationPath;

    private Double confidence;

    @Enumerated(EnumType.STRING)
    @Column(length = 20)
    @Builder.Default
    private StudyJournalStatus status = StudyJournalStatus.ACTIVE;

    @CreationTimestamp
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt;

    @UpdateTimestamp
    @Column(name = "updated_at")
    private LocalDateTime updatedAt;

    @Column(name = "deleted_at")
    private LocalDateTime deletedAt;

    public enum StudyJournalStatus {
        ACTIVE, DELETED
    }
}
