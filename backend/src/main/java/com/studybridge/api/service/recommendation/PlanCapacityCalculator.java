package com.studybridge.api.service.recommendation;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

/**
 * AI 학습 계획 진단(Optimization Strategy)의 결정적 계산부. AI 를 호출하지 않는다.
 *
 * <pre>
 *  A = Σ_d AvailableTime(d)            (d ∈ [오늘, 기한], 사용자가 입력한 하루 가용 시간 기준)
 *  W = Σ_i EstimatedDuration(task_i)   (예상 시간이 기록된 미완료 작업만)
 *  D = max(0, W − A)
 * </pre>
 * <ul>
 *   <li>예상 시간이 없는 작업은 W 에 0 으로 넣지 않고 {@code unestimatedCount} 로 따로 센다 → W 는 하한값임을 응답에 표시.</li>
 *   <li>가용 시간 입력이 없으면 A·D 를 계산하지 않는다(NEEDS_AVAILABILITY). 수치를 만들어 내지 않는다.</li>
 *   <li>총량 외에 마감일별 누적 창(EDF), 날짜별 과부하, 선수관계 위반, 일정(시간 구간) 중복을 검사한다.</li>
 * </ul>
 */
public final class PlanCapacityCalculator {

    public record Task(String key, String title, LocalDate date, LocalDate deadline, Integer estimatedMinutes,
                       boolean completed, List<String> prereqKeys) {
        LocalDate due() { return deadline != null ? deadline : date; }
    }

    public record Interval(String id, String title, LocalDateTime start, LocalDateTime end) {}

    public record Window(LocalDate dueDate, int cumulativeWorkload, Integer cumulativeAvailable, Integer shortage) {}

    public record DayLoad(LocalDate date, int plannedMinutes, Integer availableMinutes) {}

    public record DependencyIssue(String taskKey, String prereqKey, String kind) {}

    public record Overlap(String firstId, String secondId, String firstTitle, String secondTitle, long overlapMinutes) {}

    public record Result(String status, LocalDate from, LocalDate to, Integer horizonDays, Integer availableMinutes,
                         int workloadMinutes, int estimatedCount, int unestimatedCount, Integer deficitMinutes,
                         List<Window> windows, Window firstShortageWindow, List<DayLoad> overloadedDays,
                         List<DependencyIssue> dependencyIssues, List<Overlap> overlaps, List<String> priorityOrder) {}

    public static final String OK = "OK";
    public static final String SHORTAGE = "SHORTAGE";
    public static final String NEEDS_AVAILABILITY = "NEEDS_AVAILABILITY";
    public static final String NO_ESTIMATES = "NO_ESTIMATES";
    public static final String NO_TASKS = "NO_TASKS";

    private PlanCapacityCalculator() {}

    /**
     * @param dailyAvailableMinutes 하루 가용 학습 시간(분). null = 모름.
     * @param horizonEnd            진단 기한(포함). null 이면 미완료 작업의 마지막 날짜.
     * @param topoOrder             선수관계 위상 순서(작업 key). 없으면 빈 목록.
     */
    public static Result calculate(LocalDate today, LocalDate horizonEnd, Integer dailyAvailableMinutes,
                                   List<Task> tasks, List<Interval> busy, List<String> topoOrder) {
        List<Task> pending = tasks.stream().filter(t -> !t.completed()).toList();
        if (pending.isEmpty()) {
            return new Result(NO_TASKS, today, horizonEnd, null, null, 0, 0, 0, null,
                    List.of(), null, List.of(), List.of(), overlaps(busy), List.of());
        }
        LocalDate end = horizonEnd;
        if (end == null) {
            end = pending.stream().map(Task::due).filter(d -> d != null).max(LocalDate::compareTo).orElse(today);
        }
        if (end.isBefore(today)) end = today;
        int horizonDays = (int) ChronoUnit.DAYS.between(today, end) + 1;
        Integer daily = dailyAvailableMinutes != null && dailyAvailableMinutes >= 0 ? dailyAvailableMinutes : null;
        Integer available = daily == null ? null : daily * horizonDays;

        int workload = 0;
        int estimated = 0;
        int unestimated = 0;
        for (Task t : pending) {
            if (t.estimatedMinutes() != null && t.estimatedMinutes() > 0) {
                workload += t.estimatedMinutes();
                estimated++;
            } else {
                unestimated++;
            }
        }
        Integer deficit = available == null || estimated == 0 ? null : Math.max(0, workload - available);

        // 마감일별 누적 창(EDF): 기한이 지난 미완료 작업은 오늘 창에 넣는다.
        TreeMap<LocalDate, Integer> dueLoad = new TreeMap<>();
        Map<LocalDate, Integer> dayLoad = new TreeMap<>();
        for (Task t : pending) {
            if (t.estimatedMinutes() == null || t.estimatedMinutes() <= 0) continue;
            LocalDate due = t.due() == null ? end : (t.due().isBefore(today) ? today : t.due());
            dueLoad.merge(due, t.estimatedMinutes(), Integer::sum);
            LocalDate day = t.date() == null ? null : (t.date().isBefore(today) ? today : t.date());
            if (day != null) dayLoad.merge(day, t.estimatedMinutes(), Integer::sum);
        }
        List<Window> windows = new ArrayList<>();
        Window firstShortage = null;
        int cum = 0;
        for (Map.Entry<LocalDate, Integer> e : dueLoad.entrySet()) {
            cum += e.getValue();
            Integer cumA = daily == null ? null : daily * ((int) ChronoUnit.DAYS.between(today, e.getKey()) + 1);
            Integer shortage = cumA == null ? null : Math.max(0, cum - cumA);
            Window w = new Window(e.getKey(), cum, cumA, shortage);
            windows.add(w);
            if (firstShortage == null && shortage != null && shortage > 0) firstShortage = w;
        }
        List<DayLoad> overloaded = new ArrayList<>();
        if (daily != null) {
            dayLoad.forEach((d, m) -> { if (m > daily) overloaded.add(new DayLoad(d, m, daily)); });
        }

        List<DependencyIssue> deps = dependencyIssues(pending, tasks, today);
        String status;
        if (estimated == 0) status = NO_ESTIMATES;
        else if (daily == null) status = NEEDS_AVAILABILITY;
        else if ((deficit != null && deficit > 0) || firstShortage != null) status = SHORTAGE;
        else status = OK;

        return new Result(status, today, end, horizonDays, available, workload, estimated, unestimated, deficit,
                windows, firstShortage, overloaded, deps, overlaps(busy), priorityOrder(pending, topoOrder));
    }

    /** 선행 작업보다 먼저 배치된 작업(SCHEDULED_BEFORE_PREREQ), 기한 지난 미완료 선행 작업(PREREQ_OVERDUE). */
    static List<DependencyIssue> dependencyIssues(List<Task> pending, List<Task> all, LocalDate today) {
        Map<String, Task> byKey = new HashMap<>();
        for (Task t : all) byKey.put(t.key(), t);
        List<DependencyIssue> out = new ArrayList<>();
        for (Task t : pending) {
            for (String pk : t.prereqKeys() == null ? List.<String>of() : t.prereqKeys()) {
                Task p = byKey.get(pk);
                if (p == null || p.completed()) continue;
                if (t.date() != null && p.date() != null && t.date().isBefore(p.date())) {
                    out.add(new DependencyIssue(t.key(), pk, "SCHEDULED_BEFORE_PREREQ"));
                } else if (p.date() != null && p.date().isBefore(today)) {
                    out.add(new DependencyIssue(t.key(), pk, "PREREQ_OVERDUE"));
                }
            }
        }
        return out;
    }

    /** 시간 구간이 겹치는 일정 쌍(정렬 후 스윕). 시작/종료가 없거나 역전된 구간은 제외. */
    static List<Overlap> overlaps(List<Interval> busy) {
        if (busy == null || busy.isEmpty()) return List.of();
        List<Interval> xs = busy.stream()
                .filter(i -> i.start() != null && i.end() != null && i.end().isAfter(i.start()))
                .sorted(Comparator.comparing(Interval::start)).toList();
        List<Overlap> out = new ArrayList<>();
        for (int i = 0; i < xs.size(); i++) {
            for (int j = i + 1; j < xs.size(); j++) {
                Interval a = xs.get(i);
                Interval b = xs.get(j);
                if (!b.start().isBefore(a.end())) break;
                LocalDateTime oe = a.end().isBefore(b.end()) ? a.end() : b.end();
                out.add(new Overlap(a.id(), b.id(), a.title(), b.title(), ChronoUnit.MINUTES.between(b.start(), oe)));
            }
        }
        return out;
    }

    /** 우선순위: 기한 빠른 순(EDF) → 같은 기한이면 선수관계 위상 순서 → key. */
    static List<String> priorityOrder(List<Task> pending, List<String> topoOrder) {
        Map<String, Integer> topo = new HashMap<>();
        for (int i = 0; i < topoOrder.size(); i++) topo.put(topoOrder.get(i), i);
        return pending.stream()
                .sorted(Comparator.comparing((Task t) -> t.due() == null ? LocalDate.MAX : t.due())
                        .thenComparing(t -> topo.getOrDefault(t.key(), Integer.MAX_VALUE))
                        .thenComparing(Task::key))
                .map(Task::key).toList();
    }
}
