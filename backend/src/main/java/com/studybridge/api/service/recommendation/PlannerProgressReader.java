package com.studybridge.api.service.recommendation;

import com.studybridge.api.entity.PlanAnalysis;
import com.studybridge.api.entity.PlanAnalysisItem;
import com.studybridge.api.entity.Planner;
import com.studybridge.api.repository.PlanAnalysisItemRepository;
import com.studybridge.api.repository.PlanAnalysisRepository;
import com.studybridge.api.repository.PlannerRepository;
import com.studybridge.api.service.PlannerNextLearningService;
import com.studybridge.api.service.PlannerNextLearningService.Completion;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.NoSuchElementException;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 추천·진단이 공유하는 플래너 읽기 도우미. 모든 조회는 userId 로 제한한다(사용자 데이터 격리).
 *
 * <ul>
 *   <li>{@link #owned}: 소유권 검증(없으면 404, 남의 것이면 403).</li>
 *   <li>{@link #roadmapSiblings}: 같은 사용자·같은 로드맵의 로드맵 플래너(현재 포함). PlannerNextLearningService 와 같은 묶음 규칙.</li>
 *   <li>{@link #completions}: 이행도(plan_analysis_item) 일괄 조회 — 로드맵 84개 노드에서 N+1 쿼리를 피한다.</li>
 * </ul>
 */
@Component
@RequiredArgsConstructor
public class PlannerProgressReader {

    private final PlannerRepository plannerRepository;
    private final PlanAnalysisRepository planAnalysisRepository;
    private final PlanAnalysisItemRepository planAnalysisItemRepository;
    private final PlannerNextLearningService nextLearningService;

    public Planner owned(Long userId, Long plannerId) {
        Planner p = plannerRepository.findById(plannerId)
                .orElseThrow(() -> new NoSuchElementException("플래너를 찾을 수 없습니다. id=" + plannerId));
        if (!p.getUserId().equals(userId)) throw new SecurityException("본인의 플래너만 조회할 수 있습니다.");
        return p;
    }

    public List<Planner> roadmapSiblings(Long userId, Planner current) {
        List<Planner> raw = current.getSourceRoadmapId() != null
                ? plannerRepository.findByUserIdAndSourceRoadmapId(userId, current.getSourceRoadmapId())
                : current.getSourceMaterialId() != null
                    ? plannerRepository.findByUserIdAndSourceMaterialId(userId, current.getSourceMaterialId())
                    : List.of();
        List<Planner> out = new ArrayList<>();
        boolean hasCurrent = false;
        for (Planner p : raw) {
            if (!userId.equals(p.getUserId()) || !PlannerNextLearningService.isRoadmapPlanner(p)) continue;
            if (current.getSourceRoadmapId() == null && p.getSourceRoadmapId() != null) continue;
            if (p.getId().equals(current.getId())) hasCurrent = true;
            out.add(p);
        }
        if (!hasCurrent) out.add(current);
        return out;
    }

    public static String roadmapKey(Planner p) {
        if (p.getSourceRoadmapId() != null) return "r" + p.getSourceRoadmapId();
        if (p.getSourceMaterialId() != null) return "m" + p.getSourceMaterialId();
        return "p" + p.getId();
    }

    public static String nodeKey(Planner p) {
        return "p" + p.getId();
    }

    /** 위상 정렬 동률 키: week/day 가 있으면 그것, 없으면 날짜. */
    public static long order(Planner p) {
        long[] k = PlannerNextLearningService.orderKey(p);
        if (k == null) return Long.MAX_VALUE / 2 + p.getId();
        return k[0] * 1_000_000_000L + k[1] * 1_000L + k[2];
    }

    /** plannerId 로 연결된 최신 분석의 이행도. 분석이 없는 USER 플래너는 기존 단건 규칙(보관 자료 연결)으로 보충. */
    public Map<Long, Completion> completions(Long userId, List<Planner> planners) {
        Map<Long, Completion> out = new HashMap<>();
        if (planners.isEmpty()) return out;
        List<Long> ids = planners.stream().map(Planner::getId).toList();
        Map<Long, PlanAnalysis> latest = new HashMap<>();
        for (PlanAnalysis a : planAnalysisRepository.findByUserIdAndPlannerIdIn(userId, ids)) {
            PlanAnalysis prev = latest.get(a.getPlannerId());
            if (prev == null || a.getId() > prev.getId()) latest.put(a.getPlannerId(), a);
        }
        Map<Long, int[]> counts = new HashMap<>();
        if (!latest.isEmpty()) {
            Map<Long, Long> analysisToPlanner = new HashMap<>();
            latest.forEach((pid, a) -> analysisToPlanner.put(a.getId(), pid));
            for (PlanAnalysisItem it : planAnalysisItemRepository.findByAnalysisIdInAndDeletedFalse(analysisToPlanner.keySet())) {
                int[] c = counts.computeIfAbsent(analysisToPlanner.get(it.getAnalysisId()), k -> new int[2]);
                c[0]++;
                if (it.isCompleted()) c[1]++;
            }
        }
        for (Planner p : planners) {
            if (latest.containsKey(p.getId())) {
                int[] c = counts.getOrDefault(p.getId(), new int[2]);
                out.put(p.getId(), new Completion(c[0], c[1]));
            } else if (!PlannerNextLearningService.isRoadmapPlanner(p) && p.getMaterialId() != null) {
                out.put(p.getId(), nextLearningService.completion(userId, p));
            } else {
                out.put(p.getId(), new Completion(0, 0));
            }
        }
        return out;
    }

    /**
     * {@link #completions} 와 같은 분석 연결 규칙으로 플래너별 체크리스트 항목(삭제 제외, orderIndex 순)을 일괄 조회한다.
     * plannerId 로 연결된 최신 분석을 우선하고, 없으면 USER 플래너만 단건 규칙(보관 자료 연결)으로 보충한다.
     */
    public Map<Long, List<PlanAnalysisItem>> checklists(Long userId, List<Planner> planners) {
        Map<Long, List<PlanAnalysisItem>> out = new HashMap<>();
        if (planners.isEmpty()) return out;
        List<Long> ids = planners.stream().map(Planner::getId).toList();
        Map<Long, PlanAnalysis> latest = new HashMap<>();
        for (PlanAnalysis a : planAnalysisRepository.findByUserIdAndPlannerIdIn(userId, ids)) {
            PlanAnalysis prev = latest.get(a.getPlannerId());
            if (prev == null || a.getId() > prev.getId()) latest.put(a.getPlannerId(), a);
        }
        if (!latest.isEmpty()) {
            Map<Long, Long> analysisToPlanner = new HashMap<>();
            latest.forEach((pid, a) -> analysisToPlanner.put(a.getId(), pid));
            for (PlanAnalysisItem it : planAnalysisItemRepository.findByAnalysisIdInAndDeletedFalse(analysisToPlanner.keySet())) {
                out.computeIfAbsent(analysisToPlanner.get(it.getAnalysisId()), k -> new ArrayList<>()).add(it);
            }
            out.values().forEach(list -> list.sort(java.util.Comparator
                    .comparing((PlanAnalysisItem i) -> i.getOrderIndex() == null ? Integer.MAX_VALUE : i.getOrderIndex())
                    .thenComparing(PlanAnalysisItem::getId, java.util.Comparator.nullsLast(java.util.Comparator.naturalOrder()))));
        }
        for (Planner p : planners) {
            if (latest.containsKey(p.getId())) {
                out.putIfAbsent(p.getId(), List.of());
            } else if (!PlannerNextLearningService.isRoadmapPlanner(p) && p.getMaterialId() != null) {
                out.put(p.getId(), nextLearningService.checklistItems(userId, p));
            } else {
                out.put(p.getId(), List.of());
            }
        }
        return out;
    }

    /** 10분 집중 체크표(timeTableJson {"hour":[bool x6]})의 체크 칸 × 10분 = 실제 학습 기록 분. 기록 없으면 null. */
    public static Integer focusMinutes(String timeTableJson) {
        if (timeTableJson == null || timeTableJson.isBlank() || timeTableJson.trim().equals("{}")) return null;
        int n = 0;
        Matcher m = Pattern.compile("true").matcher(timeTableJson);
        while (m.find()) n++;
        return n == 0 ? null : n * 10;
    }

    // ───────────────────────── 시간/날짜 파싱(진단용) ─────────────────────────

    private static final Pattern HOUR_MIN = Pattern.compile("(\\d+(?:\\.\\d+)?)\\s*시간(?:\\s*(\\d+)\\s*분)?");
    private static final Pattern MIN_ONLY = Pattern.compile("^\\s*(\\d+)\\s*분\\s*$");
    private static final Pattern HHMM = Pattern.compile("^\\s*(\\d{1,2}):(\\d{2})\\s*$");

    /** "125분" / "2시간" / "1시간 30분" / "1.5시간" / "02:30" → 분. 단위 없는 숫자 등 해석 불가는 null(추정하지 않음). */
    public static Integer parseMinutes(String s) {
        if (s == null || s.isBlank()) return null;
        Matcher m = MIN_ONLY.matcher(s);
        if (m.matches()) return Integer.parseInt(m.group(1));
        m = HHMM.matcher(s);
        if (m.matches()) return Integer.parseInt(m.group(1)) * 60 + Integer.parseInt(m.group(2));
        m = HOUR_MIN.matcher(s);
        if (m.find()) {
            double h = Double.parseDouble(m.group(1));
            int extra = m.group(2) == null ? 0 : Integer.parseInt(m.group(2));
            return (int) Math.round(h * 60) + extra;
        }
        return null;
    }

    private static final Pattern YMD = Pattern.compile("(\\d{4})[-./](\\d{1,2})[-./](\\d{1,2})");
    private static final Pattern MD = Pattern.compile("^\\s*(\\d{1,2})[-./](\\d{1,2})\\s*$");
    private static final Pattern D_MINUS = Pattern.compile("(?i)^\\s*D\\s*-\\s*(\\d{1,3})\\s*$");

    /** 마감일 문자열(d_day 컬럼) → 날짜. "2026-09-18", "9/18", "D-7"(기준일 + 7). 해석 불가 null. */
    public static LocalDate parseDeadline(String s, LocalDate base) {
        if (s == null || s.isBlank()) return null;
        try {
            Matcher m = YMD.matcher(s);
            if (m.find()) return LocalDate.of(Integer.parseInt(m.group(1)), Integer.parseInt(m.group(2)), Integer.parseInt(m.group(3)));
            m = MD.matcher(s);
            if (m.matches() && base != null) return LocalDate.of(base.getYear(), Integer.parseInt(m.group(1)), Integer.parseInt(m.group(2)));
            m = D_MINUS.matcher(s);
            if (m.matches() && base != null) return base.plusDays(Integer.parseInt(m.group(1)));
        } catch (RuntimeException e) {
            return null;
        }
        return null;
    }
}
