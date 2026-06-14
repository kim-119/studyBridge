package com.studybridge.api.repository;

import com.studybridge.api.entity.PlanAnalysis;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface PlanAnalysisRepository extends JpaRepository<PlanAnalysis, Long> {
    /** materialId 기준 가장 최근 분석 1건. */
    Optional<PlanAnalysis> findTopByUserIdAndMaterialIdOrderByIdDesc(Long userId, Long materialId);
}
