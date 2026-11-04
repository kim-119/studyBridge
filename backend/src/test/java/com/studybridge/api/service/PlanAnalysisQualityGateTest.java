package com.studybridge.api.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.ai.quality.GateEvidence;
import com.studybridge.api.dto.PlanAnalysisDTO;
import com.studybridge.api.entity.Material;
import com.studybridge.api.entity.MaterialType;
import com.studybridge.api.entity.PlanAnalysis;
import com.studybridge.api.entity.PlanAnalysisItem;
import com.studybridge.api.entity.Planner;
import com.studybridge.api.exception.AiUpstreamException;
import com.studybridge.api.repository.MaterialRepository;
import com.studybridge.api.repository.PlanAnalysisItemRepository;
import com.studybridge.api.repository.PlanAnalysisRepository;
import com.studybridge.api.repository.PlannerRepository;
import com.studybridge.api.service.support.ChatGateStubServer;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicLong;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

/**
 * 자료(PLANNER) AI 계획 분석 품질 게이트(PLANNER_COACHING/text) + 저장본 재노출(조회·항목 변경·다음 학습 추천):
 * 79 거절 → 80 승인분만 저장(plan_analysis.quality_status), 전부 거절·평가기 503 은 422/503 + 기존 분석 보존,
 * 게이트 ON 에서 미검증 AI 분석의 AI 문구(요약·추천·항목) 가림, PDF 결정적 분석은 그대로, 게이트 OFF 회귀 없음.
 */
class PlanAnalysisQualityGateTest {

    static final long USER = 11L;
    static final long MATERIAL = 801L;
    static final long PLANNER = 802L;
    static final ObjectMapper M = new ObjectMapper();
    ChatGateStubServer stub;
    final List<PlanAnalysis> analyses = new ArrayList<>();
    final List<PlanAnalysisItem> items = new ArrayList<>();
    final AtomicLong ids = new AtomicLong(1000);
    PlanAnalysisRepository analysisRepo;
    PlanAnalysisItemRepository itemRepo;

    @BeforeEach
    void up() throws Exception {
        stub = new ChatGateStubServer();
        stub.json("/api/ai/planner/analyze", n -> "{\"title\":\"합성곱 연산\",\"keywords\":[\"합성곱\"],\"learningGoal\":\"합성곱 연산 원리를 이해한다\","
                + "\"schedule\":[\"09:00 개념 정리\"],\"checklist\":[\"초안 " + n + " 체크: 3x3 커널 손계산\",\"Conv2d 실습\"],"
                + "\"aiFeedback\":\"초안 " + n + " 피드백: 계획이 구체적입니다.\",\"problemPoints\":[\"실습 시간이 짧습니다\"],"
                + "\"balanceAssessment\":\"균형이 적절합니다.\",\"improvementActions\":[\"실습을 10분 늘리세요\"],"
                + "\"nextRecommendations\":[\"초안 " + n + " 추천: 풀링 학습\"],\"unfinishedItems\":[]}");
    }

    @AfterEach
    void down() {
        stub.close();
    }

    PlanAnalysisService service(boolean gateOn) {
        MaterialRepository materials = mock(MaterialRepository.class);
        when(materials.findById(MATERIAL)).thenReturn(Optional.of(Material.builder().materialId(MATERIAL).userId(USER)
                .materialType(MaterialType.PLANNER).plannerId(PLANNER).title("합성곱 연산").build()));
        PlannerRepository planners = mock(PlannerRepository.class);
        when(planners.findById(PLANNER)).thenReturn(Optional.of(Planner.builder().id(PLANNER).userId(USER).title("합성곱 연산")
                .subject("딥러닝").content("합성곱 연산 원리를 이해한다").tmi("3x3 커널 손계산, Conv2d 실습").build()));
        analysisRepo = mock(PlanAnalysisRepository.class);
        when(analysisRepo.save(any(PlanAnalysis.class))).thenAnswer(inv -> {
            PlanAnalysis a = inv.getArgument(0);
            if (a.getId() == null) { a.setId(ids.incrementAndGet()); analyses.add(a); }
            return a;
        });
        when(analysisRepo.findTopByUserIdAndMaterialIdOrderByIdDesc(anyLong(), anyLong())).thenAnswer(inv -> analyses.stream()
                .filter(a -> a.getUserId().equals(inv.getArgument(0)) && a.getMaterialId().equals(inv.getArgument(1)))
                .max(Comparator.comparing(PlanAnalysis::getId)));
        when(analysisRepo.findById(anyLong())).thenAnswer(inv -> analyses.stream().filter(a -> a.getId().equals(inv.getArgument(0))).findFirst());
        org.mockito.Mockito.doAnswer(inv -> analyses.remove((PlanAnalysis) inv.getArgument(0))).when(analysisRepo).delete(any(PlanAnalysis.class));
        itemRepo = mock(PlanAnalysisItemRepository.class);
        when(itemRepo.save(any(PlanAnalysisItem.class))).thenAnswer(inv -> {
            PlanAnalysisItem i = inv.getArgument(0);
            if (i.getId() == null) { i.setId(ids.incrementAndGet()); items.add(i); }
            return i;
        });
        when(itemRepo.findByAnalysisIdOrderByOrderIndexAsc(anyLong())).thenAnswer(inv -> items.stream()
                .filter(i -> i.getAnalysisId().equals(inv.getArgument(0))).sorted(Comparator.comparing(PlanAnalysisItem::getOrderIndex)).toList());
        when(itemRepo.findById(anyLong())).thenAnswer(inv -> items.stream().filter(i -> i.getId().equals(inv.getArgument(0))).findFirst());
        org.mockito.Mockito.doAnswer(inv -> items.removeIf(i -> i.getAnalysisId().equals(inv.getArgument(0))))
                .when(itemRepo).deleteByAnalysisId(anyLong());
        PlanAnalysisService svc = new PlanAnalysisService(analysisRepo, itemRepo, planners, materials, mock(PlanTextAnalyzer.class),
                stub.client(), M);
        svc.setQualityGate(stub.gate(gateOn));
        return svc;
    }

    /** 게이트 OFF 시절(미검증) AI 분석 1건 + 항목 1개. */
    PlanAnalysisItem legacyAiAnalysis(String quality) {
        PlanAnalysis a = PlanAnalysis.builder().id(ids.incrementAndGet()).userId(USER).materialId(MATERIAL).plannerId(PLANNER)
                .sourceType("PLANNER").summary("레거시 미검증 피드백").recommendation("레거시 미검증 추천")
                .plannerAnalysisJson("{\"aiFeedback\":\"레거시 미검증 피드백\",\"nextRecommendations\":[\"레거시 미검증 추천\"]}")
                .qualityStatus(quality).build();
        analyses.add(a);
        PlanAnalysisItem i = PlanAnalysisItem.builder().id(ids.incrementAndGet()).analysisId(a.getId()).orderIndex(0).type("ACTION")
                .text("레거시 미검증 항목").sourceText("레거시 미검증 항목").sourceType("PLANNER").completed(false).hidden(false).deleted(false).build();
        items.add(i);
        return i;
    }

    @GateEvidence({"POST /api/materials/{materialId}/plan-analysis"})
    @Test
    void rejected79ThenApproved80IsSavedWithStatus() {
        stub.policy = (n, in) -> n == 1 ? ChatGateStubServer.out(79, "REJECTED", false) : ChatGateStubServer.out(80, "APPROVED", false);
        PlanAnalysisDTO.Response r = service(true).analyze(USER, MATERIAL);
        assertEquals("APPROVED", r.getQualityStatus());
        assertTrue(r.getSummary().startsWith("초안 2"));
        assertEquals(2, stub.calls("/api/ai/planner/analyze"));
        assertEquals(1, analyses.size());
        assertEquals("APPROVED", analyses.get(0).getQualityStatus());
        assertTrue(analyses.get(0).getPlannerAnalysisJson().contains("초안 2") && !analyses.get(0).getPlannerAnalysisJson().contains("초안 1"));
        assertTrue(items.stream().anyMatch(i -> i.getText().startsWith("초안 2 체크")));
        assertTrue(items.stream().noneMatch(i -> i.getText().contains("초안 1")));
        JsonNode ev = stub.evaluations.get(0);
        assertEquals("PLANNER_COACHING", ev.get("taskType").asText());
        assertEquals("text", ev.get("outputKind").asText());
        String proposed = ev.get("proposedOutput").asText();
        assertTrue(proposed.contains("초안 1 체크") && proposed.contains("초안 1 추천") && proposed.contains("실습을 10분"),
                "저장될 항목 문구·추천·개선 행동 전부 평가");
        assertEquals("PLANNER_RECORD", ev.get("groundingEvidence").get(0).get("sourceType").asText());
    }

    @GateEvidence({"POST /api/materials/{materialId}/plan-analysis"})
    @Test
    void threeRejectionsKeepExistingAnalysisAndSaveNothing() {
        stub.policy = (n, in) -> ChatGateStubServer.out(60, "REJECTED", false);
        legacyAiAnalysis("APPROVED");
        PlanAnalysisService svc = service(true);
        AiUpstreamException e = assertThrows(AiUpstreamException.class, () -> svc.analyze(USER, MATERIAL));
        assertEquals("AI_QUALITY_REJECTED", e.getCode());
        assertEquals(422, e.getStatus().value());
        assertEquals(3, stub.calls("/api/ai/planner/analyze"));
        verify(analysisRepo, never()).save(any());
        verify(itemRepo, never()).save(any());
        verify(analysisRepo, never()).delete(any());
        assertEquals(1, analyses.size(), "기존 분석은 지우지 않는다");
        assertTrue(items.stream().noneMatch(i -> i.getText().contains("초안")));
    }

    @Test
    void evaluatorDownIsUnavailable() {
        stub.policy = (n, in) -> null;
        AiUpstreamException e = assertThrows(AiUpstreamException.class, () -> service(true).analyze(USER, MATERIAL));
        assertEquals("AI_QUALITY_UNAVAILABLE", e.getCode());
        assertEquals(503, e.getStatus().value());
        assertEquals(1, stub.calls("/api/ai/planner/analyze"));
        verify(analysisRepo, never()).save(any());
    }

    @GateEvidence({"GET /api/materials/{materialId}/plan-analysis"})
    @Test
    void unverifiedAiAnalysisIsRedactedThenApprovedOneIsShown() throws Exception {
        legacyAiAnalysis(null);
        PlanAnalysisService svc = service(true);
        PlanAnalysisDTO.Response hidden = svc.get(USER, MATERIAL);
        assertEquals(Boolean.TRUE, hidden.getQualityRedacted());
        assertEquals(PlanAnalysisService.REDACTED_ITEM_TEXT, hidden.getItems().get(0).getText());
        assertNull(hidden.getPlannerAnalysisData());
        assertEquals(List.of(), hidden.getRecommendations());
        assertFalse(M.writeValueAsString(hidden).contains("레거시"), "미검증 AI 문구 0");
        assertEquals(1, hidden.getProgress().getTotalCount(), "진행률(사용자 기록)은 유지");
        svc.analyze(USER, MATERIAL);
        PlanAnalysisDTO.Response shown = svc.get(USER, MATERIAL);
        assertEquals("APPROVED", shown.getQualityStatus());
        assertTrue(shown.getSummary().startsWith("초안 1"));
        assertNull(shown.getQualityRedacted());
    }

    @GateEvidence({"PATCH /api/plan-analysis/items/{itemId}"})
    @Test
    void patchKeepsUserStateButRedactsUnverifiedAiText() throws Exception {
        PlanAnalysisItem legacy = legacyAiAnalysis(null);
        PlanAnalysisService svc = service(true);
        PlanAnalysisDTO.Response r = svc.updateItem(USER, legacy.getId(), true, null);
        assertTrue(legacy.isCompleted(), "완료 체크(사용자 기록)는 저장된다");
        assertTrue(r.getItems().get(0).isCompleted());
        assertEquals(Boolean.TRUE, r.getQualityRedacted());
        assertFalse(M.writeValueAsString(r).contains("레거시"));
        svc.analyze(USER, MATERIAL);
        PlanAnalysisItem fresh = items.get(0);
        PlanAnalysisDTO.Response approved = svc.updateItem(USER, fresh.getId(), true, null);
        assertEquals("APPROVED", approved.getQualityStatus());
        assertTrue(approved.getItems().get(0).getText().startsWith("초안 1 체크"));
    }

    @GateEvidence({"POST /api/materials/{materialId}/plan-recommendation"})
    @Test
    void recommendationFromUnverifiedAiAnalysisIsWithheld() {
        legacyAiAnalysis(null);
        PlanAnalysisService svc = service(true);
        PlanAnalysisDTO.RecommendationResponse hidden = svc.recommend(USER, MATERIAL);
        assertEquals(List.of(), hidden.getRecommendations());
        assertEquals(Boolean.TRUE, hidden.getQualityRedacted());
        svc.analyze(USER, MATERIAL);
        PlanAnalysisDTO.RecommendationResponse shown = svc.recommend(USER, MATERIAL);
        assertEquals(List.of("초안 1 추천: 풀링 학습"), shown.getRecommendations());
        assertNull(shown.getQualityRedacted());
    }

    @Test
    void deterministicPdfAnalysisIsNotRedacted() {
        PlanAnalysis a = PlanAnalysis.builder().id(ids.incrementAndGet()).userId(USER).materialId(MATERIAL).sourceType("PDF")
                .summary("‘자료’의 PDF/플래너 텍스트에서 학습 항목 1개를 추출했습니다").plannerAnalysisJson(null).build();
        analyses.add(a);
        items.add(PlanAnalysisItem.builder().id(ids.incrementAndGet()).analysisId(a.getId()).orderIndex(0).type("SENTENCE")
                .text("원문 문장").completed(false).hidden(false).deleted(false).build());
        PlanAnalysisDTO.Response r = service(true).get(USER, MATERIAL);
        assertEquals("원문 문장", r.getItems().get(0).getText());
        assertNull(r.getQualityRedacted());
        assertEquals(0, stub.evaluations.size());
    }

    @Test
    void gateOffIsLegacyBehaviour() throws Exception {
        legacyAiAnalysis(null);
        PlanAnalysisService svc = service(false);
        assertEquals("레거시 미검증 피드백", svc.get(USER, MATERIAL).getSummary());
        PlanAnalysisDTO.Response r = svc.analyze(USER, MATERIAL);
        assertNull(r.getQualityStatus());
        assertNull(analyses.get(analyses.size() - 1).getQualityStatus());
        assertEquals(0, stub.evaluations.size(), "게이트 OFF: 평가기 호출 0");
        assertFalse(M.writeValueAsString(r).contains("qualityRedacted"));
    }
}
