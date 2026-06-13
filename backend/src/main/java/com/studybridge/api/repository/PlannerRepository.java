package com.studybridge.api.repository;

import com.studybridge.api.entity.Planner;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.List;

public interface PlannerRepository extends JpaRepository<Planner, Long> {
    List<Planner> findByUserIdOrderByCreatedAtDesc(Long userId);

    // 로드맵 기반 자동 생성 중복 감지용
    long countByUserIdAndSourceMaterialIdAndSourceType(Long userId, Long sourceMaterialId, String sourceType);

    // 전체삭제: 인증 사용자 소유 + 지정 id 만 조회 (다른 유저 데이터는 애초에 조회되지 않음)
    List<Planner> findByUserIdAndIdIn(Long userId, List<Long> ids);
}
