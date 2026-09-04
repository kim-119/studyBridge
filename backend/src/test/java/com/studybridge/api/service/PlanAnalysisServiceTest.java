package com.studybridge.api.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.dto.PlanAnalysisDTO;
import com.studybridge.api.entity.ExtractionStatus;
import com.studybridge.api.entity.Material;
import com.studybridge.api.entity.MaterialType;
import com.studybridge.api.entity.PlanAnalysis;
import com.studybridge.api.entity.PlanAnalysisItem;
import com.studybridge.api.entity.Planner;
import com.studybridge.api.repository.MaterialRepository;
import com.studybridge.api.repository.PlanAnalysisItemRepository;
import com.studybridge.api.repository.PlanAnalysisRepository;
import com.studybridge.api.repository.PlannerRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.client.reactive.ClientHttpRequest;
import org.springframework.http.codec.HttpMessageWriter;
import org.springframework.mock.http.client.reactive.MockClientHttpRequest;
import org.springframework.web.reactive.function.BodyInserter;
import org.springframework.web.reactive.function.client.ClientResponse;
import org.springframework.web.reactive.function.client.ExchangeStrategies;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicLong;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.*;

class PlanAnalysisServiceTest {

    private static final long USER_ID = 13L;

    private final ObjectMapper objectMapper = new ObjectMapper();

    private PlanAnalysisRepository analysisRepository;
    private PlanAnalysisItemRepository itemRepository;
    private PlannerRepository plannerRepository;
    private MaterialRepository materialRepository;
    private PlanTextAnalyzer analyzer;

    @BeforeEach
    void setUp() {
        analysisRepository = mock(PlanAnalysisRepository.class);
        itemRepository = mock(PlanAnalysisItemRepository.class);
        plannerRepository = mock(PlannerRepository.class);
        materialRepository = mock(MaterialRepository.class);
        analyzer = mock(PlanTextAnalyzer.class);

        when(analysisRepository.findTopByUserIdAndMaterialIdOrderByIdDesc(any(), any())).thenReturn(Optional.empty());
        when(analysisRepository.save(any(PlanAnalysis.class))).thenAnswer(invocation -> {
            PlanAnalysis entity = invocation.getArgument(0);
            if (entity.getId() == null) entity.setId(101L);
            return entity;
        });
        AtomicLong itemSeq = new AtomicLong(1000L);
        when(itemRepository.save(any(PlanAnalysisItem.class))).thenAnswer(invocation -> {
            PlanAnalysisItem entity = invocation.getArgument(0);
            if (entity.getId() == null) entity.setId(itemSeq.incrementAndGet());
            return entity;
        });
    }

    @Test
    void analyzePlanner_shouldUsePlannerDbDataAndMatchFastApiSchema() throws Exception {
        AtomicReference<String> capturedBody = new AtomicReference<>();
        PlanAnalysisService service = newService(plannerAnalyzeClient("""
                {
                  "success": true,
                  "title": "자료구조 학습 플래너",
                  "keywords": ["자료구조", "트리"],
                  "learningGoal": "트리 개념을 이해하고 문제 풀이까지 진행한다.",
                  "schedule": ["개념 정리", "예제 풀이", "복습"],
                  "checklist": ["트리 정의 정리", "순회 문제 풀기"],
                  "progress": 0,
                  "scheduleAnalysis": ["개념 학습과 문제 풀이 순서는 적절합니다."],
                  "problemPoints": ["복습 시간이 별도로 보이지 않습니다."],
                  "balanceAssessment": "학습량은 적절하지만 복습 시간 확보가 필요합니다.",
                  "improvementActions": ["복습 20분 추가", "문제 풀이 후 오답 정리"],
                  "aiFeedback": "계획은 명확하지만 복습 블록을 분리하면 더 좋습니다.",
                  "nextRecommendations": ["오답 정리", "복습 시간 확보"],
                  "unfinishedItems": ["순회 문제 풀기"],
                  "message": "저장된 플래너 자료를 기반으로 분석했습니다."
                }
                """, capturedBody));

        Material material = Material.builder()
                .materialId(304L)
                .userId(USER_ID)
                .title("자료구조 플래너")
                .materialType(MaterialType.PLANNER)
                .plannerId(77L)
                .extractionStatus(ExtractionStatus.SUCCESS)
                .build();
        Planner planner = Planner.builder()
                .id(77L)
                .userId(USER_ID)
                .title("자료구조 3일차")
                .subject("자료구조")
                .content("트리 개념 정리\n순회 문제 풀이")
                .tmi("AVL 트리 복습")
                .goalTime("3시간")
                .netStudyTime("1시간")
                .dDay("5")
                .studyType("시험 준비")
                .priority("높음")
                .term("3주차")
                .timeTableJson("{\"9\":[true,{\"content\":\"트리 예제 풀이\",\"checked\":true}]}")
                .build();
        when(materialRepository.findById(304L)).thenReturn(Optional.of(material));
        when(plannerRepository.findById(77L)).thenReturn(Optional.of(planner));

        PlanAnalysisDTO.Response response = service.analyze(USER_ID, 304L);

        assertEquals("PLANNER", response.getSourceType());
        assertNotNull(response.getPlannerAnalysisData());
        assertEquals(List.of("개념 학습과 문제 풀이 순서는 적절합니다."), response.getPlannerAnalysisData().getScheduleAnalysis());
        assertEquals(List.of("복습 시간이 별도로 보이지 않습니다."), response.getPlannerAnalysisData().getProblemPoints());
        assertEquals("학습량은 적절하지만 복습 시간 확보가 필요합니다.", response.getPlannerAnalysisData().getBalanceAssessment());
        assertEquals(List.of("복습 20분 추가", "문제 풀이 후 오답 정리"), response.getPlannerAnalysisData().getImprovementActions());
        assertEquals(200, response.getMeta().getFastApiResponseStatus());

        JsonNode body = objectMapper.readTree(capturedBody.get());
        assertEquals(77L, body.get("plannerId").asLong());
        assertEquals("자료구조 3일차", body.get("title").asText());
        assertTrue(body.has("content"));
        assertTrue(body.has("todo"));
        assertTrue(body.has("checklist"));
        assertTrue(body.has("completedTasks"));
        assertTrue(body.has("incompleteTasks"));
        assertFalse(body.has("planner"));
    }

    @Test
    void analyzePlanner_shouldFallbackToMaterialSnapshotWhenPlannerRowMissing() {
        AtomicReference<String> capturedBody = new AtomicReference<>();
        PlanAnalysisService service = newService(plannerAnalyzeClient("""
                {"success": true, "title": "학습 플래너", "schedule": ["핵심 주제 학습"], "checklist": ["핵심 개념 복습"], "progress": 0}
                """, capturedBody));

        Material material = Material.builder()
                .materialId(304L)
                .userId(USER_ID)
                .title("운영체제 플래너")
                .materialType(MaterialType.PLANNER)
                .plannerId(999L)
                .contentJson("{\"plannerId\":999,\"title\":\"운영체제 1일차\",\"subject\":\"운영체제\",\"content\":\"프로세스 상태 정리\",\"tmi\":\"문맥 교환 복습\",\"goalTime\":\"2시간\",\"timeTableJson\":\"{\\\"10\\\":[true]}\"}")
                .extractionStatus(ExtractionStatus.SUCCESS)
                .build();
        when(materialRepository.findById(304L)).thenReturn(Optional.of(material));
        when(plannerRepository.findById(999L)).thenReturn(Optional.empty());
        when(plannerRepository.findByUserIdAndMaterialId(USER_ID, 304L)).thenReturn(Collections.emptyList());
        when(plannerRepository.findByUserIdAndSourceMaterialId(USER_ID, 304L)).thenReturn(Collections.emptyList());

        PlanAnalysisDTO.Response response = service.analyze(USER_ID, 304L);

        assertEquals("PLANNER", response.getSourceType());
        assertEquals(1, response.getMeta().getTaskCount());
        assertEquals(1, response.getMeta().getScheduleCount());
        assertNotNull(capturedBody.get());
        assertTrue(capturedBody.get().contains("운영체제 1일차"));
    }

    @Test
    void analyzePlanner_shouldThrowEmptyWhenNoScheduleAndNoTasks() {
        PlanAnalysisService service = newService(plannerAnalyzeClient("{}", new AtomicReference<>()));

        Material material = Material.builder()
                .materialId(304L)
                .userId(USER_ID)
                .title("빈 플래너")
                .materialType(MaterialType.PLANNER)
                .plannerId(77L)
                .extractionStatus(ExtractionStatus.SUCCESS)
                .build();
        Planner planner = Planner.builder().id(77L).userId(USER_ID).title("빈 플래너").build();
        when(materialRepository.findById(304L)).thenReturn(Optional.of(material));
        when(plannerRepository.findById(77L)).thenReturn(Optional.of(planner));

        PlanAnalysisException error = assertThrows(PlanAnalysisException.class, () -> service.analyze(USER_ID, 304L));
        assertEquals("PLAN_ANALYSIS_EMPTY", error.getErrorCode());
    }

    @Test
    void analyzePdf_shouldKeepExistingPdfPath() {
        PlanAnalysisService service = newService(plannerAnalyzeClient("{}", new AtomicReference<>()));

        Material material = Material.builder()
                .materialId(401L)
                .userId(USER_ID)
                .title("알고리즘 PDF")
                .materialType(MaterialType.PDF)
                .extractedText("이진 탐색 트리 구현을 설계하고 테스트 케이스를 작성한다.")
                .extractionStatus(ExtractionStatus.SUCCESS)
                .build();
        when(materialRepository.findById(401L)).thenReturn(Optional.of(material));
        when(plannerRepository.findByUserIdAndMaterialId(USER_ID, 401L)).thenReturn(Collections.emptyList());
        when(plannerRepository.findByUserIdAndSourceMaterialId(USER_ID, 401L)).thenReturn(Collections.emptyList());
        when(analyzer.extract(any())).thenReturn(new PlanTextAnalyzer.Result(
                List.of(new PlanTextAnalyzer.ExtractedItem("ACTION", "테스트 케이스를 작성한다.", "이진 탐색 트리 구현을 설계하고 테스트 케이스를 작성한다.", "PDF", null, 0)),
                1,
                1
        ));

        PlanAnalysisDTO.Response response = service.analyze(USER_ID, 401L);

        assertEquals("PDF", response.getSourceType());
        assertEquals(1, response.getItems().size());
        assertEquals("PDF", response.getItems().get(0).getSourceType());
    }

    private PlanAnalysisService newService(WebClient webClient) {
        return new PlanAnalysisService(
                analysisRepository,
                itemRepository,
                plannerRepository,
                materialRepository,
                analyzer,
                webClient,
                objectMapper
        );
    }

    private WebClient plannerAnalyzeClient(String responseJson, AtomicReference<String> capturedBody) {
        ExchangeStrategies strategies = ExchangeStrategies.withDefaults();
        return WebClient.builder().exchangeFunction(request -> {
            MockClientHttpRequest mockRequest = new MockClientHttpRequest(request.method(), request.url());
            BodyInserter.Context context = new BodyInserter.Context() {
                @Override
                public List<HttpMessageWriter<?>> messageWriters() {
                    return strategies.messageWriters();
                }

                @Override
                public java.util.Optional<org.springframework.http.server.reactive.ServerHttpRequest> serverRequest() {
                    return java.util.Optional.empty();
                }

                @Override
                public Map<String, Object> hints() {
                    return Collections.emptyMap();
                }
            };

            BodyInserter<?, ? super ClientHttpRequest> inserter = request.body();
            return inserter.insert(mockRequest, context)
                    .then(Mono.fromCallable(() -> {
                        capturedBody.set(mockRequest.getBodyAsString().block());
                        return ClientResponse.create(HttpStatus.OK)
                                .header("Content-Type", MediaType.APPLICATION_JSON_VALUE)
                                .body(responseJson)
                                .build();
                    }));
        }).build();
    }
}
