package com.studybridge.api.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.ai.AiFailoverExecutor;
import com.studybridge.api.ai.AiUpstream;
import com.studybridge.api.ai.AiUpstreams;
import com.studybridge.api.ai.quality.AiQualityGateSettings;
import com.studybridge.api.ai.quality.AiResponseQualityGate;
import com.studybridge.api.ai.quality.QualityEvaluatorClient;
import com.studybridge.api.dto.SummaryDTO;
import com.studybridge.api.entity.Material;
import com.studybridge.api.entity.MaterialSummary;
import com.studybridge.api.repository.MaterialMemoRepository;
import com.studybridge.api.repository.MaterialQuestionRepository;
import com.studybridge.api.repository.MaterialQuizRepository;
import com.studybridge.api.repository.MaterialRepository;
import com.studybridge.api.repository.MaterialSummaryRepository;
import com.studybridge.api.repository.RoadmapRepository;
import com.studybridge.api.repository.RoadmapTaskRepository;
import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.function.IntFunction;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.web.reactive.function.client.WebClient;

/**
 * PDF 요약(JSON 경로) 품질 게이트: 79→85 재생성 승인, 전부 거절 시 저장 금지·기존 요약 보존, 미승인 캐시 미노출,
 * 평가기 503/생성 실패 시 재생성 없음, 게이트 OFF 회귀 없음, 평가기에 PDF 원문 근거 전달.
 */
class MaterialSummaryQualityGateTest {

        static final long USER = 55L;
        static final long MATERIAL = 345L;
        static final ObjectMapper M = new ObjectMapper();
        static final String PDF_TEXT = "TCP 연결은 3-way handshake(SYN, SYN-ACK, ACK)로 수립한다. 연결 해제는 4단계다. ";

        HttpServer server;
        final AtomicInteger summaryCalls = new AtomicInteger();
        final List<JsonNode> evaluations = new CopyOnWriteArrayList<>();
        volatile IntFunction<String> evaluatorPolicy; // 평가 순번 → 응답 JSON(null 이면 503)
        volatile boolean summaryFails;
        volatile String gptRaw;
        MaterialSummaryRepository summaries;
        final com.studybridge.api.ai.training.TrainingCandidateCollector collector =
                        org.mockito.Mockito.mock(com.studybridge.api.ai.training.TrainingCandidateCollector.class);

        @BeforeEach
        void up() throws Exception {
                server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
                server.createContext("/api/ai/summary", ex -> {
                        int n = summaryCalls.incrementAndGet();
                        ex.getRequestBody().readAllBytes();
                        String body = summaryFails ? "{\"success\":false,\"errorCode\":\"AI_TIMEOUT\",\"message\":\"m\",\"retryable\":true}"
                                        : "{\"success\":true,\"overview\":\"요약 " + n + ": TCP 는 3-way handshake 로 연결한다.\",\"summary\":\"s" + n
                                                        + "\",\"key_points\":[\"SYN\"],\"sections\":[{\"title\":\"연결\",\"content\":\"SYN, SYN-ACK, ACK\"}]"
                                                        + (gptRaw != null ? ",\"gpt_raw\":\"" + gptRaw + "\"" : "") + "}";
                        byte[] b = body.getBytes(StandardCharsets.UTF_8);
                        ex.getResponseHeaders().add("Content-Type", "application/json");
                        ex.sendResponseHeaders(200, b.length);
                        ex.getResponseBody().write(b);
                        ex.close();
                });
                server.createContext("/api/ai/quality/evaluate", ex -> {
                        JsonNode in = M.readTree(ex.getRequestBody().readAllBytes());
                        evaluations.add(in);
                        String body = evaluatorPolicy.apply(evaluations.size());
                        byte[] b = (body == null ? "{}" : body.replace("RID", in.get("requestId").asText())).getBytes(StandardCharsets.UTF_8);
                        ex.getResponseHeaders().add("Content-Type", "application/json");
                        ex.sendResponseHeaders(body == null ? 503 : 200, b.length);
                        ex.getResponseBody().write(b);
                        ex.close();
                });
                server.start();
        }

        @AfterEach
        void down() {
                server.stop(0);
        }

        static String out(double score, String status) {
                return "{\"schemaVersion\":\"response-quality.v1\",\"requestId\":\"RID\",\"taskType\":\"PDF_SUMMARY\",\"success\":true,\"verified\":"
                                + "APPROVED".equals(status) + ",\"qualityStatus\":\"" + status + "\",\"score\":" + score
                                + ",\"minimumScore\":80,\"hardFail\":false,\"violations\":[],\"dimensions\":[],\"evaluatorVersion\":\"stub\",\"latencyMs\":1}";
        }

        AiIntegrationService service(boolean gateOn, MaterialSummary cached) {
                WebClient wc = WebClient.create("http://127.0.0.1:" + server.getAddress().getPort());
                MaterialRepository materials = mock(MaterialRepository.class);
                Material material = Material.builder().materialId(MATERIAL).userId(USER).title("네트워크").extractedText(PDF_TEXT.repeat(10)).build();
                when(materials.findById(MATERIAL)).thenReturn(Optional.of(material));
                summaries = mock(MaterialSummaryRepository.class);
                when(summaries.findByMaterial_MaterialId(MATERIAL)).thenReturn(Optional.ofNullable(cached));
                when(summaries.save(any(MaterialSummary.class))).thenAnswer(inv -> inv.getArgument(0));
                AiQualityGateSettings s = AiQualityGateSettings.forTest(gateOn);
                AiResponseQualityGate gate = new AiResponseQualityGate(s, new QualityEvaluatorClient(wc, s, "k".repeat(64)));
                AiUpstreams ups = new AiUpstreams(List.of(new AiUpstream("primary", "http://127.0.0.1", wc)));
                return new AiIntegrationService(materials, summaries, mock(MaterialQuizRepository.class), mock(MaterialMemoRepository.class),
                                mock(MaterialQuestionRepository.class), mock(RoadmapRepository.class), mock(RoadmapTaskRepository.class), wc,
                                mock(IntentRouterService.class), mock(LearningLoopService.class), mock(MaterialQuizService.class),
                                new AiFailoverExecutor(ups), gate, collector);
        }

        MaterialSummary saved() {
                ArgumentCaptor<MaterialSummary> c = ArgumentCaptor.forClass(MaterialSummary.class);
                verify(summaries).save(c.capture());
                return c.getValue();
        }

        @Test
        void rejected79ThenApproved85IsSavedWithStatus() {
                evaluatorPolicy = n -> n == 1 ? out(79, "REJECTED") : out(85, "APPROVED");
                SummaryDTO dto = service(true, null).getSummary(USER, MATERIAL);
                assertEquals("APPROVED", dto.getQualityStatus());
                assertEquals(85.0, dto.getQualityScore());
                assertTrue(dto.getOverview().startsWith("요약 2"), "재생성된 두 번째 초안이 노출");
                assertEquals(2, summaryCalls.get());
                assertEquals("APPROVED", saved().getQualityStatus());
                JsonNode ev = evaluations.get(0);
                assertEquals("PDF_SUMMARY", ev.get("taskType").asText());
                assertEquals("PDF_ORIGINAL", ev.get("groundingEvidence").get(0).get("sourceType").asText());
                assertTrue(ev.get("groundingEvidence").get(0).get("text").asText().contains("3-way handshake"));
                assertEquals(List.of(0, 1), evaluations.stream().map(e -> e.get("attemptIndex").asInt()).toList());
        }

        @Test
        void allRejectedSavesNothingAndKeepsExistingSummary() {
                evaluatorPolicy = n -> out(60, "REJECTED");
                MaterialSummary legacy = MaterialSummary.builder().summaryId(1L).overview("기존 요약").coreContents("[]").build();
                SummaryDTO dto = service(true, legacy).getSummary(USER, MATERIAL);
                assertFalse(dto.getSuccess());
                assertEquals("AI_QUALITY_REJECTED", dto.getErrorCode());
                assertEquals("REJECTED", dto.getQualityStatus());
                assertEquals("", dto.getOverview(), "거절 초안은 응답 본문에 없다");
                assertEquals(3, summaryCalls.get(), "최초 1 + 재생성 2");
                verify(summaries, never()).save(any());
                assertEquals("기존 요약", legacy.getOverview(), "기존 정상 요약을 덮어쓰지 않는다");
        }

        @Test
        void unapprovedCachedSummaryIsNotServedWhenGateOn() {
                evaluatorPolicy = n -> out(90, "APPROVED");
                MaterialSummary legacy = MaterialSummary.builder().summaryId(1L).overview("게이트 전 요약").coreContents("[]").build();
                SummaryDTO dto = service(true, legacy).getSummary(USER, MATERIAL);
                assertEquals(1, summaryCalls.get(), "미승인 캐시 대신 재생성");
                assertTrue(dto.getOverview().startsWith("요약 1"));
        }

        @Test
        void approvedCachedSummaryIsServedWithoutAiCall() {
                evaluatorPolicy = n -> out(90, "APPROVED");
                MaterialSummary ok = MaterialSummary.builder().summaryId(1L).overview("승인된 요약").coreContents("[]")
                                .qualityStatus("APPROVED").qualityScore(91.0).build();
                SummaryDTO dto = service(true, ok).getSummary(USER, MATERIAL);
                assertEquals("승인된 요약", dto.getOverview());
                assertEquals("APPROVED", dto.getQualityStatus());
                assertEquals(0, summaryCalls.get());
                assertEquals(0, evaluations.size());
        }

        @Test
        void evaluatorDownBlocksWithoutRegeneration() {
                evaluatorPolicy = n -> null; // 503
                SummaryDTO dto = service(true, null).getSummary(USER, MATERIAL);
                assertEquals("AI_QUALITY_UNAVAILABLE", dto.getErrorCode());
                assertEquals("VALIDATION_ERROR", dto.getQualityStatus());
                assertEquals(1, summaryCalls.get());
                verify(summaries, never()).save(any());
        }

        @Test
        void upstreamGenerationFailureKeepsExistingContractWithoutRetry() {
                summaryFails = true;
                evaluatorPolicy = n -> out(90, "APPROVED");
                SummaryDTO dto = service(true, null).getSummary(USER, MATERIAL);
                assertEquals("AI_TIMEOUT", dto.getErrorCode());
                assertEquals(1, summaryCalls.get(), "ai07 생성 실패는 재생성하지 않는다");
                assertEquals(0, evaluations.size());
        }

        @Test
        void gateOffIsUnchanged() {
                evaluatorPolicy = n -> out(10, "REJECTED");
                SummaryDTO dto = service(false, null).getSummary(USER, MATERIAL);
                assertTrue(dto.getOverview().startsWith("요약 1"));
                assertNull(dto.getQualityStatus());
                assertEquals(0, evaluations.size(), "게이트 OFF 는 평가기를 부르지 않는다");
                verify(summaries, times(1)).save(any());
                assertNull(saved().getQualityStatus());
        }

        @Test
        void everyStoredFieldIsEvaluatedIncludingGptRaw() {
                gptRaw = "RAW_ONLY_TEXT 원문과 다른 서술";
                evaluatorPolicy = n -> out(90, "APPROVED");
                service(true, null).getSummary(USER, MATERIAL);
                assertTrue(evaluations.get(0).get("proposedOutput").asText().contains("RAW_ONLY_TEXT"),
                                "저장·표시되는 gpt_raw 도 평가 대상");
        }

        @Test
        void rejectionCooldownAvoidsRegenerationStorm() {
                evaluatorPolicy = n -> out(60, "REJECTED");
                AiIntegrationService svc = service(true, null);
                svc.getSummary(USER, MATERIAL);
                assertEquals(3, summaryCalls.get());
                SummaryDTO again = svc.getSummary(USER, MATERIAL);
                assertEquals(3, summaryCalls.get(), "거절 직후 재요청은 재생성하지 않는다(쿨다운)");
                assertEquals("AI_QUALITY_REJECTED", again.getErrorCode());
        }
}
