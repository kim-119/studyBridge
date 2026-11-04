package com.studybridge.api.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.ai.quality.AiQualityGateSettings;
import com.studybridge.api.ai.quality.AiResponseQualityGate;
import com.studybridge.api.ai.quality.QualityEvaluatorClient;
import com.studybridge.api.dto.FeedbackDTO;
import com.studybridge.api.entity.Material;
import com.studybridge.api.entity.MaterialFeedback;
import com.studybridge.api.entity.MaterialType;
import com.studybridge.api.exception.AiUpstreamException;
import com.studybridge.api.repository.MaterialFeedbackRepository;
import com.studybridge.api.repository.MaterialRepository;
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
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.web.reactive.function.client.WebClient;

/**
 * 자료 피드백 품질 게이트(Phase C): 79 거절→85 승인 저장, 전부 거절 시 저장 0·기존 보존, 평가기 503 미노출,
 * 미승인 레거시 저장본 미노출, 승인 저장본은 AI 호출 0, 거절 쿨다운, 생성 실패는 기존 계약, 게이트 OFF 회귀 없음.
 */
class MaterialFeedbackQualityGateTest {

        static final long USER = 8L;
        static final long MATERIAL = 404L;
        static final ObjectMapper M = new ObjectMapper();
        HttpServer server;
        final AtomicInteger feedbackCalls = new AtomicInteger();
        final List<JsonNode> evaluations = new CopyOnWriteArrayList<>();
        volatile IntFunction<String> evaluatorPolicy = n -> out(90, "APPROVED");
        volatile boolean feedbackFails;
        MaterialFeedbackRepository feedbacks;

        @BeforeEach
        void up() throws Exception {
                server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
                server.createContext("/api/ai/feedback", ex -> {
                        int n = feedbackCalls.incrementAndGet();
                        ex.getRequestBody().readAllBytes();
                        String body = feedbackFails ? "{\"success\":false,\"errorCode\":\"AI_TIMEOUT\",\"retryable\":true}"
                                        : "{\"success\":true,\"strengths\":[\"초안 " + n + ": ViewModel 생명주기를 정확히 짚었다.\"],"
                                                        + "\"recommendations\":[\"SavedStateHandle 예시를 추가하자.\"],\"concerns\":[\"프로세스 종료 시 유지 범위 확인\"]}";
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
                return "{\"schemaVersion\":\"response-quality.v1\",\"requestId\":\"RID\",\"taskType\":\"GENERAL_EXPLANATION\",\"success\":true,"
                                + "\"verified\":" + "APPROVED".equals(status) + ",\"qualityStatus\":\"" + status + "\",\"score\":" + score
                                + ",\"minimumScore\":80,\"hardFail\":false,\"violations\":[],\"dimensions\":[],\"evaluatorVersion\":\"stub\","
                                + "\"latencyMs\":1,\"mandatoryValidatorsPassed\":true}";
        }

        MaterialFeedbackService service(boolean gateOn, MaterialFeedback cached) {
                WebClient wc = WebClient.create("http://127.0.0.1:" + server.getAddress().getPort());
                MaterialRepository materials = mock(MaterialRepository.class);
                Material material = Material.builder().materialId(MATERIAL).userId(USER).materialType(MaterialType.STUDY_LOG).title("ViewModel")
                                .learningContent("ViewModel 은 화면 회전 같은 구성 변경에서 유지된다. ".repeat(20)).build();
                when(materials.findById(MATERIAL)).thenReturn(Optional.of(material));
                feedbacks = mock(MaterialFeedbackRepository.class);
                when(feedbacks.findByMaterial_MaterialId(MATERIAL)).thenReturn(Optional.ofNullable(cached));
                when(feedbacks.saveAndFlush(any(MaterialFeedback.class))).thenAnswer(inv -> inv.getArgument(0));
                AiRequestGuard guard = mock(AiRequestGuard.class);
                when(guard.tryLock(anyString(), any())).thenAnswer(inv -> new AiRequestGuard.Lock(inv.getArgument(0), "t", true));
                MaterialFeedbackService svc = new MaterialFeedbackService(materials, feedbacks, wc, guard, mock(PlatformTransactionManager.class),
                                5, false);
                AiQualityGateSettings s = AiQualityGateSettings.forTest(gateOn);
                svc.setQualityGate(new AiResponseQualityGate(s, new QualityEvaluatorClient(wc, s, "k".repeat(64))));
                return svc;
        }

        MaterialFeedback saved() {
                ArgumentCaptor<MaterialFeedback> c = ArgumentCaptor.forClass(MaterialFeedback.class);
                verify(feedbacks).saveAndFlush(c.capture());
                return c.getValue();
        }

        static MaterialFeedback legacy(String status) {
                return MaterialFeedback.builder().feedbackId(1L).material(Material.builder().materialId(MATERIAL).build())
                                .feedbackData("{\"strengths\":[\"레거시 미검증 피드백\"]}").qualityStatus(status).build();
        }

        @Test
        void rejected79ThenApproved85IsSavedWithStatus() {
                evaluatorPolicy = n -> n == 1 ? out(79, "REJECTED") : out(85, "APPROVED");
                FeedbackDTO dto = service(true, null).regenerate(USER, MATERIAL);
                assertEquals("APPROVED", dto.getQualityStatus());
                assertEquals(85.0, dto.getQualityScore());
                assertTrue(dto.getFeedbackData().contains("초안 2"), "재생성된 두 번째 초안만 노출");
                assertEquals(2, feedbackCalls.get());
                assertEquals("APPROVED", saved().getQualityStatus());
                JsonNode ev = evaluations.get(0);
                assertEquals("GENERAL_EXPLANATION", ev.get("taskType").asText());
                assertTrue(ev.get("proposedOutput").toString().contains("초안 1"), "사용자에게 보일 본문 전체를 평가");
                assertTrue(ev.get("groundingEvidence").size() > 0, "자료 원문 근거 동봉");
        }

        @Test
        void threeRejectionsSaveNothingAndKeepExisting() {
                evaluatorPolicy = n -> out(70, "REJECTED");
                AiUpstreamException e = assertThrows(AiUpstreamException.class, () -> service(true, legacy("APPROVED")).regenerate(USER, MATERIAL));
                assertEquals("AI_QUALITY_REJECTED", e.getCode());
                assertEquals(422, e.getStatus().value());
                assertTrue(e.isRetryable());
                assertEquals(3, feedbackCalls.get(), "최초 1 + 재생성 2");
                verify(feedbacks, never()).saveAndFlush(any());
        }

        @Test
        void evaluatorDownIsUnavailableNotDisguisedSuccess() {
                evaluatorPolicy = n -> null; // 503
                AiUpstreamException e = assertThrows(AiUpstreamException.class, () -> service(true, null).regenerate(USER, MATERIAL));
                assertEquals("AI_QUALITY_UNAVAILABLE", e.getCode());
                assertEquals(503, e.getStatus().value());
                assertEquals(1, feedbackCalls.get(), "평가기 장애 시 재생성하지 않는다(부하 3배 방지)");
                verify(feedbacks, never()).saveAndFlush(any());
        }

        @Test
        void unapprovedLegacyCacheIsNotReexposedAndApprovedCacheNeedsNoAi() {
                FeedbackDTO fresh = service(true, legacy(null)).get(USER, MATERIAL);
                assertEquals("APPROVED", fresh.getQualityStatus(), "레거시(미검증) 저장본 대신 새로 검증한 것");
                assertTrue(!fresh.getFeedbackData().contains("레거시"));
                feedbackCalls.set(0);
                evaluations.clear();
                FeedbackDTO cached = service(true, legacy("APPROVED")).get(USER, MATERIAL);
                assertTrue(cached.getFeedbackData().contains("레거시 미검증 피드백"));
                assertEquals(0, feedbackCalls.get(), "승인 저장본은 AI 호출 0");
                assertEquals(0, evaluations.size());
        }

        @Test
        void rejectionCooldownPreventsRegenerationStorm() {
                evaluatorPolicy = n -> out(60, "REJECTED");
                MaterialFeedbackService svc = service(true, legacy(null));
                assertThrows(AiUpstreamException.class, () -> svc.get(USER, MATERIAL));
                int calls = feedbackCalls.get();
                AiUpstreamException again = assertThrows(AiUpstreamException.class, () -> svc.get(USER, MATERIAL));
                assertEquals("AI_QUALITY_REJECTED", again.getCode());
                assertEquals(calls, feedbackCalls.get(), "쿨다운 중 재조회는 생성 0");
        }

        @Test
        void generationFailureKeepsLegacyContract() {
                feedbackFails = true;
                AiUpstreamException e = assertThrows(AiUpstreamException.class, () -> service(true, null).regenerate(USER, MATERIAL));
                assertEquals("AI_TIMEOUT", e.getCode());
                assertEquals(1, feedbackCalls.get());
                assertEquals(0, evaluations.size(), "생성 실패면 평가하지 않는다");
        }

        @Test
        void gateOffIsLegacyBehaviour() {
                FeedbackDTO dto = service(false, null).regenerate(USER, MATERIAL);
                assertNull(dto.getQualityStatus());
                assertEquals(0, evaluations.size(), "게이트 OFF: 평가기 호출 0");
                assertNull(saved().getQualityStatus());
                FeedbackDTO legacyShown = service(false, legacy(null)).get(USER, MATERIAL);
                assertTrue(legacyShown.getFeedbackData().contains("레거시"), "OFF 에선 기존 저장본 그대로");
        }
}
