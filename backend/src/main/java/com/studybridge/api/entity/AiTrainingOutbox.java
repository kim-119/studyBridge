package com.studybridge.api.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;
import org.hibernate.annotations.UpdateTimestamp;

import java.time.LocalDateTime;

/**
 * 학습 후보/철회/삭제 전달용 durable outbox(at-least-once, event_id 멱등).
 *  · SAMPLE: training-sample.v1 본문(전송 바이트 그대로, 서명은 전송 시각에 계산). 전송 완료/취소/실패 확정 시 payload 를 지운다.
 *  · REVOCATION: 동의 철회(가명 키) · DELETION: 자료 삭제(deletionTrackingId) — 사용자 원문 없음.
 *  · status: PENDING → IN_FLIGHT(lease) → SENT | PENDING(재시도) | DEAD | CANCELLED(철회·삭제로 미전송)
 */
@Entity
@Table(name = "ai_training_outbox", indexes = {
        @Index(name = "idx_ato_status_next", columnList = "status, next_attempt_at"),
        @Index(name = "idx_ato_user_material", columnList = "user_id, material_id")
}, uniqueConstraints = @UniqueConstraint(name = "uk_ato_event_id", columnNames = "event_id"))
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class AiTrainingOutbox {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "event_id", nullable = false, length = 128)
    private String eventId;

    @Column(name = "kind", nullable = false, length = 16)
    private String kind;

    @Column(name = "user_id", nullable = false)
    private Long userId;

    @Column(name = "material_id")
    private Long materialId;

    @Column(name = "status", nullable = false, length = 16)
    private String status;

    @Column(name = "attempts", nullable = false)
    private int attempts;

    @Column(name = "next_attempt_at")
    private LocalDateTime nextAttemptAt;

    @Column(name = "lease_until")
    private LocalDateTime leaseUntil;

    @Column(name = "last_error_code", length = 64)
    private String lastErrorCode;

    @Column(name = "payload_json", columnDefinition = "TEXT")
    private String payloadJson;

    @Column(name = "content_hash", length = 64)
    private String contentHash;

    @Column(name = "consent_version", length = 32)
    private String consentVersion;

    @Column(name = "deletion_tracking_id", length = 128)
    private String deletionTrackingId;

    @CreationTimestamp
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt;

    @UpdateTimestamp
    @Column(name = "updated_at")
    private LocalDateTime updatedAt;

    @Column(name = "sent_at")
    private LocalDateTime sentAt;
}
