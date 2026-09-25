package com.studybridge.api.repository;

import com.studybridge.api.entity.PlanAnalysisItem;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

public interface PlanAnalysisItemRepository extends JpaRepository<PlanAnalysisItem, Long> {
    List<PlanAnalysisItem> findByAnalysisIdAndDeletedFalseOrderByOrderIndexAsc(Long analysisId);
    List<PlanAnalysisItem> findByAnalysisIdOrderByOrderIndexAsc(Long analysisId);

    @Transactional
    void deleteByAnalysisId(Long analysisId);
}
