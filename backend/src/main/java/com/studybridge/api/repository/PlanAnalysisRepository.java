package com.studybridge.api.repository;

import com.studybridge.api.entity.PlanAnalysis;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface PlanAnalysisRepository extends JpaRepository<PlanAnalysis, Long> {
    /** materialId 기준 가장 최근 분석 1건. */
    Optional<PlanAnalysis> findTopByUserIdAndMaterialIdOrderByIdDesc(Long userId, Long materialId);
    /** plannerId 기준 가장 최근 분석 1건(다음 학습 추천의 계획 이행도 근거). */
    Optional<PlanAnalysis> findTopByUserIdAndPlannerIdOrderByIdDesc(Long userId, Long plannerId);
}
