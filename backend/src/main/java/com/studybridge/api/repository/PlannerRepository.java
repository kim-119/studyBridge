package com.studybridge.api.repository;

import com.studybridge.api.entity.Planner;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface PlannerRepository extends JpaRepository<Planner, Long> {
    List<Planner> findByUserIdOrderByCreatedAtDesc(Long userId);

    // 로드맵 기반 자동 생성 중복 감지용
    long countByUserIdAndSourceMaterialIdAndSourceType(Long userId, Long sourceMaterialId, String sourceType);
}
