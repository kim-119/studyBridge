package com.studybridge.api.ai.training;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.entity.AiTrainingOutbox;
import com.studybridge.api.repository.AiTrainingOutboxRepository;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.Map;

/** outbox 적재(항상 독립 트랜잭션). 같은 event_id 는 unique 제약으로 한 번만 저장된다(at-least-once + 멱등). */
@Slf4j
@Component
public class TrainingOutboxWriter {

    public enum Result { ENQUEUED, DUPLICATE, FAILED }

    private final AiTrainingOutboxRepository repository;
    private final ObjectMapper mapper = new ObjectMapper();

    public TrainingOutboxWriter(AiTrainingOutboxRepository repository) {
        this.repository = repository;
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public Result enqueueSample(String eventId, Long userId, Long materialId, String payloadJson, String contentHash,
                                String consentVersion, String deletionTrackingId) {
        return insert(AiTrainingOutbox.builder().eventId(eventId).kind("SAMPLE").userId(userId).materialId(materialId)
                .status("PENDING").attempts(0).nextAttemptAt(LocalDateTime.now()).payloadJson(payloadJson)
                .contentHash(contentHash).consentVersion(consentVersion).deletionTrackingId(deletionTrackingId).build());
    }

    /** 철회/삭제 요청(사용자 원문 없음). 호출자 트랜잭션에 합류 — 철회 기록과 함께 커밋/롤백된다. */
    @Transactional(propagation = Propagation.REQUIRED)
    public Result enqueueControl(String kind, String eventId, Long userId, Long materialId, Map<String, Object> body,
                                 String deletionTrackingId) {
        try {
            return insert(AiTrainingOutbox.builder().eventId(eventId).kind(kind).userId(userId).materialId(materialId)
                    .status("PENDING").attempts(0).nextAttemptAt(LocalDateTime.now()).payloadJson(mapper.writeValueAsString(body))
                    .deletionTrackingId(deletionTrackingId).build());
        } catch (com.fasterxml.jackson.core.JsonProcessingException e) {
            return Result.FAILED;
        }
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
