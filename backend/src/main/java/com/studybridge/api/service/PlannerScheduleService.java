package com.studybridge.api.service;

import com.studybridge.api.dto.PlannerSemanticDTO.*;
import com.studybridge.api.entity.Planner;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Pattern;

/**
 * 하루 학습 시간표 계산 + PDF 생성 + S3 저장/다운로드.
 *  - 시작/종료 시각은 LLM 이 아니라 Java 가 startTime + 정규화 recommendedMinutes 로 결정적으로 계산한다.
 *  - 시작시간만 바뀌면 AI 를 재호출하지 않는다(캐시된 분석의 task duration 재사용).
 *  - client 의 endTime/S3 key/userId 는 신뢰하지 않는다 — 서버가 소유권 검증 후 key 를 생성한다.
 */
@Slf4j
@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class PlannerScheduleService {

    private static final Pattern HHMM = Pattern.compile("([01]\\d|2[0-3]):([0-5]\\d)");
    private static final DateTimeFormatter DISPLAY = DateTimeFormatter.ofPattern("yyyy.MM.dd");
    private static final DateTimeFormatter KEY_DATE = DateTimeFormatter.ofPattern("yyyyMMdd");

    private final PlannerSemanticAnalyzer analyzer;
    private final PlannerAnalysisContext context;
    private final PlannerSchedulePdfRenderer renderer;
    private final S3Service s3Service;

    @Value("${planner.schedule.template-key:planner/templates/daily_schedule_v1.pdf}")
    private String templateKey;

    /** 시작시간 기준 결정적 시간표(미리보기/PDF 공통 authoritative). */
    public Schedule schedule(Long userId, Long plannerId, String startTime) {
        Planner planner = context.owned(userId, plannerId);
        AnalysisResponse analysis = analyzer.ensure(userId, plannerId);
        return buildSchedule(planner, analysis, normalizeStart(startTime));
    }

    /** 시간표 PDF 생성 → S3 private 업로드 → 15분 presigned 다운로드 URL 반환. */
    @Transactional
    public Download generatePdf(Long userId, Long plannerId, String startTime) {
        Planner planner = context.owned(userId, plannerId);
        AnalysisResponse analysis = analyzer.ensure(userId, plannerId);
        Schedule schedule = buildSchedule(planner, analysis, normalizeStart(startTime));

        LocalDate date = planner.getPlannerDate() != null ? planner.getPlannerDate() : LocalDate.now();
        String dateLabel = date.format(DISPLAY);
        byte[] pdf = renderer.render(schedule, planner.getTitle(), dateLabel);

        // key 는 서버가 생성 — client 가 userId/key 를 지정할 수 없다.
        String key = String.format("planner/generated/user_%d/planner_%d/%s_%d.pdf",
                userId, plannerId, date.format(KEY_DATE), System.currentTimeMillis());
        String stored;
        try {
            stored = s3Service.uploadBytes(pdf, key, "application/pdf");   // private object (버킷 정책 유지)
        } catch (Exception e) {
            log.error("[planner:schedule] S3 업로드 실패 plannerId={} key={}: {}", plannerId, key, e.getMessage());
            throw new IllegalStateException("시간표 PDF 저장에 실패했습니다. 잠시 후 다시 시도해 주세요.");
        }
        String fileName = fileName(planner.getTitle(), dateLabel);
        String url = s3Service.getDownloadPresignedUrl(stored, fileName);
        log.info("[planner:schedule] PDF 생성 완료 plannerId={} rows={} total={}분 key={}",
                plannerId, schedule.rows().size(), schedule.totalMinutes(), stored);
        return new Download(url, fileName, schedule);
    }

    // ---------------- 결정적 계산 ----------------

    private Schedule buildSchedule(Planner planner, AnalysisResponse analysis, String startTime) {
        List<Task> tasks = analysis.getTasks();
        if (tasks == null || tasks.isEmpty()) {
            throw new IllegalStateException("시간표를 만들 학습 활동이 없습니다. 먼저 AI 계획 분석을 실행해 주세요.");
        }
        int startAbs = toMinutes(startTime);
        int cursor = startAbs;
        int total = 0;
        List<ScheduleRow> rows = new ArrayList<>();
        for (Task t : tasks) {
            int minutes = t.getRecommendedMinutes() == null ? 1 : Math.max(1, t.getRecommendedMinutes());
            int s = cursor, e = cursor + minutes;
            rows.add(new ScheduleRow(t.getId(), t.getTitle(), t.getType(), minutes,
                    fmt(s), fmt(e), s / 1440, e / 1440));
            cursor = e;
            total += minutes;
        }
        LocalDate date = planner.getPlannerDate() != null ? planner.getPlannerDate() : LocalDate.now();
        return new Schedule(planner.getId(), planner.getTitle(), date.format(DISPLAY), total, startTime, rows);
    }

    private String normalizeStart(String startTime) {
        String s = startTime == null ? "" : startTime.trim();
        if (!HHMM.matcher(s).matches()) {
            throw new IllegalArgumentException("학습 시작 시간을 HH:MM(00:00~23:59) 형식으로 선택해 주세요.");
        }
        return s;
    }

    private int toMinutes(String hhmm) {
        String[] p = hhmm.split(":");
        return Integer.parseInt(p[0]) * 60 + Integer.parseInt(p[1]);
    }

    private String fmt(int abs) {
        int m = abs % 1440;
        return String.format("%02d:%02d", m / 60, m % 60);
    }

    private String fileName(String title, String dateLabel) {
        String base = title == null || title.isBlank() ? "학습" : title;
        base = base.replaceAll("[\\\\/:*?\"<>|]", "_").trim();
        if (base.length() > 40) base = base.substring(0, 40).trim();
        return "하루일정표_" + base + "_" + dateLabel.replace(".", "") + ".pdf";
    }
}
