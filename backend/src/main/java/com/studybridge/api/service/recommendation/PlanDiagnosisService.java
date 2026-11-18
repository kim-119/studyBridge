package com.studybridge.api.service.recommendation;

import com.studybridge.api.entity.Planner;
import com.studybridge.api.entity.PlannerType;
import com.studybridge.api.entity.Todo;
import com.studybridge.api.repository.PlannerRepository;
import com.studybridge.api.repository.TodoRepository;
import com.studybridge.api.service.PlannerNextLearningService;
import com.studybridge.api.service.PlannerNextLearningService.Completion;
import lombok.Builder;
import lombok.Getter;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * AI 학습 계획 진단 — Optimization Strategy(기존 계획 최적화). 새 공부를 만들지 않는다(그건 LearningRecommendationService).
 *
 * <p>범위: 로드맵 플래너 → 같은 로드맵의 노드 전체, 사용자 플래너 → 같은 과목의 사용자 플래너.
 * 예상 시간 = 플래너에 기록된 목표 시간(goalTime) 또는 estimatedMinutes(둘 다 사용자/로드맵 생성 시 기록값이며 EC2 가 만들지 않는다).
 * 가용 시간 = 사용자가 입력한 하루 가용 학습 시간. 입력이 없으면 A·D 를 계산하지 않는다.</p>
 * 작업의 의미적 분해는 기존 AI07 분석(/api/ai/planner/analyze-semantic)이 담당하고, 이 서비스는 실제 일정·기록으로 계산만 한다.
 */
@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class PlanDiagnosisService {

    static final int MAX_TASKS = 120;

    private final PlannerProgressReader progress;
    private final PlannerRepository plannerRepository;
    private final TodoRepository todoRepository;

    @Getter
    @Builder
    public static class TaskView {
        private Long plannerId;
        private String title;
        private LocalDate date;
        private Integer estimatedMinutes;
        private boolean completed;
    }

    @Getter
    @Builder
    public static class Response {
        private Long plannerId;
        private String scope;               // ROADMAP | USER_SUBJECT | SINGLE
        private String status;              // OK | SHORTAGE | NEEDS_AVAILABILITY | NO_ESTIMATES | NO_TASKS
        private LocalDate from;
        private LocalDate to;
        private Integer horizonDays;
        private Integer dailyAvailableMinutes;
        private Integer availableMinutes;   // A
        private int workloadMinutes;        // W (예상 시간이 있는 미완료 작업만)
        private Integer deficitMinutes;     // D = max(0, W − A)
        private int estimatedCount;
        private int unestimatedCount;
        private LocalDate deadline;
        private String deadlineSource;      // REQUEST | PLANNER_D_DAY | LAST_TASK
        private List<PlanCapacityCalculator.Window> windows;
        private PlanCapacityCalculator.Window firstShortageWindow;
        private List<PlanCapacityCalculator.DayLoad> overloadedDays;
        private List<Map<String, Object>> dependencyIssues;
        private List<Map<String, Object>> overlaps;
        private List<TaskView> priority;    // 미완료 작업 권장 순서(EDF → 선수관계)
        private int pendingCount;
        private int completedCount;
        private List<String> notes;
        private Map<String, String> formulas;
    }

    public Response diagnose(Long userId, Long plannerId, Integer dailyAvailableMinutes, LocalDate requestedDeadline) {
        Planner current = progress.owned(userId, plannerId);
        LocalDate today = LocalDate.now();
        boolean roadmap = PlannerNextLearningService.isRoadmapPlanner(current);
        List<Planner> scopePlanners = roadmap ? progress.roadmapSiblings(userId, current) : subjectPlanners(userId, current);
        String scope = roadmap ? "ROADMAP" : (scopePlanners.size() > 1 ? "USER_SUBJECT" : "SINGLE");
        if (scopePlanners.size() > MAX_TASKS) {
            scopePlanners = scopePlanners.stream().sorted((a, b) -> Long.compare(PlannerProgressReader.order(a), PlannerProgressReader.order(b)))
                    .filter(p -> p.getPlannerDate() == null || !p.getPlannerDate().isBefore(today.minusDays(30)))
                    .limit(MAX_TASKS).toList();
        }
        Map<Long, Completion> comps = progress.completions(userId, scopePlanners);

        // 선수관계: 로드맵은 순차 DAG(레거시 호환), 사용자 플래너는 관계 데이터 없음.
        Map<String, List<String>> prereqs = new HashMap<>();
        List<String> topo = List.of();
        if (roadmap) {
            LearningGraph g = LearningGraph.sequential(scopePlanners.stream()
                    .map(p -> new LearningGraph.Node(PlannerProgressReader.nodeKey(p), p.getTitle(), PlannerProgressReader.order(p))).toList());
            topo = g.topologicalOrder();
            for (String k : g.nodes().keySet()) prereqs.put(k, List.copyOf(g.prereqs(k)));
        }

        LocalDate deadline = requestedDeadline;
        String deadlineSource = deadline != null ? "REQUEST" : null;
        if (deadline == null) {
            deadline = PlannerProgressReader.parseDeadline(current.getDDay(), current.getPlannerDate() != null ? current.getPlannerDate() : today);
            if (deadline != null) deadlineSource = "PLANNER_D_DAY";
        }

        List<PlanCapacityCalculator.Task> tasks = new ArrayList<>();
        Map<String, Planner> byKey = new LinkedHashMap<>();
        int completedCount = 0;
        int afterDeadline = 0;
        for (Planner p : scopePlanners) {
            String key = PlannerProgressReader.nodeKey(p);
            byKey.put(key, p);
            boolean done = comps.get(p.getId()).allComplete();
            if (done) completedCount++;
            // 작업별 기한 = 계획된 날짜(마감일별 누적 창은 날짜 단위로 본다). 전체 마감일은 진단 기간 끝으로만 쓴다.
            tasks.add(new PlanCapacityCalculator.Task(key, p.getTitle(), p.getPlannerDate(), null, estimate(p), done,
                    prereqs.getOrDefault(key, List.of())));
            if (!done && deadline != null && p.getPlannerDate() != null && p.getPlannerDate().isAfter(deadline)) afterDeadline++;
        }

        LocalDate horizonEnd = deadline;
        if (horizonEnd == null) deadlineSource = "LAST_TASK";
        PlanCapacityCalculator.Result r = PlanCapacityCalculator.calculate(today, horizonEnd, dailyAvailableMinutes, tasks,
                busy(userId, today, horizonEnd), topo);

        List<Map<String, Object>> deps = new ArrayList<>();
        for (PlanCapacityCalculator.DependencyIssue d : r.dependencyIssues()) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("kind", d.kind());
            m.put("plannerId", byKey.get(d.taskKey()).getId());
            m.put("title", byKey.get(d.taskKey()).getTitle());
            m.put("prereqPlannerId", byKey.get(d.prereqKey()).getId());
            m.put("prereqTitle", byKey.get(d.prereqKey()).getTitle());
            deps.add(m);
        }
        List<Map<String, Object>> overlaps = new ArrayList<>();
        for (PlanCapacityCalculator.Overlap o : r.overlaps()) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("first", o.firstTitle());
            m.put("second", o.secondTitle());
            m.put("overlapMinutes", o.overlapMinutes());
            overlaps.add(m);
        }
        List<TaskView> priority = r.priorityOrder().stream().limit(20).map(k -> {
            Planner p = byKey.get(k);
            return TaskView.builder().plannerId(p.getId()).title(p.getTitle()).date(p.getPlannerDate())
                    .estimatedMinutes(estimate(p)).completed(false).build();
        }).toList();

        List<String> notes = new ArrayList<>();
        if (r.unestimatedCount() > 0) notes.add("예상 시간이 기록되지 않은 작업 " + r.unestimatedCount() + "개는 W 에 포함하지 않았습니다(W 는 하한값).");
        if (dailyAvailableMinutes == null) notes.add("하루 가용 학습 시간을 입력하면 가용 시간 A 와 부족량 D 를 계산합니다.");
        if (!roadmap) notes.add("사용자 플래너 사이의 선수관계 데이터가 없어 의존 관계 검사는 로드맵에서만 수행합니다.");
        if (afterDeadline > 0) notes.add("마감일(" + deadline + ") 이후로 계획된 미완료 작업이 " + afterDeadline + "개 있습니다. 마감 전에 끝내려면 일정을 앞당겨야 합니다.");
        if (deadline == null) notes.add("마감일이 없어 마지막 계획 날짜까지를 진단 기간으로 사용했습니다.");

        return Response.builder()
                .plannerId(plannerId).scope(scope).status(r.status()).from(r.from()).to(r.to()).horizonDays(r.horizonDays())
                .dailyAvailableMinutes(dailyAvailableMinutes).availableMinutes(r.availableMinutes())
                .workloadMinutes(r.workloadMinutes()).deficitMinutes(r.deficitMinutes())
                .estimatedCount(r.estimatedCount()).unestimatedCount(r.unestimatedCount())
                .deadline(deadline).deadlineSource(deadlineSource)
                .windows(r.windows()).firstShortageWindow(r.firstShortageWindow()).overloadedDays(r.overloadedDays())
                .dependencyIssues(deps).overlaps(overlaps).priority(priority)
                .pendingCount(tasks.size() - completedCount).completedCount(completedCount)
                .notes(notes)
                .formulas(Map.of("A", "Σ AvailableTime(d), d ∈ [from, to]", "W", "Σ EstimatedDuration(task_i) (미완료·예상시간 기록분)",
                        "D", "max(0, W − A)"))
                .build();
    }

    /** 같은 사용자·같은 과목의 사용자 플래너(현재 포함). 과목이 없으면 현재 플래너만. */
    private List<Planner> subjectPlanners(Long userId, Planner current) {
        if (current.getSubject() == null || current.getSubject().isBlank()) return List.of(current);
        String subj = current.getSubject().trim().toLowerCase(Locale.ROOT);
        List<Planner> out = new ArrayList<>();
        for (Planner p : plannerRepository.findByUserIdAndPlannerTypeOrderByCreatedAtDesc(userId, PlannerType.USER)) {
            if (!userId.equals(p.getUserId()) || p.getSubject() == null) continue;
            if (p.getSubject().trim().toLowerCase(Locale.ROOT).equals(subj)) out.add(p);
        }
        if (out.stream().noneMatch(p -> p.getId().equals(current.getId()))) out.add(current);
        return out;
    }

    /** 예상 시간(분): estimatedMinutes → goalTime 문자열 파싱. 없으면 null(추정하지 않음). */
    static Integer estimate(Planner p) {
        if (p.getEstimatedMinutes() != null && p.getEstimatedMinutes() > 0) return p.getEstimatedMinutes();
        return PlannerProgressReader.parseMinutes(p.getGoalTime());
    }

    /** 진단 기간의 시간 구간 일정(todos start/end). */
    private List<PlanCapacityCalculator.Interval> busy(Long userId, LocalDate from, LocalDate to) {
        List<PlanCapacityCalculator.Interval> out = new ArrayList<>();
        LocalDate end = to == null ? from.plusDays(60) : to;
        for (Todo t : todoRepository.findByUserId(userId)) {
            if (t.getStartDate() == null || t.getEndDate() == null) continue;
            LocalDate d = t.getStartDate().toLocalDate();
            if (d.isBefore(from) || d.isAfter(end)) continue;
            out.add(new PlanCapacityCalculator.Interval("todo" + t.getId(), t.getText(), t.getStartDate(), t.getEndDate()));
        }
        return out;
    }
}
