package com.studybridge.api.ai.training;

import com.studybridge.api.ai.contract.v1.AiContractException;
import com.studybridge.api.ai.contract.v1.TrainingControlV1;
import com.studybridge.api.entity.AiTrainingOutbox;
import com.studybridge.api.repository.AiTrainingOutboxRepository;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

import java.time.Clock;
import java.time.Instant;

/**
 * outbox 적재. 같은 event_id 는 unique 제약으로 한 번만 저장된다(at-least-once + 멱등).
 *  · SAMPLE: 독립 트랜잭션(호출자 커밋 후 적재). consent_id = 이 샘플을 만든 동의 행.
 *  · 제어 메시지(training-control.v1): 호출자 트랜잭션에 합류 — 철회/삭제 기록과 함께 커밋/롤백. 본문은 계약 검증을 통과한
 *    원시 JSON 그대로 저장하고, 디스패처는 이 바이트를 바꾸지 않고 서명해 보낸다(재시도 시 헤더 timestamp 만 갱신).
 */
@Slf4j
@Component
public class TrainingOutboxWriter {

    public enum Result { ENQUEUED, DUPLICATE, FAILED }

    private final AiTrainingOutboxRepository repository;
    private final Clock clock;

    public TrainingOutboxWriter(AiTrainingOutboxRepository repository, Clock clock) {
        this.repository = repository;
        this.clock = clock;
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public Result enqueueSample(String eventId, Long userId, Long materialId, String payloadJson, String contentHash,
                                String consentVersion, String deletionTrackingId, Long consentId) {
        return insert(AiTrainingOutbox.builder().eventId(eventId).kind("SAMPLE").userId(userId).materialId(materialId)
                .status("PENDING").attempts(0).nextAttemptAt(Instant.now(clock)).payloadJson(payloadJson)
                .contentHash(contentHash).consentVersion(consentVersion).deletionTrackingId(deletionTrackingId).consentId(consentId)
                .build());
    }

    /** 제어 메시지 적재. 계약 위반 본문은 저장하지 않는다(AiContractException → FAILED). */
    @Transactional(propagation = Propagation.REQUIRED)
    public Result enqueueControl(TrainingControlV1 message, Long userId, Long materialId) {
        String json;
        try {
            json = TrainingControlV1.toJson(message);
        } catch (AiContractException e) {
            log.error("[TRAINING-OUTBOX] 제어 메시지 계약 위반 — 적재 안 함 type={} code={}", message == null ? null : message.messageType(),
                    e.code());
            return Result.FAILED;
        }
        return insert(AiTrainingOutbox.builder().eventId(message.eventId()).kind(message.messageType().name()).userId(userId)
                .materialId(materialId).status("PENDING").attempts(0).nextAttemptAt(Instant.now(clock)).payloadJson(json)
                .deletionTrackingId(message.deletionTrackingId()).contentHash(message.contentHash()).build());
    }

    private Result insert(AiTrainingOutbox row) {
        if (repository.existsByEventId(row.getEventId())) {
            return Result.DUPLICATE;
        }
        try {
            repository.saveAndFlush(row);
            return Result.ENQUEUED;
        } catch (DataIntegrityViolationException e) {
            return Result.DUPLICATE; // 동시 적재 경합 — unique(event_id)
        }
    }
}
