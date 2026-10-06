package com.studybridge.api.repository;

import com.studybridge.api.entity.PlannerAiResult;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface PlannerAiResultRepository extends JpaRepository<PlannerAiResult, Long> {
    Optional<PlannerAiResult> findByPlannerId(Long plannerId);
}
