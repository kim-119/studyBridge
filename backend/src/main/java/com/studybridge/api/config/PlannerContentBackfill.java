package com.studybridge.api.config;

import com.studybridge.api.service.PlannerService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.SpringApplication;
import org.springframework.context.ConfigurableApplicationContext;
import org.springframework.stereotype.Component;

/**
 * 로드맵 플래너 content/tmi 문장 재구성 backfill(옵트인, 기본 off).
 *
 * <pre>
 *   STUDYBRIDGE_PLANNER_CONTENT_BACKFILL=run   기동 후 1회 실행하고 계속 서비스
 *   STUDYBRIDGE_PLANNER_CONTENT_BACKFILL=once  1회 실행 후 프로세스 종료(예: docker compose run --rm spring)
 * </pre>
 * 실행 내용은 {@link PlannerService#normalizeRoadmapPlannerContent()} — idempotent 하므로 반복 실행해도 안전하다.
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class PlannerContentBackfill implements ApplicationRunner {

    private final PlannerService plannerService;
    private final ConfigurableApplicationContext context;

    @Value("${studybridge.planner.content-backfill:off}")
    private String mode;

    @Override
    public void run(ApplicationArguments args) {
        String m = mode == null ? "off" : mode.trim().toLowerCase();
        if (!m.equals("run") && !m.equals("once")) return;
        int changed;
        try {
            changed = plannerService.normalizeRoadmapPlannerContent();
            log.info("[planner:content-backfill] mode={} changed={}", m, changed);
        } catch (Exception e) {
            log.error("[planner:content-backfill] 실패", e);
            if (m.equals("once")) System.exit(SpringApplication.exit(context, () -> 1));
            return;
        }
        if (m.equals("once")) System.exit(SpringApplication.exit(context, () -> 0));
    }
}
