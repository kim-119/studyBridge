package com.studybridge.api.service;

import com.studybridge.api.dto.PlannerDTO.NextLearningResponse;
import com.studybridge.api.entity.Material;
import com.studybridge.api.entity.MaterialType;
import com.studybridge.api.entity.PlanAnalysis;
import com.studybridge.api.entity.PlanAnalysisItem;
import com.studybridge.api.entity.Planner;
import com.studybridge.api.entity.PlannerType;
import com.studybridge.api.repository.MaterialRepository;
import com.studybridge.api.repository.PlanAnalysisItemRepository;
import com.studybridge.api.repository.PlanAnalysisRepository;
import com.studybridge.api.repository.PlannerRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.domain.PageRequest;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDate;
import java.util.List;
import java.util.Locale;
import java.util.NoSuchElementException;
import java.util.Optional;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * "다음 학습 추천" — DB 데이터 + 결정적 규칙만 사용한다. AI 서버(FastAPI/OpenAI/Ollama)를 호출하지 않는다.
 *
 * <ul>
 *   <li>다음 항목은 <b>이미 존재하는</b> 플래너 중에서만 고른다(새 학습 내용 생성·플래너 생성·일정 변경 없음).</li>
 *   <li>로드맵 플래너: 같은 사용자·같은 로드맵의 형제 플래너를 1회 SELECT 한 뒤 week/day(없으면 plannerDate) 순서로
 *       현재보다 뒤에 있는 가장 가까운 항목. planner_id 증가값은 순서로 쓰지 않는다.</li>
 *   <li>사용자 플래너: 같은 사용자·같은 과목·현재 플래너 날짜 이후 중 가장 가까운 기존 플래너 1건.</li>
 *   <li>완료 상태 = 계획 이행도(plan_analysis_item.completed)이며 이해도가 아니다. 전부 완료일 때만 READY.</li>
 * </ul>
 */
@Slf4j
@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class PlannerNextLearningService {

    public static final String STATUS_READY = "READY";
    public static final String STATUS_IN_PROGRESS = "IN_PROGRESS";
    public static final String STATUS_NO_NEXT = "NO_NEXT";
    public static final String STATUS_NO_DATA = "NO_DATA";
    public static final String TYPE_ROADMAP_NEXT = "ROADMAP_NEXT";
    public static final String TYPE_USER_NEXT = "USER_NEXT";

    static final String REASON_ROADMAP_NEXT = "현재 로드맵의 다음 학습 순서입니다.";
    static final String REASON_IN_PROGRESS = "현재 계획이 아직 진행 중입니다. 완료 후 다음 학습으로 이동할 수 있습니다.";
    static final String REASON_USER_NEXT = "같은 과목에서 예정된 다음 학습 계획입니다.";
    static final String REASON_NO_NEXT = "현재 등록된 다음 학습 계획이 없습니다.";
    static final String REASON_NO_DATA = "다음 학습을 결정할 학습 순서 정보가 없습니다.";

    private static final Pattern ROADMAP_WD = Pattern.compile("\\[\\s*로드맵\\s*(\\d+)\\s*주차\\s*(\\d+)\\s*일\\s*\\]");

    private final PlannerRepository plannerRepository;
    private final MaterialRepository materialRepository;
    private final PlanAnalysisRepository planAnalysisRepository;
    private final PlanAnalysisItemRepository planAnalysisItemRepository;

    public NextLearningResponse recommend(Long userId, Long plannerId) {
        Planner current = plannerRepository.findById(plannerId)
                .orElseThrow(() -> new NoSuchElementException("플래너를 찾을 수 없습니다. id=" + plannerId));
        if (!current.getUserId().equals(userId)) throw new SecurityException("본인의 플래너만 조회할 수 있습니다.");

        Completion completion = completion(userId, current);
        boolean roadmap = isRoadmapPlanner(current);

        Candidate next = roadmap ? nextInRoadmap(userId, current) : nextUserPlanner(userId, current);
        NextLearningResponse.NextLearningResponseBuilder b = NextLearningResponse.builder()
                .currentPlannerId(current.getId())
                .completionRate(completion.rate())
                .checklistTotal(completion.total)
                .checklistCompleted(completion.completed);

        if (next == null) {
            String status = (roadmap && orderKey(current) == null) || (!roadmap && isBlank(current.getSubject()))
                    ? STATUS_NO_DATA : STATUS_NO_NEXT;
            return b.available(false).status(status)
                    .reason(STATUS_NO_DATA.equals(status) ? REASON_NO_DATA : REASON_NO_NEXT).build();
        }

        Planner p = next.planner;
        boolean ready = completion.allComplete();
        int[] wd = weekDay(p);
        return b.available(true)
                .status(ready ? STATUS_READY : STATUS_IN_PROGRESS)
                .recommendationType(next.type)
                .nextPlannerId(p.getId())
                .nextMaterialId(archiveMaterialId(p))
                .title(p.getTitle())
                .subject(p.getSubject())
                .plannerDate(p.getPlannerDate())
                .roadmapWeek(wd == null ? null : wd[0])
                .roadmapDay(wd == null ? null : wd[1])
                .reason(ready ? (TYPE_ROADMAP_NEXT.equals(next.type) ? REASON_ROADMAP_NEXT : REASON_USER_NEXT) : REASON_IN_PROGRESS)
                .build();
    }

    // ---------------- 로드맵 플래너 ----------------

    /** 같은 사용자·같은 로드맵의 형제 플래너 중 현재보다 뒤 순서에서 가장 가까운 것. 순서 근거가 없으면 null. */
    private Candidate nextInRoadmap(Long userId, Planner current) {
        long[] curKey = orderKey(current);
        if (curKey == null) return null;
        List<Planner> siblings = current.getSourceRoadmapId() != null
                ? plannerRepository.findByUserIdAndSourceRoadmapId(userId, current.getSourceRoadmapId())
                : current.getSourceMaterialId() != null
                    ? plannerRepository.findByUserIdAndSourceMaterialId(userId, current.getSourceMaterialId())
                    : List.of();
        Planner best = null;
        long[] bestKey = null;
        for (Planner p : siblings) {
            if (p.getId().equals(current.getId()) || !userId.equals(p.getUserId()) || !isRoadmapPlanner(p)) continue;
            // sourceRoadmapId 로 묶지 못한 레거시 행은 같은 출처 자료의 로드맵 플래너로 한정한다.
            if (current.getSourceRoadmapId() == null && p.getSourceRoadmapId() != null) continue;
            long[] key = orderKey(p);
            if (key == null || compare(key, curKey) <= 0) continue;
            if (bestKey == null || compare(key, bestKey) < 0 || (compare(key, bestKey) == 0 && p.getId() < best.getId())) {
                best = p; bestKey = key;
            }
        }
        return best == null ? null : new Candidate(best, TYPE_ROADMAP_NEXT);
    }

    /**
     * 학습 순서 키: [0]=순서 종류(0=week/day, 1=날짜만), [1..]=값. week/day 가 있는 행끼리는 week/day 로,
     * 없으면 plannerDate 로 비교한다. 둘 다 없으면 null(순서를 알 수 없음).
     */
    static long[] orderKey(Planner p) {
        int[] wd = weekDay(p);
        if (wd != null) return new long[]{0, wd[0], wd[1]};
        if (p.getPlannerDate() != null) return new long[]{1, p.getPlannerDate().toEpochDay(), 0};
        return null;
    }

    private static int compare(long[] a, long[] b) {
        for (int i = 0; i < Math.min(a.length, b.length); i++) {
            int c = Long.compare(a[i], b[i]);
            if (c != 0) return c;
        }
        return 0;
    }

    /** week/day: 컬럼 우선, 없으면 제목 "[로드맵 N주차 M일]" 에서 추출. */
    static int[] weekDay(Planner p) {
        if (p.getRoadmapWeek() != null && p.getRoadmapDay() != null) return new int[]{p.getRoadmapWeek(), p.getRoadmapDay()};
        if (p.getTitle() == null) return null;
        Matcher m = ROADMAP_WD.matcher(p.getTitle());
        if (!m.find()) return null;
        try { return new int[]{Integer.parseInt(m.group(1)), Integer.parseInt(m.group(2))}; }
        catch (NumberFormatException e) { return null; }
    }

    static boolean isRoadmapPlanner(Planner p) {
        if (p.getPlannerType() != null) return p.getPlannerType() == PlannerType.ROADMAP;
        return p.getSourceType() != null || p.getSourceRoadmapId() != null;
    }

    // ---------------- 사용자 플래너 ----------------

    /** 같은 사용자·같은 과목·현재 플래너 날짜(없으면 오늘) 이후 중 가장 가까운 기존 플래너. */
    private Candidate nextUserPlanner(Long userId, Planner current) {
        if (isBlank(current.getSubject())) return null;
        LocalDate after = current.getPlannerDate() != null ? current.getPlannerDate() : LocalDate.now();
        List<Planner> found = plannerRepository.findNextUserPlanners(userId, current.getId(),
                current.getSubject().trim().toLowerCase(Locale.ROOT), after, PageRequest.of(0, 1));
        if (found.isEmpty()) return null;
        Planner p = found.get(0);
        if (!userId.equals(p.getUserId())) return null;   // 방어: 쿼리가 이미 userId 로 제한하지만 소유권을 재확인
        return new Candidate(p, TYPE_USER_NEXT);
    }

    // ---------------- 완료 상태(계획 이행도) ----------------

    /**
     * 현재 플래너의 체크리스트 완료 상태. 근거는 plan_analysis_item(삭제 제외)이며, 분석은 plannerId 로 연결된 것을
     * 우선하고 없으면 이 플래너의 보관 자료(PLANNER material)에 연결된 분석을 쓴다.
     * (로드맵 플래너의 materialId 는 출처 PDF 라 여러 플래너가 공유하므로 그 분석은 쓰지 않는다.)
     */
    private Completion completion(Long userId, Planner current) {
        Optional<PlanAnalysis> analysis = planAnalysisRepository.findTopByUserIdAndPlannerIdOrderByIdDesc(userId, current.getId());
        if (analysis.isEmpty() && current.getMaterialId() != null) {
            Material m = materialRepository.findById(current.getMaterialId()).orElse(null);
            if (m != null && m.getMaterialType() == MaterialType.PLANNER && current.getId().equals(m.getPlannerId())) {
                analysis = planAnalysisRepository.findTopByUserIdAndMaterialIdOrderByIdDesc(userId, m.getMaterialId());
            }
        }
        if (analysis.isEmpty()) return new Completion(0, 0);
        List<PlanAnalysisItem> items = planAnalysisItemRepository.findByAnalysisIdAndDeletedFalseOrderByOrderIndexAsc(analysis.get().getId());
        int done = (int) items.stream().filter(PlanAnalysisItem::isCompleted).count();
        return new Completion(items.size(), done);
    }

    /** 다음 플래너의 자료보관함 보관 항목 id(있으면 기존 Archive 라우팅으로 이동). */
    private Long archiveMaterialId(Planner next) {
        List<Material> archives = materialRepository.findByPlannerIdAndMaterialType(next.getId(), MaterialType.PLANNER);
        if (!archives.isEmpty()) return archives.get(0).getMaterialId();
        if (next.getMaterialId() != null) {
            Material m = materialRepository.findById(next.getMaterialId()).orElse(null);
            if (m != null && m.getMaterialType() == MaterialType.PLANNER && next.getId().equals(m.getPlannerId())) return m.getMaterialId();
        }
        return null;
    }

    private static boolean isBlank(String s) { return s == null || s.isBlank(); }

    private record Candidate(Planner planner, String type) {}

    private record Completion(int total, int completed) {
        boolean allComplete() { return total > 0 && completed == total; }
        Double rate() { return total == 0 ? null : (double) completed / total; }
    }
}
