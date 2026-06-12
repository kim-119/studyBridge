package com.studybridge.api.repository;

import com.studybridge.api.entity.Roadmap;
import org.springframework.data.jpa.repository.JpaRepository;
import java.util.Optional;

public interface RoadmapRepository extends JpaRepository<Roadmap, Long> {
    Optional<Roadmap> findByMaterial_MaterialId(Long materialId);

    // 플래너 로드맵 (가장 최근 1건)
    Optional<Roadmap> findFirstByPlannerIdOrderByRoadmapIdDesc(Long plannerId);
}
