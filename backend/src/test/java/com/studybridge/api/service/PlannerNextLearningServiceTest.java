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
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Field;
import java.time.LocalDate;
import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;

/**
 * 다음 학습 추천 — DB + 결정적 규칙. AI 호출 없음, 플래너 생성/수정 없음, planner_id 증가값으로 순서 판단 없음.
 */
class PlannerNextLearningServiceTest {

    private static final long USER = 8L;
    private static final long OTHER_USER = 9L;
    private static final long ROADMAP = 172L;

    private PlannerRepository planners;
    private MaterialRepository materials;
    private PlanAnalysisRepository analyses;
    private PlanAnalysisItemRepository items;
    private PlannerNextLearningService service;

    @BeforeEach
    void setUp() {
        planners = mock(PlannerRepository.class);
        materials = mock(MaterialRepository.class);
        analyses = mock(PlanAnalysisRepository.class);
        items = mock(PlanAnalysisItemRepository.class);
        service = new PlannerNextLearningService(planners, materials, analyses, items);
        when(analyses.findTopByUserIdAndPlannerIdOrderByIdDesc(anyLong(), anyLong())).thenReturn(Optional.empty());
        when(analyses.findTopByUserIdAndMaterialIdOrderByIdDesc(anyLong(), anyLong())).thenReturn(Optional.empty());
        when(materials.findByPlannerIdAndMaterialType(anyLong(), any())).thenReturn(List.of());
        when(materials.findById(anyLong())).thenReturn(Optional.empty());
    }

    /** 제목에만 week/day 가 있는 운영 데이터 형태(roadmap_week/day 컬럼 NULL). */
    private static Planner roadmap(long id, long user, int week, int day, LocalDate date) {
        return Planner.builder().id(id).userId(user).plannerType(PlannerType.ROADMAP).sourceType("ROADMAP_AUTO")
                .sourceRoadmapId(ROADMAP).sourceMaterialId(299L).materialId(299L).subject("선형회귀")
                .title("[로드맵 " + week + "주차 " + day + "일] 주제 " + week + "-" + day).plannerDate(date).build();
    }

    private static Planner user(long id, long user, String subject, LocalDate date) {
        return Planner.builder().id(id).userId(user).plannerType(PlannerType.USER).subject(subject)
                .title(subject + " 계획 " + id).plannerDate(date).build();
    }

    private void checklist(long plannerId, int total, int completed) {
        PlanAnalysis a = PlanAnalysis.builder().id(500L + plannerId).userId(USER).plannerId(plannerId).materialId(700L).build();
        when(analyses.findTopByUserIdAndPlannerIdOrderByIdDesc(USER, plannerId)).thenReturn(Optional.of(a));
        java.util.List<PlanAnalysisItem> list = new java.util.ArrayList<>();
        for (int i = 0; i < total; i++) {
            list.add(PlanAnalysisItem.builder().id(1000L + i).analysisId(a.getId()).orderIndex(i).text("항목 " + i).completed(i < completed).build());
        }
        when(items.findByAnalysisIdAndDeletedFalseOrderByOrderIndexAsc(a.getId())).thenReturn(list);
    }

    @Test void A_roadmapMiddlePlannerRecommendsExactNextWeekDay() {
        Planner cur = roadmap(2291L, USER, 11, 2, LocalDate.of(2026, 11, 17));
        Planner next = roadmap(2292L, USER, 11, 3, LocalDate.of(2026, 11, 18));
        Planner later = roadmap(2293L, USER, 11, 4, LocalDate.of(2026, 11, 19));
        Planner prev = roadmap(2290L, USER, 11, 1, LocalDate.of(2026, 11, 16));
        when(planners.findById(2291L)).thenReturn(Optional.of(cur));
        when(planners.findByUserIdAndSourceRoadmapId(USER, ROADMAP)).thenReturn(List.of(later, prev, cur, next));
        when(materials.findByPlannerIdAndMaterialType(2292L, MaterialType.PLANNER))
                .thenReturn(List.of(Material.builder().materialId(314L).userId(USER).materialType(MaterialType.PLANNER).plannerId(2292L).build()));
        checklist(2291L, 3, 3);

        NextLearningResponse r = service.recommend(USER, 2291L);

        assertTrue(r.isAvailable());
        assertEquals("READY", r.getStatus());
        assertEquals("ROADMAP_NEXT", r.getRecommendationType());
        assertEquals(2292L, r.getNextPlannerId());
        assertEquals(314L, r.getNextMaterialId());
        assertEquals(11, r.getRoadmapWeek()); assertEquals(3, r.getRoadmapDay());
        assertEquals(LocalDate.of(2026, 11, 18), r.getPlannerDate());
        assertEquals(1.0, r.getCompletionRate());
        assertEquals("현재 로드맵의 다음 학습 순서입니다.", r.getReason());
        // 추천만 한다: 어떤 저장도 없다
        verify(planners, never()).save(any());
        verify(materials, never()).save(any());
    }

    @Test void B_incompleteCurrentPlannerIsInProgressButStillShowsNext() {
        Planner cur = roadmap(2291L, USER, 11, 2, LocalDate.of(2026, 11, 17));
        Planner next = roadmap(2292L, USER, 11, 3, LocalDate.of(2026, 11, 18));
        when(planners.findById(2291L)).thenReturn(Optional.of(cur));
        when(planners.findByUserIdAndSourceRoadmapId(USER, ROADMAP)).thenReturn(List.of(cur, next));
        checklist(2291L, 4, 2);

        NextLearningResponse r = service.recommend(USER, 2291L);

        assertTrue(r.isAvailable());
        assertEquals("IN_PROGRESS", r.getStatus());
        assertEquals(2292L, r.getNextPlannerId());
        assertEquals(0.5, r.getCompletionRate());
        assertEquals(4, r.getChecklistTotal()); assertEquals(2, r.getChecklistCompleted());
        assertEquals("현재 계획이 아직 진행 중입니다. 완료 후 다음 학습으로 이동할 수 있습니다.", r.getReason());
    }

    @Test void B2_noChecklistIsNotTreatedAsComplete() {
        Planner cur = roadmap(2291L, USER, 11, 2, LocalDate.of(2026, 11, 17));
        Planner next = roadmap(2292L, USER, 11, 3, LocalDate.of(2026, 11, 18));
        when(planners.findById(2291L)).thenReturn(Optional.of(cur));
        when(planners.findByUserIdAndSourceRoadmapId(USER, ROADMAP)).thenReturn(List.of(cur, next));

        NextLearningResponse r = service.recommend(USER, 2291L);
        assertEquals("IN_PROGRESS", r.getStatus());
        assertNull(r.getCompletionRate());
        assertEquals(0, r.getChecklistTotal());
    }

    @Test void C_lastRoadmapPlannerHasNoNext() {
        Planner cur = roadmap(2400L, USER, 12, 7, LocalDate.of(2026, 11, 30));
        when(planners.findById(2400L)).thenReturn(Optional.of(cur));
        when(planners.findByUserIdAndSourceRoadmapId(USER, ROADMAP)).thenReturn(List.of(
                roadmap(2399L, USER, 12, 6, LocalDate.of(2026, 11, 29)), cur));
        checklist(2400L, 2, 2);

        NextLearningResponse r = service.recommend(USER, 2400L);
        assertFalse(r.isAvailable());
        assertEquals("NO_NEXT", r.getStatus());
        assertNull(r.getNextPlannerId());
        assertEquals("현재 등록된 다음 학습 계획이 없습니다.", r.getReason());
    }

    @Test void D_userPlannerRecommendsNearestLaterSameSubjectPlanner() {
        Planner cur = user(10L, USER, "자료구조", LocalDate.of(2026, 9, 10));
        Planner nearest = user(12L, USER, "자료구조", LocalDate.of(2026, 9, 12));
        when(planners.findById(10L)).thenReturn(Optional.of(cur));
        when(planners.findNextUserPlanners(eq(USER), eq(10L), eq("자료구조"), eq(LocalDate.of(2026, 9, 10)), any()))
                .thenReturn(List.of(nearest));
        checklist(10L, 1, 1);

        NextLearningResponse r = service.recommend(USER, 10L);
        assertTrue(r.isAvailable());
        assertEquals("READY", r.getStatus());
        assertEquals("USER_NEXT", r.getRecommendationType());
        assertEquals(12L, r.getNextPlannerId());
        assertNull(r.getNextMaterialId());
        assertEquals("같은 과목에서 예정된 다음 학습 계획입니다.", r.getReason());
        verify(planners, never()).findByUserIdAndSourceRoadmapId(anyLong(), anyLong());
    }

    @Test void E_userPlannerWithoutLaterPlannerIsNoNext() {
        Planner cur = user(10L, USER, "자료구조", LocalDate.of(2026, 9, 10));
        when(planners.findById(10L)).thenReturn(Optional.of(cur));
        when(planners.findNextUserPlanners(anyLong(), anyLong(), any(), any(), any())).thenReturn(List.of());

        NextLearningResponse r = service.recommend(USER, 10L);
        assertFalse(r.isAvailable());
        assertEquals("NO_NEXT", r.getStatus());
        assertNull(r.getRecommendationType());
    }

    @Test void F_otherUsersPlannersAreNeverRecommendedAndOwnershipIsEnforced() {
        Planner cur = roadmap(2291L, USER, 11, 2, LocalDate.of(2026, 11, 17));
        Planner foreign = roadmap(2292L, OTHER_USER, 11, 3, LocalDate.of(2026, 11, 18));
        when(planners.findById(2291L)).thenReturn(Optional.of(cur));
        // 저장소가 잘못 섞어 돌려줘도 다른 사용자 행은 걸러진다
        when(planners.findByUserIdAndSourceRoadmapId(USER, ROADMAP)).thenReturn(List.of(cur, foreign));

        NextLearningResponse r = service.recommend(USER, 2291L);
        assertFalse(r.isAvailable());
        assertEquals("NO_NEXT", r.getStatus());
        assertNull(r.getNextPlannerId());

        // 남의 플래너를 현재 플래너로 조회하면 거부
        when(planners.findById(2292L)).thenReturn(Optional.of(foreign));
        assertThrows(SecurityException.class, () -> service.recommend(USER, 2292L));
    }

    @Test void G_orderFollowsRoadmapWeekDayNotPlannerId() {
        // planner_id 는 뒤죽박죽: 다음 순서(11주차 3일)의 id 가 현재보다 작고, id 가 큰 행은 이전 주차다
        Planner cur = roadmap(2291L, USER, 11, 2, LocalDate.of(2026, 11, 17));
        Planner next = roadmap(1500L, USER, 11, 3, LocalDate.of(2026, 11, 18));
        Planner bigIdButEarlier = roadmap(9999L, USER, 10, 7, LocalDate.of(2026, 11, 15));
        Planner nextWeek = roadmap(1400L, USER, 12, 1, LocalDate.of(2026, 11, 23));
        when(planners.findById(2291L)).thenReturn(Optional.of(cur));
        when(planners.findByUserIdAndSourceRoadmapId(USER, ROADMAP)).thenReturn(List.of(bigIdButEarlier, nextWeek, cur, next));
        checklist(2291L, 1, 1);

        NextLearningResponse r = service.recommend(USER, 2291L);
        assertEquals(1500L, r.getNextPlannerId());
        assertEquals("[로드맵 11주차 3일] 주제 11-3", r.getTitle());

        // 컬럼(roadmapWeek/day)이 채워진 행은 컬럼을 우선 사용한다(제목보다 우선)
        Planner cur2 = Planner.builder().id(50L).userId(USER).plannerType(PlannerType.ROADMAP).sourceRoadmapId(ROADMAP)
                .roadmapWeek(2).roadmapDay(5).title("제목 없음 형식").plannerDate(LocalDate.of(2026, 1, 12)).build();
        Planner next2 = Planner.builder().id(40L).userId(USER).plannerType(PlannerType.ROADMAP).sourceRoadmapId(ROADMAP)
                .roadmapWeek(2).roadmapDay(6).title("제목 없음 형식").plannerDate(LocalDate.of(2026, 1, 13)).build();
        when(planners.findById(50L)).thenReturn(Optional.of(cur2));
        when(planners.findByUserIdAndSourceRoadmapId(USER, ROADMAP)).thenReturn(List.of(next2, cur2));
        assertEquals(40L, service.recommend(USER, 50L).getNextPlannerId());
    }

    @Test void H_noExternalAiDependencyAtAll() {
        // 서비스는 저장소 4개만 의존한다 — WebClient/RestTemplate/AI 서비스 의존이 존재하지 않는다.
        for (Field f : PlannerNextLearningService.class.getDeclaredFields()) {
            String type = f.getType().getName();
            assertFalse(type.contains("WebClient") || type.contains("RestTemplate") || type.contains("AiIntegration")
                    || type.contains("PlanAnalysisService") || type.contains("PlannerSemanticAnalyzer"), "AI 의존 금지: " + type);
        }
        // 실행 중에도 저장소 외 다른 협력자와 상호작용하지 않는다(모든 협력자가 mock 이고 결과가 결정적)
        Planner cur = roadmap(2291L, USER, 11, 2, LocalDate.of(2026, 11, 17));
        when(planners.findById(2291L)).thenReturn(Optional.of(cur));
        when(planners.findByUserIdAndSourceRoadmapId(USER, ROADMAP)).thenReturn(List.of(cur, roadmap(2292L, USER, 11, 3, LocalDate.of(2026, 11, 18))));
        NextLearningResponse first = service.recommend(USER, 2291L);
        NextLearningResponse second = service.recommend(USER, 2291L);
        assertEquals(first.getNextPlannerId(), second.getNextPlannerId());
        assertEquals(first.getReason(), second.getReason());
    }

    @Test void roadmapPlannerWithoutOrderInfoIsNoData() {
        Planner cur = Planner.builder().id(77L).userId(USER).plannerType(PlannerType.ROADMAP).sourceRoadmapId(ROADMAP).title("순서 없음").build();
        when(planners.findById(77L)).thenReturn(Optional.of(cur));
        NextLearningResponse r = service.recommend(USER, 77L);
        assertEquals("NO_DATA", r.getStatus());
        assertFalse(r.isAvailable());
    }
}
