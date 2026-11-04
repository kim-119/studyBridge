package com.studybridge.api.repository;

import com.studybridge.api.entity.AiTrainingOutbox;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.time.Instant;
import java.util.List;
import java.util.Optional;

public interface AiTrainingOutboxRepository extends JpaRepository<AiTrainingOutbox, Long> {

    boolean existsByEventId(String eventId);

    long countByUserIdAndKind(Long userId, String kind);

    Optional<AiTrainingOutbox> findByEventId(String eventId);

    /**
     * 전송 대상 선점(여러 인스턴스 동시 실행 안전: SKIP LOCKED). lease 가 지난 IN_FLIGHT(전송 중 중단)도 다시 집는다.
     * 철회·삭제·피드백(제어 메시지)을 학습 샘플보다 먼저 보낸다(tombstone 우선).
     */
    @Query(value = "SELECT * FROM ai_training_outbox WHERE (status = 'PENDING' AND (next_attempt_at IS NULL OR next_attempt_at <= :now)) "
            + "OR (status = 'IN_FLIGHT' AND lease_until < :now) "
            + "ORDER BY CASE WHEN kind = 'SAMPLE' THEN 1 ELSE 0 END, id LIMIT :limit FOR UPDATE SKIP LOCKED", nativeQuery = true)
    List<AiTrainingOutbox> lockDue(@Param("now") Instant now, @Param("limit") int limit);

    /** ai07 에 도달했을 수 있는 샘플(한 번이라도 전송 시도)의 삭제 추적 id — 회원 탈퇴 시 자료 단위 삭제 요청 대상. */
    @Query("SELECT DISTINCT o.deletionTrackingId FROM AiTrainingOutbox o WHERE o.userId = :userId AND o.kind = 'SAMPLE' "
            + "AND o.attempts > 0 AND o.deletionTrackingId IS NOT NULL")
    List<String> attemptedSampleTrackingIds(@Param("userId") Long userId);

    /** 철회/삭제: 아직 안 보낸 학습 샘플은 보내지 않고 원문을 지운다. */
    @Modifying
    @Query("UPDATE AiTrainingOutbox o SET o.status = 'CANCELLED', o.payloadJson = NULL, o.lastErrorCode = :reason "
            + "WHERE o.userId = :userId AND o.kind = 'SAMPLE' AND o.status IN ('PENDING', 'IN_FLIGHT')")
    int cancelPendingSamplesForUser(@Param("userId") Long userId, @Param("reason") String reason);

    @Modifying
    @Query("UPDATE AiTrainingOutbox o SET o.status = 'CANCELLED', o.payloadJson = NULL, o.lastErrorCode = :reason "
            + "WHERE o.userId = :userId AND o.materialId = :materialId AND o.kind = 'SAMPLE' AND o.status IN ('PENDING', 'IN_FLIGHT')")
    int cancelPendingSamplesForMaterial(@Param("userId") Long userId, @Param("materialId") Long materialId, @Param("reason") String reason);

    @Modifying
    @Query("UPDATE AiTrainingOutbox o SET o.status = 'CANCELLED', o.payloadJson = NULL, o.lastErrorCode = :reason "
            + "WHERE o.userId = :userId AND o.kind = 'FEEDBACK' AND o.status IN ('PENDING', 'IN_FLIGHT')")
    int cancelPendingFeedbackForUser(@Param("userId") Long userId, @Param("reason") String reason);
}
