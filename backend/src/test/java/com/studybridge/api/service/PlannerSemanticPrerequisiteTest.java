package com.studybridge.api.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.dto.PlannerSemanticDTO.*;
import com.studybridge.api.entity.Planner;
import com.studybridge.api.entity.PlannerType;
import com.studybridge.api.entity.Roadmap;
import com.studybridge.api.repository.*;
import org.junit.jupiter.api.Test;
import org.springframework.web.reactive.function.client.WebClient;

import java.util.*;
import java.util.stream.Collectors;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.*;

/**
 * ROADMAP_AUTO 플래너 AI 계획 분석: 문장형/예제형 조각이 선행 개념·목표·플로우로 새지 않고,
 * prerequisites / tasks / flow 가 독립이며 flow 합계가 goalTime 과 정확히 일치하는지.
 */
class PlannerSemanticPrerequisiteTest {

    private static final String FRAG_REG = "관측된데이터를통해독립변수와종속변수사이의관계를추정하는것";
    private static final String FRAG_CLU = "데이터를서로유사한특성을가진그룹으로묶는것";
    private static final String FRAG_CLS = "이산적인라벨값에따라데이터를분류하는것";

    private final ObjectMapper json = new ObjectMapper();
    private final PlannerTimeAllocator allocator = new PlannerTimeAllocator();

    private String roadmapJson() {
        // 1주차: 개념형 core_concepts(선행 개념 후보) / 2주차 2일: 예제 문장이 개념 자리에 들어간 day(오늘)
        return """
        {"weeks":[
          {"week":1,"days":[
            {"day_index":1,"title":"1일차 선형회귀란?","objective":"선형회귀의 • 넘파이을(를) 동작 원리 분석 중심으로 학습한다.",
             "core_concepts":["넘파이","선형회귀모델"],
             "tasks":[{"title":"넘파이 동작 원리 분석","description":"입력·처리·출력 흐름으로 분석한다","estimated_minutes":40}]},
            {"day_index":2,"title":"2일차 다중회귀","objective":"다중회귀분석을 이해한다.",
             "core_concepts":["다중회귀분석","주택면적은독립변수이고"],
             "tasks":[{"title":"다중회귀분석 코드 흐름 추적","description":"호출 순서를 메모한다","estimated_minutes":40}]}
          ]},
          {"week":2,"days":[
            {"day_index":1,"title":"1일차 정규화","objective":"정규화를 학습한다.","core_concepts":["정규화"],
             "tasks":[{"title":"정규화 개념 정리","estimated_minutes":30}]},
            {"day_index":2,"title":"2일차 고급 회귀 기법",
             "objective":"선형회귀의 • %1$s을(를) 코드 흐름 추적 중심으로 학습한다. (주차 흐름: 복습과 시험 대비)",
             "core_concepts":["%1$s","%2$s","%3$s"],
             "tasks":[
               {"title":"%1$s 코드 흐름 추적","description":"선형회귀의 • %1$s 관련 코드 흐름을 따라가며 호출 순서와 데이터 변화를 메모한다","estimated_minutes":40},
               {"title":"%2$s 구조 비교","description":"%2$s을(를) 대체 가능한 방식과 비교해 장단점과 선택 기준을 표로 정리한다","estimated_minutes":35},
               {"title":"%3$s 오류 원인 추론","description":"%3$s 사용 시 발생하기 쉬운 오류 상황 1가지를 정하고 원인과 해결 가설을 적는다","estimated_minutes":40}],
             "review_questions":["%1$s의 핵심 구성 요소는 무엇인가?"],
             "checkpoint":"%1$s의 핵심을 본인 말로 설명할 수 있다",
             "deliverable":"%1$s 정리 노트 또는 • %2$s 비교 표"}
          ]}
        ]}
        """.formatted(FRAG_REG, FRAG_CLU, FRAG_CLS);
    }

    private Planner planner() {
        return Planner.builder().id(10L).userId(1L).title("[로드맵 2주차 2일] 고급 회귀 기법").subject("선형회귀")
                .plannerType(PlannerType.ROADMAP).sourceType("ROADMAP_AUTO").sourceRoadmapId(20L).sourceMaterialId(30L)
                .materialId(40L).roadmapWeek(2).roadmapDay(2).goalTime("115분")
                .content("[오늘 목표] 선형회귀의 • " + FRAG_REG + "을(를) 코드 흐름 추적 중심으로 학습한다.\n\n[할 일]\n1. " + FRAG_REG + " 코드 흐름 추적: ...\n2. " + FRAG_CLU + " 구조 비교: ...")
                .tmi("핵심 개념: " + FRAG_REG + ", " + FRAG_CLU + ", " + FRAG_CLS)
                .build();
    }

    private PlannerAnalysisContext context(Planner p) {
        PlannerRepository planners = mock(PlannerRepository.class);
        RoadmapRepository roadmaps = mock(RoadmapRepository.class);
        RoadmapTaskRepository roadmapTasks = mock(RoadmapTaskRepository.class);
        PlanAnalysisRepository analyses = mock(PlanAnalysisRepository.class);
        PlanAnalysisItemRepository items = mock(PlanAnalysisItemRepository.class);
        when(planners.findById(10L)).thenReturn(Optional.of(p));
        when(planners.save(any())).thenAnswer(inv -> inv.getArgument(0));
        when(roadmaps.findById(20L)).thenReturn(Optional.of(Roadmap.builder().roadmapId(20L).userId(1L).roadmapJson(roadmapJson()).build()));
        when(analyses.findTopByUserIdAndMaterialIdOrderByIdDesc(anyLong(), anyLong())).thenReturn(Optional.empty());
        return new PlannerAnalysisContext(planners, roadmaps, roadmapTasks, analyses, items, json, allocator);
    }

    private PlannerSemanticAnalyzer analyzerWithAiDown(PlannerAnalysisContext ctx) {
        WebClient client = mock(WebClient.class);
        when(client.post()).thenThrow(new IllegalStateException("ai07 unreachable"));
        PlannerRepository planners = mock(PlannerRepository.class);
        when(planners.save(any())).thenAnswer(inv -> inv.getArgument(0));
        return new PlannerSemanticAnalyzer(ctx, allocator, planners, client, json);
    }

    @Test void contextUsesExactDayAndReplacesSentenceFragmentsWithTopic() {
        Planner p = planner();
        Request req = context(p).build(p);

        assertEquals("ROADMAP", req.getSourceType());
        assertEquals("고급 회귀 기법", req.getTopic());
        assertEquals("선형회귀", req.getSubject());
        assertEquals(115, req.getTargetMinutes());
        // 오늘 day 의 task 만(3개), 다른 날짜 task 는 섞이지 않는다
        assertEquals(3, req.getDetailTasks().size());
        assertEquals(List.of("고급 회귀 기법 코드 흐름 추적", "고급 회귀 기법 구조 비교", "고급 회귀 기법 오류 원인 추론"),
                req.getDetailTasks().stream().map(InputItem::getTitle).toList());
        for (InputItem t : req.getDetailTasks()) {
            assertFalse(t.getTitle().contains(FRAG_REG) || t.getTitle().contains(FRAG_CLU) || t.getTitle().contains(FRAG_CLS), t.getTitle());
            assertFalse(t.getDescription().contains("추정하는것") || t.getDescription().contains("묶는것") || t.getDescription().contains("분류하는것"), t.getDescription());
        }
        assertEquals("선형회귀의 고급 회귀 기법을(를) 코드 흐름 추적 중심으로 학습한다. (주차 흐름: 복습과 시험 대비)", req.getLearningGoal());
        // 문장형 core_concepts 는 개념으로 전달하지 않고 excludedFragments 로만 남긴다(AI07 payload 에서 제외)
        assertTrue(req.getCoreConcepts().isEmpty());
        assertEquals(3, req.getExcludedFragments().size());
        assertFalse(json.valueToTree(req).has("excludedFragments"));
        // 앞선 날의 개념형 개념만 선행 개념 후보(문장형 "주택면적은독립변수이고"는 제외)
        assertEquals(List.of("넘파이", "선형회귀모델", "다중회귀분석", "정규화"), req.getPriorConcepts());
        // content/tmi 는 보조 컨텍스트로 치환 전달
        assertFalse(req.getMemo().contains(FRAG_REG));
        assertFalse(req.getContent().contains(FRAG_CLU));
        assertTrue(req.getReviewQuestions().get(0).startsWith("고급 회귀 기법의"));
    }

    @Test void fallbackAnalysisKeepsPrerequisitesTasksFlowIndependentAndSumsToGoalTime() {
        Planner p = planner();
        PlannerAnalysisContext ctx = context(p);
        AnalysisResponse resp = analyzerWithAiDown(ctx).analyze(1L, 10L);

        assertEquals("FALLBACK", resp.getAiSource());
        // C. flow 합계 = goalTime(115) 정확히, targetMinutes 그대로
        assertEquals(115, resp.getTargetMinutes());
        assertEquals(115, resp.getTotalRecommendedMinutes());
        assertEquals(115, resp.getFlow().stream().mapToInt(FlowNode::getRecommendedMinutes).sum());
        assertEquals(115, resp.getTasks().stream().mapToInt(Task::getRecommendedMinutes).sum());

        // A. prerequisites 는 예제 문장/입력 task 를 복사하지 않는다
        Set<String> taskTitles = resp.getTasks().stream().map(Task::getTitle).collect(Collectors.toSet());
        Set<String> flowTitles = resp.getFlow().stream().map(FlowNode::getTitle).collect(Collectors.toSet());
        for (Prerequisite pre : resp.getPrerequisites()) {
            assertFalse(pre.getName().contains("하는것") || pre.getName().contains("묶는것") || pre.getName().contains("이다"), pre.getName());
            assertFalse(taskTitles.contains(pre.getName()), pre.getName());
            assertFalse(flowTitles.contains(pre.getName()), pre.getName());
            assertFalse(pre.isIncludedInPlanTime());                     // D. 선행 개념 시간은 115분에 불포함
            assertTrue(pre.getReason().contains("권장"), pre.getReason());  // 모른다고 단정하지 않는 표현
        }
        // 폴백 선행 개념은 앞서 다룬 개념 중 주제(회귀)와 연관된 것만
        assertEquals(List.of("선형회귀모델", "다중회귀분석"), resp.getPrerequisites().stream().map(Prerequisite::getName).toList());

        // B. flow 는 학습 활동 순서(tasks)이며 선행 개념 목록과 다르다
        assertEquals(resp.getTasks().stream().map(Task::getId).toList(), resp.getFlow().stream().map(FlowNode::getTaskId).toList());
        assertEquals(List.of("고급 회귀 기법 코드 흐름 추적", "고급 회귀 기법 구조 비교", "고급 회귀 기법 오류 원인 추론"),
                resp.getFlow().stream().map(FlowNode::getTitle).toList());
        assertTrue(Collections.disjoint(flowTitles, resp.getPrerequisites().stream().map(Prerequisite::getName).toList()));

        // 목표 정합성/요약에도 예제 문장이 남지 않는다
        assertFalse(resp.getGoalAlignment().getSummary().contains("추정하는것"));
        assertFalse(resp.getSummary().contains("추정하는것"));
        // 목표 원문("…학습한다. (주차 흐름: …)")을 결합하지 않은 완결 문장이어야 한다(조사 보정 표기·메타 괄호·말줄임 없음)
        for (String s : List.of(resp.getGoalAlignment().getSummary(), resp.getSummary(), resp.getTasks().get(0).getGoalAlignment().getReason())) {
            assertFalse(s.contains("(를)") || s.contains("(을)") || s.contains("주차 흐름") || s.contains("…") || s.contains("학습한다."), s);
            assertTrue(s.endsWith("다."), s);
        }
        assertEquals("현재 학습 활동은 고급 회귀 기법의 개념 이해, 코드 흐름 추적, 실습을 중심으로 구성되어 있어 학습 목표와 대체로 잘 연결되어 있습니다.",
                resp.getGoalAlignment().getSummary());
        assertFalse(resp.getLearningGoal().contains("(를)") || resp.getLearningGoal().contains("주차 흐름"), resp.getLearningGoal());
        assertTrue(resp.getWarnings().stream().anyMatch(w -> w.contains("문장형 항목 3개")));

        // E. Material → Planner 연결(materialId/sourceMaterialId/sourceRoadmapId)은 분석이 건드리지 않는다
        assertEquals(40L, p.getMaterialId());
        assertEquals(30L, p.getSourceMaterialId());
        assertEquals(20L, p.getSourceRoadmapId());
        assertNotNull(p.getPlanAnalysisJson());
    }

    @Test void aiPrerequisitesAreValidatedNotTrusted() {
        Planner p = planner();
        PlannerAnalysisContext ctx = context(p);
        Request req = ctx.build(p);
        PlannerSemanticAnalyzer analyzer = analyzerWithAiDown(ctx);

        List<Prerequisite> candidates = List.of(
                new Prerequisite("독립변수와 종속변수", "회귀 모델의 입력/출력 구분에 필요합니다.", true),
                new Prerequisite("기본 선형회귀", null, false),
                new Prerequisite("손실함수 / 평균제곱오차(MSE)", "", false),
                new Prerequisite(FRAG_REG, "x", false),                                   // 예제 문장
                new Prerequisite("고급 회귀 기법 코드 흐름 추적", "x", false),               // task 제목 복사
                new Prerequisite("선형회귀의 고급 회귀 기법을(를) 코드 흐름 추적 중심으로 학습한다. (주차 흐름: 복습과 시험 대비)", "x", false), // 목표 복사
                new Prerequisite("주택면적은 독립변수이고 거래가격은 종속변수이다", "x", false),  // 서술문
                new Prerequisite("기본 선형회귀", "dup", false));
        List<Prerequisite> out = analyzer.validatePrerequisites(candidates, req);
        assertEquals(List.of("독립변수와 종속변수", "기본 선형회귀", "손실함수 / 평균제곱오차(MSE)"),
                out.stream().map(Prerequisite::getName).toList());
        out.forEach(pre -> { assertFalse(pre.isIncludedInPlanTime()); assertFalse(pre.getReason().isBlank()); });
    }

    @Test void manualPlannerIsUnaffected() {
        Planner p = Planner.builder().id(11L).userId(1L).title("자료구조 복습").plannerType(PlannerType.USER).goalTime("60분")
                .content("[오늘 목표] 스택과 큐 복습\n\n[할 일]\n1. 스택 구현\n2. 큐 구현").build();
        PlannerRepository planners = mock(PlannerRepository.class);
        when(planners.findById(11L)).thenReturn(Optional.of(p));
        PlanAnalysisRepository analyses = mock(PlanAnalysisRepository.class);
        PlannerAnalysisContext ctx = new PlannerAnalysisContext(planners, mock(RoadmapRepository.class), mock(RoadmapTaskRepository.class),
                analyses, mock(PlanAnalysisItemRepository.class), json, allocator);
        Request req = ctx.build(p);
        assertEquals("MANUAL", req.getSourceType());
        assertEquals("자료구조 복습", req.getTopic());
        assertEquals(List.of("스택 구현", "큐 구현"), req.getDetailTasks().stream().map(InputItem::getTitle).toList());
        assertEquals("스택과 큐 복습", req.getLearningGoal());
        assertTrue(req.getExcludedFragments().isEmpty());
        AnalysisResponse resp = analyzerWithAiDown(ctx).analyze(1L, 11L);
        assertEquals(60, resp.getFlow().stream().mapToInt(FlowNode::getRecommendedMinutes).sum());
        assertTrue(resp.getPrerequisites().isEmpty());   // 추측하지 않는다(정상 empty)
    }
}
