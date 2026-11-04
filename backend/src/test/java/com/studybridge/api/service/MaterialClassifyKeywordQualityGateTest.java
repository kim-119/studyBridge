package com.studybridge.api.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.JsonNode;
import com.studybridge.api.ai.AiFailoverExecutor;
import com.studybridge.api.ai.AiUpstream;
import com.studybridge.api.ai.AiUpstreams;
import com.studybridge.api.ai.quality.GateEvidence;
import com.studybridge.api.dto.KeywordDefineDTO;
import com.studybridge.api.entity.Material;
import com.studybridge.api.entity.MaterialType;
import com.studybridge.api.repository.MaterialMemoRepository;
import com.studybridge.api.repository.MaterialQuestionRepository;
import com.studybridge.api.repository.MaterialQuizRepository;
import com.studybridge.api.repository.MaterialRepository;
import com.studybridge.api.repository.MaterialSummaryRepository;
import com.studybridge.api.repository.RoadmapRepository;
import com.studybridge.api.repository.RoadmapTaskRepository;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

/**
 * 자료 업로드 전 유형 판별(classify-before-save)·핵심 키워드 정의(keywords/define) 품질 게이트(Phase D — material):
 * 79 거절→80 승인 재생성, 전부 거절/평가기 503 이면 AI 문구 0(성공 위장 없음), hardFail 거절, ai07 생성 실패는 기존 계약(평가 0),
 * 근거 동봉(분류기 입력 / 자료 원문 + allowedMaterialIds), 게이트 OFF 회귀 없음.
 */
class MaterialClassifyKeywordQualityGateTest {

        static final long USER = 31L;
        static final long MATERIAL = 512L;
        static final String PDF_TEXT = "운영체제의 프로세스 스케줄링은 CPU 를 어느 프로세스에 할당할지 결정한다. 라운드 로빈은 타임 슬라이스를 쓴다. ";
        static final String CLASSIFY = "/api/ai/material/classify";
        static final String KEYWORD = "/api/ai/keyword/define";

        MaterialAiStubServer stub;
        volatile boolean classifyDown;
        volatile boolean keywordFails;

        @BeforeEach
        void up() throws Exception {
                stub = new MaterialAiStubServer();
                stub.route(CLASSIFY, (n, in) -> classifyDown ? new MaterialAiStubServer.Reply(500, "{}")
                                : new MaterialAiStubServer.Reply(200, "{\"success\":true,\"recommended_type\":\"PLANNER\",\"selected_type\":\"STUDY_PDF\","
                                                + "\"is_mismatch\":true,\"confidence\":0.82,\"reason\":\"분류근거초안" + n + ": 시간표와 목표 학습 시간 단서가 보여 플래너로 판단했습니다.\","
                                                + "\"user_message\":\"이 파일은 학습PDF가 아니라 플래너로 보입니다. 알맞은 곳에 넣으세요.\","
                                                + "\"allowed_actions\":[{\"label\":\"플래너로 저장\",\"type\":\"PLANNER\",\"recommended\":true},"
                                                + "{\"label\":\"취소\",\"type\":\"CANCEL\",\"recommended\":false}],"
                                                + "\"capability_hint\":{\"planner_enabled\":true},\"error_code\":null}"));
                stub.json(KEYWORD, n -> keywordFails ? "{\"success\":false,\"errorCode\":\"AI_TIMEOUT\",\"message\":\"m\"}"
                                : "{\"success\":true,\"name\":\"라운드 로빈\",\"shortDefinition\":\"정의초안" + n + ": 타임 슬라이스마다 프로세스를 돌아가며 실행한다.\","
                                                + "\"detailedDefinition\":\"CPU 스케줄링 기법의 하나다.\",\"importance\":\"응답 시간을 공정하게 만든다.\","
                                                + "\"examples\":[\"시분할 시스템\"],\"relatedConcepts\":[\"타임 슬라이스\",\"선점형 스케줄링\"],"
                                                + "\"sourceUsed\":\"GPT\",\"wikiUrl\":\"https://ko.wikipedia.org/wiki/RR\"}");
        }

        @AfterEach
        void down() {
                stub.close();
        }

        AiIntegrationService service(boolean gateOn) {
                MaterialRepository materials = mock(MaterialRepository.class);
                Material material = Material.builder().materialId(MATERIAL).userId(USER).materialType(MaterialType.PDF).title("운영체제")
                                .extractedText(PDF_TEXT.repeat(8)).build();
                when(materials.findById(MATERIAL)).thenReturn(Optional.of(material));
                AiUpstreams ups = new AiUpstreams(List.of(new AiUpstream("primary", "http://127.0.0.1", stub.client())));
                AiIntegrationService svc = new AiIntegrationService(materials, mock(MaterialSummaryRepository.class), mock(MaterialQuizRepository.class),
                                mock(MaterialMemoRepository.class), mock(MaterialQuestionRepository.class), mock(RoadmapRepository.class),
                                mock(RoadmapTaskRepository.class), stub.client(), mock(IntentRouterService.class), mock(LearningLoopService.class),
                                mock(MaterialQuizService.class), new AiFailoverExecutor(ups), stub.gate(gateOn),
                                mock(com.studybridge.api.ai.training.TrainingCandidateCollector.class));
                ReflectionTestUtils.setField(svc, "keywordDefineTimeoutSeconds", 10L);
                return svc;
        }

        Map<String, Object> classify(AiIntegrationService svc) {
                return svc.classifyBeforeSave("week3_plan.pdf", "application/pdf", "STUDY_PDF", null, "3주차 공부 계획", List.of("플래너", "시간표"));
        }

        KeywordDefineDTO.Response define(AiIntegrationService svc) {
                return svc.defineKeyword(USER, MATERIAL, KeywordDefineDTO.Request.builder().keyword("라운드 로빈").context("클라이언트가 보낸 맥락").build());
        }

        // ───────────────────────── classify-before-save ─────────────────────────

        @GateEvidence({"POST /api/materials/classify-before-save"})
        @Test
        void classifyRejected79ThenApproved80ShowsOnlyApprovedDraft() {
                stub.evaluator = (n, in) -> n == 1 ? MaterialAiStubServer.out(79, "REJECTED") : MaterialAiStubServer.out(80, "APPROVED");
                Map<String, Object> res = classify(service(true));
                assertEquals(true, res.get("success"));
                assertEquals("APPROVED", res.get("qualityStatus"));
                assertTrue(String.valueOf(res.get("reason")).startsWith("분류근거초안2"), "재분류된 두 번째 초안만 노출");
                assertEquals(2, stub.calls(CLASSIFY));
                assertEquals(2, stub.evaluations.size());
                JsonNode ev = stub.evaluations.get(0);
                assertEquals("GENERAL_EXPLANATION", ev.get("taskType").asText());
                assertEquals("text", ev.get("outputKind").asText());
                String proposed = MaterialAiStubServer.text(ev);
                assertTrue(proposed.contains("분류근거초안1") && proposed.contains("알맞은 곳에 넣으세요") && proposed.contains("플래너로 저장"),
                                "사용자에게 보이는 문자열 전부(근거·안내·선택지 라벨)를 평가");
                JsonNode g = ev.get("groundingEvidence").get(0);
                assertEquals("USER_INPUT", g.get("sourceType").asText());
                assertTrue(g.get("text").asText().contains("week3_plan.pdf"), "분류기가 실제로 본 입력을 근거로");
        }

        @GateEvidence({"POST /api/materials/classify-before-save"})
        @Test
        void classifyRejectedOrUnavailableReturnsExplicitFailureWithoutAiText() {
                stub.evaluator = (n, in) -> MaterialAiStubServer.out(70, "REJECTED");
                Map<String, Object> rej = classify(service(true));
                assertEquals(false, rej.get("success"));
                assertEquals("AI_QUALITY_REJECTED", rej.get("errorCode"));
                assertEquals(true, rej.get("retryable"));
                assertFalse(rej.containsKey("reason") || rej.containsKey("recommendedType") || rej.containsKey("allowedActions"));
                assertFalse(rej.toString().contains("분류근거초안"), "초안 문구 0");
                assertEquals(3, stub.calls(CLASSIFY), "최초 1 + 재분류 2");

                stub.evaluations.clear();
                stub.evaluator = (n, in) -> null; // 503
                Map<String, Object> down = classify(service(true));
                assertEquals("AI_QUALITY_UNAVAILABLE", down.get("errorCode"));
                assertFalse(down.toString().contains("분류근거초안"));
                assertEquals(4, stub.calls(CLASSIFY), "평가기 장애면 재분류하지 않는다");
        }

        @Test
        void classifyHardFailIsRejectedEvenAt95() {
                stub.evaluator = (n, in) -> MaterialAiStubServer.out(95, "REJECTED", true, "PROMPT_INJECTION_SUCCESS");
                Map<String, Object> res = classify(service(true));
                assertEquals("AI_QUALITY_REJECTED", res.get("errorCode"));
                assertFalse(res.toString().contains("분류근거초안"));
        }

        @Test
        void classifyUpstreamDownKeepsSpringFallbackWithoutEvaluation() {
                classifyDown = true;
                Map<String, Object> res = classify(service(true));
                assertEquals(true, res.get("success"));
                assertEquals(false, res.get("isMismatch"));
                assertEquals("STUDY_PDF", res.get("recommendedType"), "Spring 고정 폴백(선택 유형으로 진행, AI 문구 없음)");
                assertEquals(0, stub.evaluations.size());
        }

        @Test
        void classifyGateOffIsLegacy() {
                Map<String, Object> res = classify(service(false));
                assertTrue(String.valueOf(res.get("reason")).startsWith("분류근거초안1"));
                assertFalse(res.containsKey("qualityStatus"));
                assertEquals(0, stub.evaluations.size(), "게이트 OFF: 평가기 호출 0");
        }

        // ───────────────────────── keywords/define ─────────────────────────

        @GateEvidence({"POST /api/materials/{materialId}/keywords/define"})
        @Test
        void keywordRejected79ThenApproved80WithMaterialEvidence() {
                stub.evaluator = (n, in) -> n == 1 ? MaterialAiStubServer.out(79, "REJECTED") : MaterialAiStubServer.out(80, "APPROVED");
                KeywordDefineDTO.Response res = define(service(true));
                assertTrue(res.getSuccess());
                assertEquals("APPROVED", res.getQualityStatus());
                assertEquals(80.0, res.getQualityScore());
                assertTrue(res.getShortDefinition().startsWith("정의초안2"));
                assertEquals(2, stub.calls(KEYWORD));
                JsonNode ev = stub.evaluations.get(0);
                assertEquals("GENERAL_EXPLANATION", ev.get("taskType").asText());
                String proposed = MaterialAiStubServer.text(ev);
                for (String s : List.of("정의초안1", "CPU 스케줄링 기법", "응답 시간을 공정하게", "시분할 시스템", "선점형 스케줄링", "GPT", "wikipedia.org")) {
                        assertTrue(proposed.contains(s), "응답 DTO 의 모든 문자열 평가: " + s);
                }
                JsonNode g = ev.get("groundingEvidence");
                assertTrue(g.size() > 0);
                assertEquals("PDF_ORIGINAL", g.get(0).get("sourceType").asText());
                assertEquals(MATERIAL, g.get(0).get("materialId").asLong());
                assertTrue(g.get(0).get("text").asText().contains("라운드 로빈은 타임 슬라이스"), "근거 = Spring 이 가진 자료 원문");
                assertFalse(g.toString().contains("클라이언트가 보낸 맥락"), "클라이언트 context 는 근거가 아니다");
                assertEquals(MATERIAL, ev.get("constraints").get("allowedMaterialIds").get(0).asLong());
        }

        @GateEvidence({"POST /api/materials/{materialId}/keywords/define"})
        @Test
        void keywordRejectedOrUnavailableReturnsNoDefinition() {
                stub.evaluator = (n, in) -> MaterialAiStubServer.out(60, "REJECTED");
                KeywordDefineDTO.Response rej = define(service(true));
                assertFalse(rej.getSuccess());
                assertEquals("AI_QUALITY_REJECTED", rej.getErrorCode());
                assertTrue(rej.getRetryable());
                assertNull(rej.getName());
                assertNull(rej.getShortDefinition());
                assertNull(rej.getExamples());
                assertEquals(3, stub.calls(KEYWORD));

                stub.evaluator = (n, in) -> null;
                KeywordDefineDTO.Response down = define(service(true));
                assertEquals("AI_QUALITY_UNAVAILABLE", down.getErrorCode());
                assertNull(down.getShortDefinition());
                assertEquals(4, stub.calls(KEYWORD));
        }

        @Test
        void keywordGenerationFailureKeepsLegacyContractWithoutEvaluation() {
                keywordFails = true;
                KeywordDefineDTO.Response res = define(service(true));
                assertFalse(res.getSuccess());
                assertEquals("AI_TIMEOUT", res.getErrorCode());
                assertEquals(1, stub.calls(KEYWORD));
                assertEquals(0, stub.evaluations.size());
        }

        @Test
        void keywordGateOffIsLegacy() {
                KeywordDefineDTO.Response res = define(service(false));
                assertTrue(res.getSuccess());
                assertTrue(res.getShortDefinition().startsWith("정의초안1"));
                assertNull(res.getQualityStatus());
                assertNull(res.getRetryable());
                assertEquals(0, stub.evaluations.size());
        }
}
