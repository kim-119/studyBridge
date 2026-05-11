package com.studybridge.api.repository;

import com.studybridge.api.entity.Timer;
import com.studybridge.api.entity.TimerStatus;
import com.studybridge.api.entity.User; // User 엔티티 import
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

@Repository
public interface TimerRepository extends JpaRepository<Timer, Long> {

    Optional<Timer> findByUserAndStatus(User user, TimerStatus status);

    List<Timer> findByUserOrderByStartTimeDesc(User user);

    // 특정 사용자, 특정 상태, 특정 시간 범위 내의 타이머들을 조회
    List<Timer> findByUserAndStatusAndEndTimeBetween(User user, TimerStatus status, LocalDateTime start, LocalDateTime end);
}
