package com.studybridge.api.repository;

import com.studybridge.api.entity.AiTrainingOutbox;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.time.LocalDateTime;
import java.util.List;

public interface AiTrainingOutboxRepository extends JpaRepository<AiTrainingOutbox, Long> {

    boolean existsByEventId(String eventId);

    long countByUserIdAndKind(Long userId, String kind);

    /** 전송 대상 선점(여러 인스턴스 동시 실행 안전: SKIP LOCKED). lease 가 지난 IN_FLIGHT(전송 중 중단)도 다시 집는다. */
    @Query(value = "SELECT * FROM ai_training_outbox WHERE (status = 'PENDING' AND (next_attempt_at IS NULL OR next_attempt_at <= :now)) "
            + "OR (status = 'IN_FLIGHT' AND lease_until < :now) ORDER BY id LIMIT :limit FOR UPDATE SKIP LOCKED", nativeQuery = true)
    List<AiTrainingOutbox> lockDue(@Param("now") LocalDateTime now, @Param("limit") int limit);

    /** 철회/삭제: 아직 안 보낸 학습 샘플은 보내지 않고 원문을 지운다. */
    @Modifying
    @Query("UPDATE AiTrainingOutbox o SET o.status = 'CANCELLED', o.payloadJson = NULL, o.lastErrorCode = :reason "
            + "WHERE o.userId = :userId AND o.kind = 'SAMPLE' AND o.status IN ('PENDING', 'IN_FLIGHT')")
    int cancelPendingSamplesForUser(@Param("userId") Long userId, @Param("reason") String reason);

    @Modifying
    @Query("UPDATE AiTrainingOutbox o SET o.status = 'CANCELLED', o.payloadJson = NULL, o.lastErrorCode = :reason "
            + "WHERE o.userId = :userId AND o.materialId = :materialId AND o.kind = 'SAMPLE' AND o.status IN ('PENDING', 'IN_FLIGHT')")
    int cancelPendingSamplesForMaterial(@Param("userId") Long userId, @Param("materialId") Long materialId, @Param("reason") String reason);
}
