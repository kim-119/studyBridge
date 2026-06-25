package com.studybridge.api.repository;

import com.studybridge.api.entity.Planner;
import com.studybridge.api.entity.PlannerType;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;

import java.util.List;

public interface PlannerRepository extends JpaRepository<Planner, Long> {
    List<Planner> findByUserIdOrderByCreatedAtDesc(Long userId);

    // 타입 필터 조회 (backfill 완료 데이터용). NULL 데이터는 서비스 resolver 로 보강한다.
    List<Planner> findByUserIdAndPlannerTypeOrderByCreatedAtDesc(Long userId, PlannerType plannerType);

    // ── 기존 NULL plannerType 데이터 일괄 보정(backfill) ──
    // 로드맵 자동 생성 흔적이 있으면 ROADMAP, 나머지는 USER 로 채운다. 기동 시 1회 실행(이미 채워진 행은 건드리지 않음).
    @Modifying
    @Query("UPDATE Planner p SET p.plannerType = com.studybridge.api.entity.PlannerType.ROADMAP " +
            "WHERE p.plannerType IS NULL AND (p.sourceType IS NOT NULL OR p.sourceRoadmapId IS NOT NULL)")
    int backfillRoadmapType();

    @Modifying
    @Query("UPDATE Planner p SET p.plannerType = com.studybridge.api.entity.PlannerType.USER " +
            "WHERE p.plannerType IS NULL")
    int backfillUserType();

    long countByPlannerTypeIsNull();

    // 로드맵 기반 자동 생성 중복 감지용
    long countByUserIdAndSourceMaterialIdAndSourceType(Long userId, Long sourceMaterialId, String sourceType);

    // 전체삭제: 인증 사용자 소유 + 지정 id 만 조회 (다른 유저 데이터는 애초에 조회되지 않음)
    List<Planner> findByUserIdAndIdIn(Long userId, List<Long> ids);

    // AI 계획 분석: 자료에 연결된 플래너 텍스트 수집용
    List<Planner> findByUserIdAndMaterialId(Long userId, Long materialId);
    List<Planner> findByUserIdAndSourceMaterialId(Long userId, Long sourceMaterialId);
}
