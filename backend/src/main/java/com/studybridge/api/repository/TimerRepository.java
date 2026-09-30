package com.studybridge.api.repository;

import com.studybridge.api.entity.Timer;
import com.studybridge.api.entity.TimerStatus;
import jakarta.persistence.LockModeType;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.stereotype.Repository;

import java.time.LocalDateTime;
import java.util.Collection;
import java.util.List;
import java.util.Optional;

@Repository
public interface TimerRepository extends JpaRepository<Timer, Long> {

    Optional<Timer> findByUserIdAndStatus(Long userId, TimerStatus status);

    /** 사용자의 활성 세션을 행 잠금으로 조회 — start/heartbeat/end 가 동시에 와도 크레딧 중복/이중 세션이 생기지 않게 직렬화한다. */
    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("SELECT t FROM Timer t WHERE t.user.id = :userId AND t.status = :status")
    Optional<Timer> findByUserIdAndStatusForUpdate(@Param("userId") Long userId, @Param("status") TimerStatus status);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("SELECT t FROM Timer t WHERE t.id = :id")
    Optional<Timer> findByIdForUpdate(@Param("id") Long id);

    List<Timer> findByUserIdOrderByStartTimeDesc(Long userId);

    /** 사용자의 가장 최근 세션(멱등 STOP 재호출 시 기존 결과 반환용). */
    Optional<Timer> findFirstByUserIdOrderByStartTimeDesc(Long userId);

    // --- 추가된 메서드 ---
    // 특정 사용자, 특정 상태, 특정 시간 범위 내의 타이머들을 조회
    List<Timer> findByUserIdAndStatusAndEndTimeBetween(Long userId, TimerStatus status, LocalDateTime start, LocalDateTime end);

    /** reaper: heartbeat 를 지원하는 활성 세션 중 마지막 heartbeat 가 기준 시각보다 오래된 것(비정상 종료 추정). */
    @Query("SELECT t.id FROM Timer t WHERE t.status = 'STARTED' AND t.lastHeartbeatAt IS NOT NULL AND t.lastHeartbeatAt < :threshold")
    List<Long> findHeartbeatTimedOutIds(@Param("threshold") LocalDateTime threshold);

    /** reaper: heartbeat 미지원(구 클라이언트) 활성 세션이 기준 시각보다 오래 남은 것(좀비). */
    @Query("SELECT t.id FROM Timer t WHERE t.status = 'STARTED' AND t.lastHeartbeatAt IS NULL AND t.startTime < :threshold")
    List<Long> findStaleWithoutHeartbeatIds(@Param("threshold") LocalDateTime threshold);

    /**
     * 통계: 그룹의 세션 중 [from, toExclusive) 와 겹치는 것(진행 중 세션 포함). 그룹 단위 1회 조회.
     * end_time 이 null(진행 중)이면 겹침으로 간주하고 서비스가 유효 종료 시각(lastHeartbeatAt)으로 자른다.
     */
    @Query("SELECT t FROM Timer t WHERE t.groupStudyId = :groupId AND t.user.id IN :userIds " +
           "AND t.status IN ('STARTED', 'COMPLETED') AND t.startTime < :toExclusive " +
           "AND (t.endTime IS NULL OR t.endTime > :from) ORDER BY t.startTime")
    List<Timer> findGroupSessionsOverlapping(@Param("groupId") Long groupId,
                                             @Param("userIds") Collection<Long> userIds,
                                             @Param("from") LocalDateTime from,
                                             @Param("toExclusive") LocalDateTime toExclusive);
}
