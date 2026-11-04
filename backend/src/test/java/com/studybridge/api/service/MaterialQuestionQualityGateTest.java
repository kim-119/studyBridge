package com.studybridge.api.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyMap;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.ai.AiFailoverExecutor;
import com.studybridge.api.ai.AiUpstream;
import com.studybridge.api.ai.AiUpstreams;
import com.studybridge.api.ai.contract.v1.ResponseQualityV1;
import com.studybridge.api.ai.quality.AiQualityGateSettings;
import com.studybridge.api.ai.quality.AiResponseQualityGate;
import com.studybridge.api.ai.quality.GateEvidence;
import com.studybridge.api.ai.quality.QualityEvaluatorClient;
import com.studybridge.api.dto.IntentDTO;
import com.studybridge.api.dto.QuestionDTO;
import com.studybridge.api.entity.Material;
import com.studybridge.api.entity.MaterialQuestion;
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
 * 자료 질문(POST /api/materials/{materialId}/question) 품질 게이트(Phase D, PDF_QA):
 * 79 거절 → 80 승인 경계, 전부 거절·평가기 503 시 저장 0·초안 미노출, 생성 실패는 기존 계약, 라우터 LLM 문구 미노출,
 * BLOCKED 파이프라인 우회 차단, 긴 자료의 질문 관련 근거 선택, 게이트 OFF 회귀 없음.
 */
class MaterialQuestionQualityGateTest {

        static final long USER = 61L;
        static final long MATERIAL = 512L;
        static final ObjectMapper M = new ObjectMapper();
        static final String PDF_TEXT = "TCP 연결은 3-way handshake(SYN, SYN-ACK, ACK)로 수립한다. 연결 해제는 4단계 FIN 교환이다. ";

        HttpServer server;
        final AtomicInteger questionCalls = new AtomicInteger();
        final List<JsonNode> evaluations = new CopyOnWriteArrayList<>();
        volatile IntFunction<String> evaluatorPolicy = n -> out(90, "APPROVED", false);
        volatile String questionReply; // null 이면 정상 초안
        MaterialQuestionRepository questions;
        RoadmapRepository roadmaps;
        IntentRouterService router;

        @BeforeEach
        void up() throws Exception {
                server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
                server.createContext("/api/ai/question", ex -> {
                        int n = questionCalls.incrementAndGet();
                        ex.getRequestBody().readAllBytes();
                        String body = questionReply != null ? questionReply
                                        : "{\"success\":true,\"answer\":\"초안 " + n + ": TCP 연결은 SYN, SYN-ACK, ACK 3-way handshake 로 수립됩니다.\","
                                                        + "\"usedChunks\":[0],\"warnings\":[],\"metadata\":{\"provider\":\"ollama+gpt\"}}";
                        send(ex, 200, body);
                });
                server.createContext("/api/ai/quality/evaluate", ex -> {
                        JsonNode in = M.readTree(ex.getRequestBody().readAllBytes());
                        evaluations.add(in);
                        String body = evaluatorPolicy.apply(evaluations.size());
                        send(ex, body == null ? 503 : 200, body == null ? "{}" : body.replace("RID", in.get("requestId").asText()));
                });
                server.start();
        }

        static void send(com.sun.net.httpserver.HttpExchange ex, int status, String body) throws java.io.IOException {
                byte[] b = body.getBytes(StandardCharsets.UTF_8);
                ex.getResponseHeaders().add("Content-Type", "application/json");
                ex.sendResponseHeaders(status, b.length);
                ex.getResponseBody().write(b);
                ex.close();
        }

        @AfterEach
        void down() {
                server.stop(0);
        }

        static String out(double score, String status, boolean hardFail) {
                return "{\"schemaVersion\":\"response-quality.v1\",\"requestId\":\"RID\",\"taskType\":\"PDF_QA\",\"success\":true,\"verified\":"
                                + "APPROVED".equals(status) + ",\"qualityStatus\":\"" + status + "\",\"score\":" + score
                                + ",\"minimumScore\":80,\"hardFail\":" + hardFail + ",\"violations\":"
                                + (hardFail ? "[{\"code\":\"SOURCE_CONTRADICTION\",\"severity\":\"HARD\",\"reason\":\"r\"}]" : "[]")
                                + ",\"dimensions\":[],\"evaluatorVersion\":\"stub\",\"latencyMs\":1}";
        }

        AiIntegrationService service(boolean gateOn, String text, IntentDTO.RouteResult route) {
                WebClient wc = WebClient.create("http://127.0.0.1:" + server.getAddress().getPort());
                MaterialRepository materials = mock(MaterialRepository.class);
                Material material = Material.builder().materialId(MATERIAL).userId(USER).title("네트워크").extractedText(text).build();
                when(materials.findById(MATERIAL)).thenReturn(Optional.of(material));
                questions = mock(MaterialQuestionRepository.class);
                when(questions.save(any(MaterialQuestion.class))).thenAnswer(inv -> inv.getArgument(0));
                roadmaps = mock(RoadmapRepository.class);
                router = mock(IntentRouterService.class);
                when(router.route(anyString(), anyString(), anyMap())).thenReturn(route);
                MaterialSummaryRepository summaries = mock(MaterialSummaryRepository.class);
                when(summaries.findByMaterial_MaterialId(MATERIAL)).thenReturn(Optional.of(MaterialSummary.builder().summaryId(1L)
                                .overview("승인된 요약").coreContents("[{\"title\":\"연결\",\"content\":\"SYN\"}]").qualityStatus("APPROVED").build()));
                AiQualityGateSettings s = AiQualityGateSettings.forTest(gateOn);
                AiResponseQualityGate gate = new AiResponseQualityGate(s, new QualityEvaluatorClient(wc, s, "k".repeat(64)));
                AiUpstreams ups = new AiUpstreams(List.of(new AiUpstream("primary", "http://127.0.0.1", wc)));
                return new AiIntegrationService(materials, summaries, mock(MaterialQuizRepository.class), mock(MaterialMemoRepository.class),
                                questions, roadmaps, mock(RoadmapTaskRepository.class), wc, router, mock(LearningLoopService.class),
                                mock(MaterialQuizService.class), new AiFailoverExecutor(ups), gate, null);
        }

        AiIntegrationService service(boolean gateOn) {
                return service(gateOn, PDF_TEXT.repeat(10), proceed());
        }

        static IntentDTO.RouteResult proceed() {
                return IntentDTO.RouteResult.builder().action(IntentDTO.RouteAction.PROCEED).usedFallback(true).build();
        }

        static QuestionDTO.Request ask(String q) {
                return new QuestionDTO.Request(q);
        }

        MaterialQuestion saved() {
                ArgumentCaptor<MaterialQuestion> c = ArgumentCaptor.forClass(MaterialQuestion.class);
                verify(questions).save(c.capture());
                return c.getValue();
        }

        @GateEvidence({"POST /api/materials/{materialId}/question"})
        @Test
        void rejected79ThenApproved80IsSavedAndOnlyApprovedAnswerShown() {
                evaluatorPolicy = n -> n == 1 ? out(79, "REJECTED", false) : out(80, "APPROVED", false);
                QuestionDTO.Response r = service(true).askQuestion(USER, MATERIAL, ask("TCP 연결은 어떻게 수립되나요?"));
                assertTrue(r.getSuccess());
                assertEquals("APPROVED", r.getQualityStatus());
                assertEquals(80.0, r.getQualityScore());
                assertTrue(r.getVerified());
                assertTrue(r.getAiAnswer().startsWith("초안 2"), "재생성된 두 번째 초안만 노출");
                assertEquals(2, questionCalls.get());
                MaterialQuestion row = saved();
                assertEquals("APPROVED", row.getQualityStatus());
                assertTrue(row.getAiAnswer().startsWith("초안 2"), "79 점 초안은 저장되지 않는다");
                JsonNode ev = evaluations.get(0);
                assertEquals("PDF_QA", ev.get("taskType").asText());
                assertEquals("text", ev.get("outputKind").asText());
                assertEquals("TCP 연결은 어떻게 수립되나요?", ev.get("originalRequest").asText());
                assertTrue(ev.get("proposedOutput").asText().startsWith("초안 1"), "사용자에게 보일 답변 전체를 평가");
                assertEquals("PDF_ORIGINAL", ev.get("groundingEvidence").get(0).get("sourceType").asText());
                assertTrue(ev.get("groundingEvidence").get(0).get("text").asText().contains("3-way handshake"), "Spring 이 가진 자료 원문 근거");
                assertEquals(MATERIAL, ev.get("constraints").get("allowedMaterialIds").get(0).asLong());
                assertEquals(2, evaluations.size());
        }

        @GateEvidence({"POST /api/materials/{materialId}/question"})
        @Test
        void allRejectedSavesNothingAndShowsNoDraft() {
                evaluatorPolicy = n -> out(70, "REJECTED", false);
                QuestionDTO.Response r = service(true).askQuestion(USER, MATERIAL, ask("TCP 연결은 어떻게 수립되나요?"));
                assertFalse(r.getSuccess());
                assertEquals("AI_QUALITY_REJECTED", r.getErrorCode());
                assertEquals("REJECTED", r.getQualityStatus());
                assertFalse(r.getVerified());
                assertTrue(r.getRetryable());
                assertFalse(r.getAiAnswer().contains("초안"), "거절 초안은 응답 어디에도 없다");
                assertNull(r.getQuestionId());
                assertEquals(3, questionCalls.get(), "최초 1 + 재생성 2");
                verify(questions, never()).save(any());
        }

        @Test
        void hardFailIsRejectedEvenWithHighScore() {
                evaluatorPolicy = n -> out(95, "REJECTED", true);
                QuestionDTO.Response r = service(true).askQuestion(USER, MATERIAL, ask("TCP 연결은?"));
                assertEquals("AI_QUALITY_REJECTED", r.getErrorCode());
                verify(questions, never()).save(any());
        }

        @Test
        void evaluatorDownIsUnavailableNotDisguisedSuccess() {
                evaluatorPolicy = n -> null; // 503
                QuestionDTO.Response r = service(true).askQuestion(USER, MATERIAL, ask("TCP 연결은?"));
                assertFalse(r.getSuccess());
                assertEquals("AI_QUALITY_UNAVAILABLE", r.getErrorCode());
                assertEquals("VALIDATION_ERROR", r.getQualityStatus());
                assertFalse(r.getAiAnswer().contains("초안"));
                assertEquals(1, questionCalls.get(), "평가기 장애 시 재생성하지 않는다");
                verify(questions, never()).save(any());
        }

        @Test
        void generationFailureKeepsLegacyContractWithoutEvaluation() {
                questionReply = "{\"success\":false,\"errorCode\":\"AI_TIMEOUT\",\"message\":\"m\",\"retryable\":true,\"answer\":\"AI 응답 시간이 초과되었습니다.\"}";
                QuestionDTO.Response r = service(true).askQuestion(USER, MATERIAL, ask("TCP 연결은?"));
                assertEquals("AI_TIMEOUT", r.getErrorCode());
                assertEquals(1, questionCalls.get());
                assertEquals(0, evaluations.size(), "생성 실패면 평가하지 않는다");
                verify(questions, never()).save(any());
                questionCalls.set(0);
                questionReply = "{\"success\":true,\"answer\":\"  \"}";
                QuestionDTO.Response blank = service(true).askQuestion(USER, MATERIAL, ask("TCP 연결은?"));
                assertEquals("AI_RESPONSE_INVALID", blank.getErrorCode(), "빈 답변을 자리표시 문구로 저장·노출하지 않는다");
                assertEquals(0, evaluations.size());
        }

        @Test
        void routerLlmTextIsReplacedByTemplateAndBlockedPipelineIsNotRun() {
                IntentDTO.RouteResult llmReply = IntentDTO.RouteResult.builder().action(IntentDTO.RouteAction.DIRECT_REPLY)
                                .directReply("LLM 이 만든 미검증 인사말").build();
                QuestionDTO.Response terminal = service(true, PDF_TEXT, llmReply).askQuestion(USER, MATERIAL, ask("안녕"));
                assertFalse(terminal.getAiAnswer().contains("미검증"), "라우터 LLM 문구는 게이트 ON 에서 노출하지 않는다");
                assertEquals(0, questionCalls.get());

                IntentDTO.RouteResult roadmap = IntentDTO.RouteResult.builder().action(IntentDTO.RouteAction.ROADMAP_PIPELINE).build();
                QuestionDTO.Response blocked = service(true, PDF_TEXT, roadmap).askQuestion(USER, MATERIAL, ask("로드맵 만들어 줘"));
                assertFalse(blocked.getSuccess());
                assertEquals("AI_QUALITY_GATE_NOT_WIRED", blocked.getErrorCode(), "BLOCKED 로드맵 파이프라인을 질문 경로로 우회하지 않는다");
                verifyNoInteractions(roadmaps);

                IntentDTO.RouteResult summary = IntentDTO.RouteResult.builder().action(IntentDTO.RouteAction.SUMMARY_PIPELINE).build();
                QuestionDTO.Response ok = service(true, PDF_TEXT, summary).askQuestion(USER, MATERIAL, ask("요약해 줘"));
                assertTrue(ok.getSuccess(), "GATED 요약 파이프라인(승인 저장본)은 그대로 실행");
                assertEquals("SUMMARY_PIPELINE", ok.getRouteAction());

                IntentDTO.RouteResult warn = IntentDTO.RouteResult.builder().action(IntentDTO.RouteAction.WARN)
                                .warningMessage("LLM 경고 원문").build();
                QuestionDTO.Response warned = service(true, PDF_TEXT.repeat(5), warn).askQuestion(USER, MATERIAL, ask("TCP 연결은?"));
                assertFalse(warned.getRouteMessage().contains("LLM 경고 원문"));
        }

        @Test
        void longDocumentEvidenceSelectsQuestionRelevantWindowsOfThisMaterialOnly() {
                StringBuilder sb = new StringBuilder();
                while (sb.length() < 100_000) {
                        sb.append("운영체제 스케줄링은 프로세스에 CPU 를 배분한다. ");
                }
                int at = sb.length();
                sb.append("혼잡 제어는 슬로 스타트와 혼잡 회피로 송신 윈도를 조절한다. ".repeat(40));
                String text = sb.toString();
                List<ResponseQualityV1.GroundingEvidence> ev = AiIntegrationService.questionEvidence(MATERIAL, text, "혼잡 제어는 어떻게 동작하나요?");
                assertEquals(12, ev.size());
                assertTrue(ev.stream().allMatch(g -> g.materialId() == MATERIAL && g.text().length() <= ResponseQualityV1.MAX_EVIDENCE_CHARS));
                assertTrue(ev.stream().anyMatch(g -> g.text().contains("혼잡 제어")), "질문 관련 후반부 구간(" + at + "자 이후)이 근거에 포함");
                assertEquals(AiResponseQualityGate.pdfEvidence(MATERIAL, PDF_TEXT, 4000, 48000).size(),
                                AiIntegrationService.questionEvidence(MATERIAL, PDF_TEXT, "x").size(), "짧은 자료는 전체 원문");
        }

        @Test
        void gateOffIsLegacyBehaviour() {
                QuestionDTO.Response r = service(false).askQuestion(USER, MATERIAL, ask("TCP 연결은?"));
                assertTrue(r.getAiAnswer().startsWith("초안 1"));
                assertNull(r.getQualityStatus());
                assertNull(r.getVerified());
                assertEquals(0, evaluations.size(), "게이트 OFF: 평가기 호출 0");
                assertNull(saved().getQualityStatus());
                IntentDTO.RouteResult llmReply = IntentDTO.RouteResult.builder().action(IntentDTO.RouteAction.DIRECT_REPLY)
                                .directReply("라우터 인사말").build();
                assertEquals("라우터 인사말", service(false, PDF_TEXT, llmReply).askQuestion(USER, MATERIAL, ask("안녕")).getAiAnswer());
        }
}
