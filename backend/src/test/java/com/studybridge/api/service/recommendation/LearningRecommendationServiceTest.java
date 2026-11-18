package com.studybridge.api.service.recommendation;

import com.studybridge.api.dto.LearningRecommendationDTO;
import com.studybridge.api.entity.LearningRecommendation;
import com.studybridge.api.entity.LearningRecommendation.Source;
import com.studybridge.api.entity.LearningRecommendation.Status;
import com.studybridge.api.entity.Material;
import com.studybridge.api.entity.MaterialType;
import com.studybridge.api.entity.Planner;
import com.studybridge.api.entity.PlannerType;
import com.studybridge.api.exception.AiUpstreamException;
import com.studybridge.api.repository.*;
import com.studybridge.api.service.AiRequestGuard;
import com.studybridge.api.service.MaterialQuizScoreService;
import com.studybridge.api.service.PlannerNextLearningService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.NoSuchElementException;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicLong;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class LearningRecommendationServiceTest {

    private static final long USER = 55L;
    private static final long OTHER = 56L;

    private PlannerRepository planners;
    private MaterialRepository materials;
    private LearningRecommendationRepository recs;
    private AiRequestGuard guard;
    private AiRecommendationClient ai;
    private PlannerProgressReader progress;
    private LearningRecommendationService service;
    private final List<LearningRecommendation> store = new ArrayList<>();
    private final AtomicLong ids = new AtomicLong(100);

    @BeforeEach
    void setUp() {
        planners = mock(PlannerRepository.class);
        materials = mock(MaterialRepository.class);
        recs = mock(LearningRecommendationRepository.class);
        guard = mock(AiRequestGuard.class);
        ai = mock(AiRecommendationClient.class);
        PlanAnalysisRepository analyses = mock(PlanAnalysisRepository.class);
        PlanAnalysisItemRepository items = mock(PlanAnalysisItemRepository.class);
        when(analyses.findByUserIdAndPlannerIdIn(anyLong(), any())).thenReturn(List.of());
        progress = new PlannerProgressReader(planners, analyses, items, mock(PlannerNextLearningService.class));
        MaterialQuizRepository quizzes = mock(MaterialQuizRepository.class);
        when(quizzes.findByMaterial_MaterialIdOrderByCreatedAtDesc(anyLong())).thenReturn(List.of());
        ReviewNoteRepository notes = mock(ReviewNoteRepository.class);
        when(notes.findByUserIdOrderByCreatedAtDesc(anyLong())).thenReturn(List.of());
        MaterialStudyNoteAnalysisRepository studyNotes = mock(MaterialStudyNoteAnalysisRepository.class);
        when(studyNotes.findByMaterialId(anyLong())).thenReturn(Optional.empty());
        when(guard.allow(anyString(), anyInt(), any())).thenReturn(true);
        when(guard.tryLock(anyString(), any())).thenAnswer(inv -> new AiRequestGuard.Lock(inv.getArgument(0), "t", true));
        when(planners.findNextUserPlanners(anyLong(), anyLong(), anyString(), any(), any())).thenReturn(List.of());

        // 인메모리 저장소(사용자 격리 조건까지 그대로 흉내)
        when(recs.save(any(LearningRecommendation.class))).thenAnswer(inv -> {
            LearningRecommendation r = inv.getArgument(0);
            if (r.getId() == null) { r.setId(ids.incrementAndGet()); store.add(r); }
            return r;
        });
        when(recs.findByUserIdAndDedupKey(anyLong(), anyString())).thenAnswer(inv -> store.stream()
                .filter(r -> r.getUserId().equals(inv.getArgument(0)) && r.getDedupKey().equals(inv.getArgument(1))).findFirst());
        when(recs.findByIdAndUserId(anyLong(), anyLong())).thenAnswer(inv -> store.stream()
                .filter(r -> r.getId().equals(inv.getArgument(0)) && r.getUserId().equals(inv.getArgument(1))).findFirst());
        when(recs.findByUserIdAndPlannerIdAndStatusInOrderByIdAsc(anyLong(), anyLong(), any())).thenAnswer(inv -> store.stream()
                .filter(r -> r.getUserId().equals(inv.getArgument(0)) && inv.getArgument(1).equals(r.getPlannerId())
                        && ((java.util.Collection<?>) inv.getArgument(2)).contains(r.getStatus())).toList());
        when(recs.findByUserIdAndMaterialIdAndPlannerIdIsNullAndStatusInOrderByIdAsc(anyLong(), anyLong(), any())).thenAnswer(inv -> store.stream()
                .filter(r -> r.getUserId().equals(inv.getArgument(0)) && inv.getArgument(1).equals(r.getMaterialId()) && r.getPlannerId() == null
                        && ((java.util.Collection<?>) inv.getArgument(2)).contains(r.getStatus())).toList());
        when(recs.transition(anyLong(), anyLong(), any(), any(), any())).thenAnswer(inv -> {
            for (LearningRecommendation r : store) {
                if (r.getId().equals(inv.getArgument(0)) && r.getUserId().equals(inv.getArgument(1)) && r.getStatus() == inv.getArgument(2)) {
                    r.setStatus(inv.getArgument(3));
                    return 1;
                }
            }
            return 0;
        });
        when(recs.markCompleted(anyLong(), anyLong(), any(), any(), any())).thenAnswer(inv -> {
            for (LearningRecommendation r : store) {
                if (r.getId().equals(inv.getArgument(0)) && r.getUserId().equals(inv.getArgument(1)) && r.getStatus() == Status.ACCEPTED) {
                    r.setStatus(Status.COMPLETED);
                    return 1;
                }
            }
            return 0;
        });
        when(recs.findByUserId(anyLong())).thenAnswer(inv -> store.stream().filter(r -> r.getUserId().equals(inv.getArgument(0))).toList());
        when(planners.save(any(Planner.class))).thenAnswer(inv -> { Planner p = inv.getArgument(0); p.setId(9000L + ids.incrementAndGet()); return p; });

        service = new LearningRecommendationService(progress, planners, materials, quizzes, mock(MaterialQuizScoreService.class), notes,
                studyNotes, mock(RoadmapRepository.class), recs, guard, ai);
    }

    private Planner userPlanner(long id, long owner, String title) {
        Planner p = Planner.builder().id(id).userId(owner).plannerType(PlannerType.USER).title(title).subject("선형대수")
                .plannerDate(LocalDate.of(2026, 10, 13)).build();
        when(planners.findById(id)).thenReturn(Optional.of(p));
        return p;
    }

    @Test
    void generate_forUserPlanner_persistsRuleCandidates_withoutCallingAiWhenFlagOff() {
        userPlanner(10L, USER, "김도현 저자의 선형대수 2장 학습하기");
        LearningRecommendationDTO.ListResponse r = service.generateForPlanner(USER, 10L);
        assertEquals(LearningRecommendationService.MODE_TASK, r.getMode());
        assertEquals(2, r.getItems().size());
        assertTrue(r.getItems().stream().allMatch(i -> "RULE".equals(i.getGenerator()) && "GENERATED".equals(i.getStatus())));
        assertFalse(r.isAiUsed());
        verify(ai, never()).request(anyString(), any(), anyString());
        verify(guard).release(any());
    }

    @Test
    void regenerate_doesNotDuplicate_andRejectedIsNotPresentedAgain() {
        userPlanner(10L, USER, "선형대수 2장 학습하기");
        var first = service.generateForPlanner(USER, 10L);
        service.reject(USER, first.getItems().get(0).getId());
        var second = service.generateForPlanner(USER, 10L);
        assertEquals(2, store.size(), "같은 후보는 다시 저장하지 않는다");
        assertEquals(1, second.getItems().size(), "거절한 후보는 다시 제시하지 않는다");
        assertEquals(2, store.stream().filter(x -> x.getStatus() == Status.GENERATED).findFirst().orElseThrow().getPresentedCount());
        assertEquals(0.3333, service.metrics(USER).getDuplicateRate()); // 제시 3회 중 재제시 1회
    }

    @Test
    void otherUsersPlanner_isForbidden() {
        userPlanner(10L, OTHER, "선형대수 2장 학습하기");
        assertThrows(SecurityException.class, () -> service.generateForPlanner(USER, 10L));
        assertThrows(SecurityException.class, () -> service.listForPlanner(USER, 10L));
    }

    @Test
    void otherUsersRecommendation_cannotBeAcceptedOrRejected() {
        userPlanner(10L, OTHER, "선형대수 2장 학습하기");
        var r = service.generateForPlanner(OTHER, 10L);
        Long id = r.getItems().get(0).getId();
        assertThrows(NoSuchElementException.class, () -> service.accept(USER, id, null));
        assertThrows(NoSuchElementException.class, () -> service.reject(USER, id));
        verify(planners, never()).save(any());
    }

    @Test
    void accept_createsExactlyOnePlanner_andIsIdempotent() {
        userPlanner(10L, USER, "선형대수 2장 학습하기");
        Long id = service.generateForPlanner(USER, 10L).getItems().get(0).getId();
        var req = new LearningRecommendationDTO.AcceptRequest(LocalDate.of(2026, 10, 20), false);
        var a1 = service.accept(USER, id, req);
        var a2 = service.accept(USER, id, req);
        assertEquals("ACCEPTED", a1.getStatus());
        assertEquals(a1.getAcceptedPlannerId(), a2.getAcceptedPlannerId());
        verify(planners, times(1)).save(argThat(p -> p.getPlannerType() == PlannerType.USER
                && "선형대수".equals(p.getSubject()) && LocalDate.of(2026, 10, 20).equals(p.getPlannerDate())
                && p.getMaterialId() == null && p.getDayOfWeek() != null));
        assertThrows(IllegalStateException.class, () -> service.reject(USER, id));
        assertEquals("COMPLETED", service.complete(USER, id).getStatus());
        assertEquals(1.0, service.metrics(USER).getCompletionRate());
    }

    @Test
    void concurrentAccept_loserReturnsWinnerResult_withoutCreatingPlanner() {
        userPlanner(10L, USER, "선형대수 2장 학습하기");
        Long id = service.generateForPlanner(USER, 10L).getItems().get(0).getId();
        LearningRecommendation r = store.stream().filter(x -> x.getId().equals(id)).findFirst().orElseThrow();
        // 다른 요청이 먼저 전이·커밋한 상황: 조건부 UPDATE 0건
        when(recs.transition(eq(id), eq(USER), any(), any(), any())).thenAnswer(inv -> {
            r.setStatus(Status.ACCEPTED);
            r.setAcceptedPlannerId(777L);
            return 0;
        });
        var res = service.accept(USER, id, null);
        assertEquals(777L, res.getAcceptedPlannerId());
        verify(planners, never()).save(any());
    }

    @Test
    void verificationRequired_needsExplicitAcknowledgement() {
        LearningRecommendation r = LearningRecommendation.builder().id(5L).userId(USER).sourceKind(Source.USER_PLANNER)
                .recommendationType("NEXT_CHAPTER").title("선형대수 3장 학습").verificationRequired(true)
                .verificationNote("목차 미확인").generator("RULE").status(Status.GENERATED).dedupKey("k").presentedCount(1).build();
        store.add(r);
        assertThrows(IllegalArgumentException.class, () -> service.accept(USER, 5L, new LearningRecommendationDTO.AcceptRequest(null, false)));
        assertEquals(Status.GENERATED, r.getStatus());
        assertEquals("ACCEPTED", service.accept(USER, 5L, new LearningRecommendationDTO.AcceptRequest(null, true)).getStatus());
    }

    @Test
    void roadmapNodeAccept_linksExistingPlanner_noNewPlanner() {
        Planner node = Planner.builder().id(3001L).userId(USER).plannerType(PlannerType.ROADMAP).title("[로드맵 1주차 2일] 행렬").build();
        when(planners.findById(3001L)).thenReturn(Optional.of(node));
        store.add(LearningRecommendation.builder().id(6L).userId(USER).sourceKind(Source.ROADMAP_PLANNER).recommendationType("ROADMAP_NODE")
                .plannerId(3000L).targetKey("p3001").title("다음 단계").generator("RULE").status(Status.GENERATED).dedupKey("k2").presentedCount(1).build());
        var res = service.accept(USER, 6L, null);
        assertEquals(3001L, res.getAcceptedPlannerId());
        verify(planners, never()).save(any());
    }

    @Test
    void rateLimitAndInFlightLock_areEnforcedPerUser() {
        userPlanner(10L, USER, "선형대수 2장 학습하기");
        when(guard.allow(eq(AiRequestGuard.rateKey("rec", USER)), anyInt(), any())).thenReturn(false);
        AiUpstreamException e = assertThrows(AiUpstreamException.class, () -> service.generateForPlanner(USER, 10L));
        assertEquals(HttpStatus.TOO_MANY_REQUESTS, e.getStatus());
        when(guard.allow(anyString(), anyInt(), any())).thenReturn(true);
        when(guard.tryLock(anyString(), any())).thenReturn(new AiRequestGuard.Lock("k", "t", false));
        assertEquals(HttpStatus.CONFLICT, assertThrows(AiUpstreamException.class, () -> service.generateForPlanner(USER, 10L)).getStatus());
    }

    @Test
    void documentMode_whenPlannerMissing_andAiHallucinationsAreDiscardedNotPresented() {
        Material m = Material.builder().materialId(345L).userId(USER).materialType(MaterialType.PDF).title("ViewModel 정리")
                .keywords("ViewModel, SavedStateHandle").build();
        when(materials.findById(345L)).thenReturn(Optional.of(m));
        when(ai.enabled()).thenReturn(true);
        when(ai.request(eq(AiRecommendationClient.PATH_DOCUMENT), any(), anyString())).thenReturn(Optional.of(new AiRecommendationClient.Response(
                List.of(new AiCandidateValidator.RawCandidate("DOCUMENT_DEEP_DIVE", "Activity 간 ViewModel 공유", "x", List.of("QUIZ:999"), null, null, null),
                        new AiCandidateValidator.RawCandidate("DOCUMENT_DEEP_DIVE", "SavedStateHandle 로 프로세스 종료 복원 실습", "y",
                                List.of("MATERIAL:345"), null, null, null)),
                List.of(), "ollama", "qwen2.5")));

        var r = service.generateForMaterial(USER, 345L);

        assertEquals(LearningRecommendationService.MODE_DOCUMENT, r.getMode());
        assertTrue(r.isAiUsed());
        assertEquals(1, r.getAiDiscarded());
        assertTrue(r.getItems().stream().noneMatch(i -> i.getTitle().contains("Activity 간")));
        assertTrue(r.getItems().stream().anyMatch(i -> "AI".equals(i.getGenerator()) && "ollama".equals(i.getModelProvider())));
        assertEquals(1, store.stream().filter(x -> x.getStatus() == Status.DISCARDED).count());
        var metrics = service.metrics(USER);
        assertEquals(2, metrics.getAiCandidates());
        assertEquals(0.5, metrics.getHallucinationRate());
        assertEquals(0.5, metrics.getEvidenceMatchRate());
        // 실제 전송 payload 에는 사용자 식별자가 없다
        verify(ai).request(eq(AiRecommendationClient.PATH_DOCUMENT), argThat((Map<String, Object> p) ->
                !p.containsKey("userId") && !p.containsKey("email")), anyString());
    }

    @Test
    void metrics_noData_areNullNotFabricated() {
        var m = service.metrics(USER);
        assertNull(m.getAcceptanceRate());
        assertNull(m.getCompletionRate());
        assertNull(m.getHallucinationRate());
        assertNotNull(m.getNote());
    }
}
