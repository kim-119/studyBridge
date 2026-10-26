package com.studybridge.api.config;

import com.studybridge.api.repository.PlannerRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.ApplicationArguments;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Transactional;

/**
 * 기존 planners 데이터의 NULL plannerType 을 기동 시 1회 보정한다(데이터 원천 분리).
 *  - 로드맵 자동 생성 흔적(sourceType=ROADMAP_AUTO 또는 sourceRoadmapId) → ROADMAP
 *  - 나머지 → USER
 * 이미 채워진 행은 건드리지 않으며, 보정할 행이 없으면 UPDATE 자체를 건너뛴다(idempotent).
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class PlannerTypeBackfill implements ApplicationRunner {

    private final PlannerRepository plannerRepository;

    @Override
    @Transactional
    public void run(ApplicationArguments args) {
        long nullCount = plannerRepository.countByPlannerTypeIsNull();
        if (nullCount == 0) {
            log.info("[planner-backfill] plannerType NULL 데이터 없음 — backfill 생략");
            return;
        }
        int roadmap = plannerRepository.backfillRoadmapType();
        int user = plannerRepository.backfillUserType();
        log.info("[planner-backfill] plannerType 보정 완료: NULL {}건 → ROADMAP {}건, USER {}건",
                nullCount, roadmap, user);
    }
}
