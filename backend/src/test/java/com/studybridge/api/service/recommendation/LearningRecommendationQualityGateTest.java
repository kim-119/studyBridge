package com.studybridge.api.service.recommendation;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.ai.quality.GateEvidence;
import com.studybridge.api.dto.LearningRecommendationDTO;
import com.studybridge.api.entity.LearningRecommendation;
import com.studybridge.api.entity.LearningRecommendation.Status;
import com.studybridge.api.entity.Material;
import com.studybridge.api.entity.MaterialType;
import com.studybridge.api.entity.Planner;
import com.studybridge.api.entity.PlannerType;
import com.studybridge.api.exception.AiUpstreamException;
import com.studybridge.api.repository.LearningRecommendationRepository;
import com.studybridge.api.repository.MaterialQuizRepository;
import com.studybridge.api.repository.MaterialRepository;
import com.studybridge.api.repository.MaterialStudyNoteAnalysisRepository;
import com.studybridge.api.repository.PlanAnalysisItemRepository;
import com.studybridge.api.repository.PlanAnalysisRepository;
import com.studybridge.api.repository.PlannerRepository;
import com.studybridge.api.repository.ReviewNoteRepository;
import com.studybridge.api.repository.RoadmapRepository;
import com.studybridge.api.service.AiRequestGuard;
import com.studybridge.api.service.MaterialQuizScoreService;
import com.studybridge.api.service.PlannerNextLearningService;
import com.studybridge.api.service.PlannerQualityGateSupport;
import com.studybridge.api.service.support.ChatGateStubServer;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicLong;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

/**
 * 학습 추천 품질 게이트(PLANNER_COACHING/text): 생성은 79 거절(저장 0)·80 승인(quality_status=APPROVED 저장), AI 후보 경로 ON 인데
 * ai07 무응답이면 503(규칙 폴백 성공 위장 없음), 재노출(목록·승인/거절/완료 응답)은 미검증 문구 가림, 미검증 추천 승인 거부, 게이트 OFF 회귀 없음.
 */
class LearningRecommendationQualityGateTest {

    static final long USER = 55L;
    static final long PLANNER = 10L;
    static final long MATERIAL = 31L;
    static final ObjectMapper M = new ObjectMapper().findAndRegisterModules();
    ChatGateStubServer stub;
    PlannerRepository planners;
    MaterialRepository materials;
    LearningRecommendationRepository recs;
    AiRecommendationClient ai;
    PlannerProgressReader progress;
    MaterialQuizRepository quizzes;
    ReviewNoteRepository notes;
    MaterialStudyNoteAnalysisRepository studyNotes;
    AiRequestGuard guard;
    final List<LearningRecommendation> store = new ArrayList<>();
    final AtomicLong ids = new AtomicLong(100);

    @BeforeEach
    void setUp() throws Exception {
        stub = new ChatGateStubServer();
        planners = mock(PlannerRepository.class);
        materials = mock(MaterialRepository.class);
        recs = mock(LearningRecommendationRepository.class);
        guard = mock(AiRequestGuard.class);
        ai = mock(AiRecommendationClient.class);
        PlanAnalysisRepository analyses = mock(PlanAnalysisRepository.class);
        when(analyses.findByUserIdAndPlannerIdIn(anyLong(), any())).thenReturn(List.of());
        progress = new PlannerProgressReader(planners, analyses, mock(PlanAnalysisItemRepository.class), mock(PlannerNextLearningService.class));
        quizzes = mock(MaterialQuizRepository.class);
        when(quizzes.findByMaterial_MaterialIdOrderByCreatedAtDesc(anyLong())).thenReturn(List.of());
        notes = mock(ReviewNoteRepository.class);
        when(notes.findByUserIdOrderByCreatedAtDesc(anyLong())).thenReturn(List.of());
        studyNotes = mock(MaterialStudyNoteAnalysisRepository.class);
        when(studyNotes.findByMaterialId(anyLong())).thenReturn(Optional.empty());
        when(guard.allow(anyString(), anyInt(), any())).thenReturn(true);
        when(guard.tryLock(anyString(), any())).thenAnswer(inv -> new AiRequestGuard.Lock(inv.getArgument(0), "t", true));
        when(planners.findNextUserPlanners(anyLong(), anyLong(), anyString(), any(), any())).thenReturn(List.of());
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
        when(planners.save(any(Planner.class))).thenAnswer(inv -> { Planner p = inv.getArgument(0); p.setId(9000L + ids.incrementAndGet()); return p; });
        Planner p = Planner.builder().id(PLANNER).userId(USER).plannerType(PlannerType.USER).title("김도현 저자의 선형대수 2장 학습하기")
                .subject("선형대수").content("2장 행렬 연산 정리").plannerDate(LocalDate.of(2026, 10, 13)).build();
        when(planners.findById(PLANNER)).thenReturn(Optional.of(p));
        when(materials.findById(MATERIAL)).thenReturn(Optional.of(Material.builder().materialId(MATERIAL).userId(USER)
                .materialType(MaterialType.PDF).title("합성곱 신경망").keywords("합성곱, 풀링")
                .extractedText("합성곱 신경망은 합성곱과 풀링으로 특징을 추출한다. ".repeat(10)).build()));
    }

    @AfterEach
    void down() {
        stub.close();
    }

    LearningRecommendationService svc(boolean gateOn) {
        LearningRecommendationService s = new LearningRecommendationService(progress, planners, materials, quizzes,
                mock(MaterialQuizScoreService.class), notes, studyNotes, mock(RoadmapRepository.class), recs, guard, ai);
        s.setQualityGate(stub.gate(gateOn));
        return s;
    }

    @GateEvidence({"POST /api/planners/{plannerId}/recommendations"})
    @Test
    void rejected79SavesNothingAndApproved80SavesWithStatus() {
        stub.policy = (n, in) -> ChatGateStubServer.out(79, "REJECTED", false);
        AiUpstreamException e = assertThrows(AiUpstreamException.class, () -> svc(true).generateForPlanner(USER, PLANNER));
        assertEquals("AI_QUALITY_REJECTED", e.getCode());
        assertEquals(422, e.getStatus().value());
        assertTrue(store.isEmpty(), "거절된 후보는 저장하지 않는다");
        verify(recs, never()).save(any());
        assertEquals(1, stub.evaluations.size(), "결정적 후보 — 같은 초안 반복 평가 없음");
        JsonNode ev = stub.evaluations.get(0);
        assertEquals("PLANNER_COACHING", ev.get("taskType").asText());
        assertEquals("text", ev.get("outputKind").asText());
        assertTrue(ev.get("proposedOutput").asText().contains("선형대수"), "후보 제목·사유 전체 평가");
        assertEquals("PLANNER_RECORD", ev.get("groundingEvidence").get(0).get("sourceType").asText());

        stub.policy = (n, in) -> ChatGateStubServer.out(80, "APPROVED", false);
        LearningRecommendationDTO.ListResponse r = svc(true).generateForPlanner(USER, PLANNER);
        assertEquals("APPROVED", r.getQualityStatus());
        assertFalse(r.getItems().isEmpty());
        assertTrue(store.stream().allMatch(x -> "APPROVED".equals(x.getQualityStatus())));
        assertTrue(r.getItems().stream().allMatch(i -> "APPROVED".equals(i.getQualityStatus()) && i.getQualityRedacted() == null));
    }

    @Test
    void aiRouteMissingIsExplicitFailureNotRuleFallback() {
        when(ai.enabled()).thenReturn(true);
        when(ai.request(anyString(), any(), anyString())).thenReturn(Optional.empty()); // ai07 라우트 없음(404) → empty
        AiUpstreamException e = assertThrows(AiUpstreamException.class, () -> svc(true).generateForPlanner(USER, PLANNER));
        assertEquals("RECOMMENDATION_AI_UNAVAILABLE", e.getCode());
        assertEquals(503, e.getStatus().value());
        assertTrue(store.isEmpty());
        assertEquals(0, stub.evaluations.size());
        // 게이트 OFF 는 기존대로 규칙 추천 폴백
        assertFalse(svc(false).generateForPlanner(USER, PLANNER).getItems().isEmpty());
    }

    @GateEvidence({"GET /api/planners/{plannerId}/recommendations"})
    @Test
    void legacyRowsAreRedactedUntilRegeneratedUnderGate() throws Exception {
        svc(false).generateForPlanner(USER, PLANNER); // 게이트 OFF 생성 = 미검증 행
        assertTrue(store.stream().allMatch(x -> x.getQualityStatus() == null));
        String legacyTitle = store.get(0).getTitle();
        LearningRecommendationDTO.ListResponse hidden = svc(true).listForPlanner(USER, PLANNER);
        assertTrue(hidden.getItems().stream().allMatch(i -> Boolean.TRUE.equals(i.getQualityRedacted())));
        assertFalse(M.writeValueAsString(hidden).contains(legacyTitle), "미검증 문구 0");
        assertTrue(hidden.getItems().stream().allMatch(i -> i.getEvidence().stream().noneMatch(m -> m.containsKey("label"))));
        // 게이트 ON 재생성(승인) → 다시 제시되는 행도 승인 문구·판정으로 갱신
        stub.policy = (n, in) -> ChatGateStubServer.out(90, "APPROVED", false);
        svc(true).generateForPlanner(USER, PLANNER);
        assertTrue(store.stream().allMatch(x -> "APPROVED".equals(x.getQualityStatus())));
        LearningRecommendationDTO.ListResponse shown = svc(true).listForPlanner(USER, PLANNER);
        assertTrue(shown.getItems().stream().allMatch(i -> "APPROVED".equals(i.getQualityStatus())));
        assertTrue(M.writeValueAsString(shown).contains(legacyTitle));
        assertTrue(stub.evaluations.size() >= 1);
    }

    @GateEvidence({"POST /api/materials/{materialId}/recommendations", "GET /api/materials/{materialId}/recommendations"})
    @Test
    void documentRecommendationsAreGatedWithMaterialEvidence() throws Exception {
        stub.policy = (n, in) -> ChatGateStubServer.out(60, "REJECTED", true);
        assertThrows(AiUpstreamException.class, () -> svc(true).generateForMaterial(USER, MATERIAL));
        assertTrue(store.isEmpty());
        JsonNode ev = stub.evaluations.get(0);
        assertEquals("PDF_ORIGINAL", ev.get("groundingEvidence").get(0).get("sourceType").asText(), "근거 = 자료 원문");
        assertEquals(MATERIAL, ev.get("constraints").get("allowedMaterialIds").get(0).asLong());
        assertTrue(ev.get("proposedOutput").asText().contains("합성곱"));
        assertTrue(svc(true).listForMaterial(USER, MATERIAL).getItems().isEmpty());

        stub.policy = (n, in) -> ChatGateStubServer.out(80, "APPROVED", false);
        LearningRecommendationDTO.ListResponse r = svc(true).generateForMaterial(USER, MATERIAL);
        assertEquals("APPROVED", r.getQualityStatus());
        assertTrue(store.stream().allMatch(x -> "APPROVED".equals(x.getQualityStatus())));
        LearningRecommendationDTO.ListResponse list = svc(true).listForMaterial(USER, MATERIAL);
        assertTrue(M.writeValueAsString(list).contains("합성곱"));
        assertTrue(list.getItems().stream().allMatch(i -> "APPROVED".equals(i.getQualityStatus())));
    }

    @GateEvidence({"POST /api/recommendations/{id}/accept"})
    @Test
    void unverifiedRecommendationCannotBeAcceptedIntoPlanner() {
        svc(false).generateForPlanner(USER, PLANNER);
        Long legacyId = store.get(0).getId();
        AiUpstreamException e = assertThrows(AiUpstreamException.class, () -> svc(true).accept(USER, legacyId, null));
        assertEquals("RECOMMENDATION_NOT_VERIFIED", e.getCode());
        assertEquals(409, e.getStatus().value());
        verify(planners, never()).save(any());
        assertEquals(Status.GENERATED, store.get(0).getStatus());
        // 게이트 ON 승인 생성분은 승인 가능 — 플래너 제목 = 승인 문구
        svc(true).generateForPlanner(USER, PLANNER);
        LearningRecommendationDTO.Item accepted = svc(true).accept(USER, legacyId, null);
        assertEquals("ACCEPTED", accepted.getStatus());
        assertEquals("APPROVED", accepted.getQualityStatus());
        assertEquals(store.get(0).getTitle(), accepted.getTitle());
        verify(planners).save(any(Planner.class));
    }

    @GateEvidence({"POST /api/recommendations/{id}/reject", "POST /api/recommendations/{id}/complete"})
    @Test
    void rejectAndCompleteResponsesRedactUnverifiedText() throws Exception {
        svc(false).generateForPlanner(USER, PLANNER);
        LearningRecommendation legacy = store.get(0);
        String legacyTitle = legacy.getTitle();
        LearningRecommendationDTO.Item rejected = svc(true).reject(USER, legacy.getId());
        assertEquals("REJECTED", rejected.getStatus(), "상태 전이는 그대로");
        assertEquals(Boolean.TRUE, rejected.getQualityRedacted());
        assertFalse(M.writeValueAsString(rejected).contains(legacyTitle));
        // 승인된 행은 완료 응답에 문구가 보인다
        stub.policy = (n, in) -> ChatGateStubServer.out(85, "APPROVED", false);
        svc(true).generateForPlanner(USER, PLANNER);
        LearningRecommendation approved = store.stream().filter(x -> x.getStatus() == Status.GENERATED).findFirst().orElseThrow();
        assertEquals(PlannerQualityGateSupport.APPROVED, approved.getQualityStatus());
        svc(true).accept(USER, approved.getId(), null);
        LearningRecommendationDTO.Item done = svc(true).complete(USER, approved.getId());
        assertEquals("COMPLETED", done.getStatus());
        assertEquals(approved.getTitle(), done.getTitle());
        assertNull(done.getQualityRedacted());
        // 미검증 완료 응답도 가린다
        legacy.setStatus(Status.ACCEPTED);
        LearningRecommendationDTO.Item legacyDone = svc(true).complete(USER, legacy.getId());
        assertEquals(Boolean.TRUE, legacyDone.getQualityRedacted());
        assertFalse(M.writeValueAsString(legacyDone).contains(legacyTitle));
    }

    @Test
    void gateOffIsLegacyBehaviour() throws Exception {
        LearningRecommendationDTO.ListResponse r = svc(false).generateForPlanner(USER, PLANNER);
        assertNull(r.getQualityStatus());
        assertEquals(0, stub.evaluations.size(), "게이트 OFF: 평가기 호출 0");
        assertTrue(store.stream().allMatch(x -> x.getQualityStatus() == null));
        String json = M.writeValueAsString(svc(false).listForPlanner(USER, PLANNER));
        assertFalse(json.contains("qualityRedacted") || json.contains("qualityStatus"), "게이트 OFF 응답 형태 동일");
        assertTrue(json.contains(store.get(0).getTitle()));
    }
}
