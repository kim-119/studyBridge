package com.studybridge.api.service.adaptive;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.entity.PlanAnalysis;
import com.studybridge.api.entity.PlanAnalysisItem;
import com.studybridge.api.entity.Planner;
import com.studybridge.api.entity.PlannerType;
import com.studybridge.api.entity.ReviewNote;
import com.studybridge.api.repository.PlanAnalysisItemRepository;
import com.studybridge.api.repository.PlanAnalysisRepository;
import com.studybridge.api.repository.PlannerRepository;
import com.studybridge.api.repository.ReviewNoteRepository;
import com.studybridge.api.service.PlannerNextLearningService;
import com.studybridge.api.service.recommendation.PlannerProgressReader;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicLong;

/**
 * 적응형 학습 엔진 테스트 공용 인메모리 DB(플래너·체크리스트·오답노트). 조회는 실제 리포지토리처럼 userId 로 거른다.
 */
class AdaptiveFixtures {

    static final long USER = 55L;
    static final long OTHER = 56L;
    static final LocalDate TODAY = LocalDate.of(2026, 10, 28);

    final Map<Long, Planner> planners = new LinkedHashMap<>();
    final List<PlanAnalysis> analyses = new ArrayList<>();
    final List<PlanAnalysisItem> items = new ArrayList<>();
    final List<ReviewNote> notes = new ArrayList<>();
    final AtomicLong seq = new AtomicLong(1000);

    final PlannerRepository plannerRepository = mock(PlannerRepository.class);
    final PlanAnalysisRepository analysisRepository = mock(PlanAnalysisRepository.class);
    final PlanAnalysisItemRepository itemRepository = mock(PlanAnalysisItemRepository.class);
    final ReviewNoteRepository reviewNoteRepository = mock(ReviewNoteRepository.class);
    final PlannerNextLearningService nextLearningService = mock(PlannerNextLearningService.class);
    final ObjectMapper objectMapper = new ObjectMapper();
    final PlannerProgressReader progressReader;
    final AdaptivePlannerContextBuilder builder;

    AdaptiveFixtures() {
        when(plannerRepository.findById(anyLong())).thenAnswer(inv -> Optional.ofNullable(planners.get((Long) inv.getArgument(0))));
        when(plannerRepository.findByUserIdAndSourceRoadmapId(anyLong(), anyLong())).thenAnswer(inv -> planners.values().stream()
                .filter(p -> p.getUserId().equals(inv.getArgument(0)) && inv.getArgument(1).equals(p.getSourceRoadmapId())).toList());
        when(plannerRepository.findByUserIdAndSourceMaterialId(anyLong(), anyLong())).thenAnswer(inv -> planners.values().stream()
                .filter(p -> p.getUserId().equals(inv.getArgument(0)) && inv.getArgument(1).equals(p.getSourceMaterialId())).toList());
        when(plannerRepository.findByUserIdOrderByCreatedAtDesc(anyLong())).thenAnswer(inv -> planners.values().stream()
                .filter(p -> p.getUserId().equals(inv.getArgument(0))).toList());
        when(analysisRepository.findByUserIdAndPlannerIdIn(anyLong(), any())).thenAnswer(inv -> analyses.stream()
                .filter(a -> a.getUserId().equals(inv.getArgument(0)) && ((Collection<?>) inv.getArgument(1)).contains(a.getPlannerId())).toList());
        when(itemRepository.findByAnalysisIdInAndDeletedFalse(any())).thenAnswer(inv -> items.stream()
                .filter(i -> !i.isDeleted() && ((Collection<?>) inv.getArgument(0)).contains(i.getAnalysisId())).toList());
        when(reviewNoteRepository.findTop5ByUserIdAndSourceMaterialIdOrderByCreatedAtDesc(anyLong(), anyLong())).thenAnswer(inv -> notes.stream()
                .filter(n -> n.getUserId().equals(inv.getArgument(0)) && inv.getArgument(1).equals(n.getSourceMaterialId()))
                .sorted((a, b) -> b.getCreatedAt().compareTo(a.getCreatedAt())).limit(5).toList());
        progressReader = new PlannerProgressReader(plannerRepository, analysisRepository, itemRepository, nextLearningService);
        builder = new AdaptivePlannerContextBuilder(plannerRepository, progressReader, reviewNoteRepository, objectMapper);
    }

    Planner roadmapStep(long id, long owner, int week, int day, LocalDate date) {
        Planner p = Planner.builder().id(id).userId(owner).plannerType(PlannerType.ROADMAP).sourceType("ROADMAP_AUTO")
                .sourceRoadmapId(9L).sourceMaterialId(345L).roadmapWeek(week).roadmapDay(day)
                .title("[로드맵 " + week + "주차 " + day + "일] 단계 " + week + "-" + day).subject("딥러닝")
                .content("필터가 입력 위를 이동하며 특징맵을 만드는 과정을 이해한다. [할 일] 1. 손계산").priority("보통")
                .plannerDate(date).year(date.getYear()).month(date.getMonthValue()).day(date.getDayOfMonth())
                .createdAt(LocalDateTime.of(2026, 10, 1, 9, 0)).build();
        planners.put(id, p);
        return p;
    }

    Planner userPlanner(long id, long owner, String title, LocalDate date, String priority, String dDay) {
        Planner p = Planner.builder().id(id).userId(owner).plannerType(PlannerType.USER).title(title).subject("과목" + id)
                .priority(priority).dDay(dDay).content("내용 " + title)
                .plannerDate(date).year(date == null ? null : date.getYear()).month(date == null ? null : date.getMonthValue())
                .day(date == null ? null : date.getDayOfMonth())
                .createdAt(LocalDateTime.of(2026, 10, 20, 9, 0)).build();
        planners.put(id, p);
        return p;
    }

    /** 플래너에 체크리스트(분석 1건 + 항목). completed[i] 로 완료 여부. */
    List<PlanAnalysisItem> checklist(Planner p, boolean... completed) {
        PlanAnalysis a = PlanAnalysis.builder().id(seq.incrementAndGet()).userId(p.getUserId()).plannerId(p.getId()).build();
        analyses.add(a);
        List<PlanAnalysisItem> out = new ArrayList<>();
        for (int i = 0; i < completed.length; i++) {
            PlanAnalysisItem it = PlanAnalysisItem.builder().id(seq.incrementAndGet()).analysisId(a.getId()).orderIndex(i)
                    .text("과제 " + p.getId() + "-" + (i + 1)).completed(completed[i]).hidden(false).deleted(false).build();
            items.add(it);
            out.add(it);
        }
        return out;
    }

    ReviewNote reviewNote(long id, long owner, long materialId, LocalDateTime createdAt, String retryJson) {
        ReviewNote n = ReviewNote.builder().reviewNoteId(id).userId(owner).sourceMaterialId(materialId).title("오답노트 " + id)
                .retryJson(retryJson).createdAt(createdAt).build();
        notes.add(n);
        return n;
    }
}
