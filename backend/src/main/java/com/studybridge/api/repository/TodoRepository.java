package com.studybridge.api.repository;

import com.studybridge.api.entity.Todo;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface TodoRepository extends JpaRepository<Todo, Long> {
    List<Todo> findByUserId(Long userId);

    // 출처 기반 idempotent 조회(같은 사용자·같은 출처·같은 날짜 → 기존 row 재사용)
    java.util.Optional<Todo> findFirstByUserIdAndSourceTypeAndSourceIdAndScheduleDateOrderByIdAsc(
            Long userId, String sourceType, Long sourceId, java.time.LocalDate scheduleDate);

    List<Todo> findByUserIdAndSourceTypeAndSourceIdOrderByScheduleDateDesc(Long userId, String sourceType, Long sourceId);
}
