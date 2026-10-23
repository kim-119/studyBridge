package com.studybridge.api.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.dto.PlannerDTO;
import com.studybridge.api.entity.Planner;
import com.studybridge.api.entity.PlannerType;
import com.studybridge.api.repository.FolderRepository;
import com.studybridge.api.repository.MaterialRepository;
import com.studybridge.api.repository.PlannerRepository;
import com.studybridge.api.util.LearningConceptValidator;
import com.studybridge.api.util.LearningDayNormalizer;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

/**
 * 로드맵 → 플래너 content/tmi upstream 생성 + 기존 저장본 backfill: 사용자에게 저장되는 최종 문자열에
 * 템플릿 조립 흔적("을(를)", "• ", 설명문 조각, 메타 괄호)이 남지 않고 완결 문장만 남아야 한다.
 */
class PlannerRoadmapContentTest {

    private static final String FRAG_REG = "관측된데이터를통해독립변수와종속변수사이의관계를추정하는것";
    private static final String FRAG_CLU = "데이터를서로유사한특성을가진그룹으로묶는것";
    private static final String FRAG_CLS = "이산적인라벨값에따라데이터를분류하는것";

    private PlannerRepository planners = mock(PlannerRepository.class);
    private final PlannerService service = new PlannerService(planners, mock(MaterialRepository.class), mock(S3Service.class), new ObjectMapper(), mock(FolderRepository.class));

    private static void assertClean(String s) {
        for (String bad : List.of("을(를)", "이(가)", "은(는)", "과(와)", "•", "(주차 흐름", "…"))
            assertFalse(s.contains(bad), "'" + bad + "' in: " + s);
        for (String f : List.of(FRAG_REG, FRAG_CLU, FRAG_CLS)) assertFalse(LearningConceptValidator.containsFragment(s, f), s);
        for (String line : s.split("\\R")) assertFalse(line.matches(".*[가-힣]{18,}.*"), line);
    }

    @Test void createFromRoadmapStoresNormalizedContentAndTmi() {
        when(planners.countByUserIdAndSourceMaterialIdAndSourceType(any(), any(), any())).thenReturn(0L);
        when(planners.save(any())).thenAnswer(inv -> inv.getArgument(0));
        PlannerDTO.RoadmapItem item = new PlannerDTO.RoadmapItem();
        item.setWeek(11); item.setDayIndex(2); item.setTitle("2일차 고급 회귀 기법");
        item.setObjective("선형회귀의 • " + FRAG_REG + "을(를) 코드 흐름 추적 중심으로 학습한다. (주차 흐름: 복습과 시험 대비)");
        item.setTasks(List.of(FRAG_REG + " 코드 흐름 추적: 선형회귀의 • " + FRAG_REG + " 관련 코드 흐름을 따라가며 호출 순서와 데이터 변화를 메모한다",
                FRAG_CLU + " 구조 비교: " + FRAG_CLU + "을(를) 대체 가능한 방식과 비교해 장단점과 선택 기준을 표로 정리한다",
                FRAG_CLS + " 오류 원인 추론: " + FRAG_CLS + " 사용 시 발생하기 쉬운 오류 상황 1가지를 정하고 원인과 해결 가설을 적는다"));
        item.setCoreConcepts(List.of(FRAG_REG, FRAG_CLU, FRAG_CLS));
        item.setReviewQuestions(List.of(FRAG_REG + "의 핵심 구성 요소는 무엇인가?", "선형회귀에서 • " + FRAG_CLU + "을(를) 사용하는 이유는 무엇인가?"));
        item.setCheckpoint(FRAG_REG + "의 핵심을 본인 말로 설명할 수 있다");
        item.setDeliverable(FRAG_REG + " 정리 노트 또는 • " + FRAG_CLU + " 비교 표");
        item.setTargetMinutes(115);
        PlannerDTO.FromRoadmapRequest req = new PlannerDTO.FromRoadmapRequest();
        req.setMaterialId(40L); req.setRoadmapId(20L); req.setSubject("선형회귀"); req.setItems(List.of(item));

        PlannerDTO.FromRoadmapResponse res = service.createFromRoadmap(1L, req);
        assertEquals(1, res.getCreatedCount());
        ArgumentCaptor<Planner> cap = ArgumentCaptor.forClass(Planner.class);
        verify(planners).save(cap.capture());
        Planner p = cap.getValue();

        assertEquals("[로드맵 11주차 2일] 고급 회귀 기법", p.getTitle());
        assertClean(p.getContent());
        assertClean(p.getTmi());
        assertEquals("""
                [오늘 목표] 선형회귀의 고급 회귀 기법을 코드 흐름 추적 중심으로 학습한다. 이번 주는 복습과 시험 대비 단계이다.

                [할 일]
                1. 고급 회귀 기법 코드 흐름 추적: 선형회귀의 고급 회귀 기법 관련 코드 흐름을 따라가며 호출 순서와 데이터 변화를 메모한다.
                2. 고급 회귀 기법 구조 비교: 고급 회귀 기법을 대체 가능한 방식과 비교해 장단점과 선택 기준을 표로 정리한다.
                3. 고급 회귀 기법 오류 원인 추론: 고급 회귀 기법 사용 시 발생하기 쉬운 오류 상황 1가지를 정하고 원인과 해결 가설을 적는다.""",
                p.getContent());
        assertEquals("""
                핵심 개념: 고급 회귀 기법, 선형회귀
                복습 질문:
                - 고급 회귀 기법의 핵심 구성 요소는 무엇인가?
                - 선형회귀에서 고급 회귀 기법을 사용하는 이유는 무엇인가?
                체크포인트: 고급 회귀 기법의 핵심을 본인 말로 설명할 수 있다.
                산출물: 고급 회귀 기법 정리 노트 또는 고급 회귀 기법 비교 표""", p.getTmi());
        // 파싱 → 정규화 왕복이 안정적이다(backfill 재실행 시 변경 없음)
        LearningDayNormalizer.DayContent again = PlannerDayContent.normalizeStored(p);
        assertEquals(p.getContent(), PlannerDayContent.composeContent(again));
        assertEquals(p.getTmi(), PlannerDayContent.composeTmi(again));
    }

    @Test void backfillRewritesLegacyRowsOnceAndSkipsCleanOnes() {
        Planner legacy = Planner.builder().id(2302L).userId(1L).plannerType(PlannerType.ROADMAP).sourceType("ROADMAP_AUTO")
                .title("[로드맵 12주차 6일] 시험 준비 마무리").subject("선형회귀")
                .content("[오늘 목표] 선형회귀의 • 주택면적은독립변수이고을(를) 실제 프로젝트 적용 중심으로 학습한다. (주차 흐름: 최종 정리 및 회고)\n\n"
                        + "[할 일]\n1. 주택면적은독립변수이고 구조 비교: 주택면적은독립변수이고을(를) 대체 가능한 방식과 비교해 장단점과 선택 기준을 표로 정리한다\n"
                        + "2. 거래가격은종속변수이다 오류 원인 추론: 거래가격은종속변수이다 사용 시 발생하기 쉬운 오류 상황 1가지를 정하고 원인과 해결 가설을 적는다")
                .tmi("핵심 개념: 주택면적은독립변수이고, 거래가격은종속변수이다, 두변수모두다른변수에영향을받지않는독립변수이다\n복습 질문:\n"
                        + "- 선형회귀에서 • 주택면적은독립변수이고을(를) 사용하는 이유는 무엇인가?\n- 거래가격은종속변수이다과(와) 비슷하지만 다른 개념은 무엇이고 어떻게 구분하는가?\n"
                        + "체크포인트: 주택면적은독립변수이고의 핵심을 본인 말로 설명할 수 있다\n산출물: 주택면적은독립변수이고 정리 노트 또는 거래가격은종속변수이다 비교 표\n메모: 오후에 복습")
                .build();
        Planner manual = Planner.builder().id(3L).userId(1L).plannerType(PlannerType.USER).sourceType("ROADMAP_AUTO")
                .title("자유 메모").content("오늘은 스택과 큐를 복습한다.").tmi("퇴근 후 1시간").build();
        when(planners.findBySourceType("ROADMAP_AUTO")).thenReturn(new ArrayList<>(List.of(legacy, manual)));
        when(planners.save(any())).thenAnswer(inv -> inv.getArgument(0));

        assertEquals(1, service.normalizeRoadmapPlannerContent());
        assertClean(legacy.getContent());
        assertClean(legacy.getTmi());
        assertTrue(legacy.getContent().startsWith("[오늘 목표] 선형회귀의 시험 준비 마무리를 실제 프로젝트 적용 중심으로 학습한다. 이번 주는 최종 정리 및 회고 단계이다."), legacy.getContent());
        assertTrue(legacy.getTmi().startsWith("핵심 개념: 시험 준비 마무리, 선형회귀\n복습 질문:\n- 선형회귀에서 시험 준비 마무리를 사용하는 이유는 무엇인가?"), legacy.getTmi());
        assertTrue(legacy.getTmi().endsWith("메모: 오후에 복습"), legacy.getTmi());   // 태그 밖 메모는 보존
        assertEquals("오늘은 스택과 큐를 복습한다.", manual.getContent());               // 자유 입력은 손대지 않는다
        // 두 번째 실행은 변경 0건(idempotent)
        assertEquals(0, service.normalizeRoadmapPlannerContent());
    }
}
