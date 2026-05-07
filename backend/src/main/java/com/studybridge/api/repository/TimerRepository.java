package com.studybridge.api.repository;

import com.studybridge.api.entity.Timer;
import com.studybridge.api.entity.TimerStatus;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;

@Repository
public interface TimerRepository extends JpaRepository<Timer, Long> {

    Optional<Timer> findByUserIdAndStatus(Long userId, TimerStatus status);

    List<Timer> findByUserIdOrderByStartTimeDesc(Long userId);
}
