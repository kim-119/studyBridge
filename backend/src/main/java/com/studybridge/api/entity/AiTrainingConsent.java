package com.studybridge.api.entity;

import jakarta.persistence.*;
import lombok.*;
import org.hibernate.annotations.CreationTimestamp;

import java.time.LocalDateTime;

/**
 * 모델 학습 데이터 활용 동의(MODEL_TRAINING) 이력 — append-only. 최신 행이 현재 상태다(GRANTED/WITHDRAWN).
 *  · 일반 서비스 이용·AI 기능 사용 동의와 별개이며 기본은 미동의(행 없음 = OFF).
 *  · 동의 증명: 버전 + 그 버전 고지문 SHA-256 + 시각 + 만 14세 이상 확인 여부를 서버에 남긴다(문구 원문은 코드 버전 관리).
 *  · 철회는 새 행(WITHDRAWN)으로 남기고 지우지 않는다(감사·소급 적용 금지 판단 근거).
 */
@Entity
@Table(name = "ai_training_consents", indexes = {
        @Index(name = "idx_atc_user_purpose_created", columnList = "user_id, purpose, created_at")
})
@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
public class AiTrainingConsent {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "user_id", nullable = false)
    private Long userId;

    @Column(name = "purpose", nullable = false, length = 32)
    private String purpose;

    @Column(name = "status", nullable = false, length = 16)
    private String status;

    @Column(name = "consent_version", nullable = false, length = 32)
    private String consentVersion;

    @Column(name = "consent_text_sha256", length = 64)
    private String consentTextSha256;

    @Column(name = "age_confirmed_14_plus")
    private Boolean ageConfirmed14Plus;

    @Column(name = "source", length = 16)
    private String source;

    @CreationTimestamp
    @Column(name = "created_at", updatable = false)
    private LocalDateTime createdAt;
}
