package com.studybridge.api.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.ai.AiFailoverExecutor;
import com.studybridge.api.ai.AiUpstream;
import com.studybridge.api.ai.AiUpstreams;
import com.studybridge.api.ai.quality.AiQualityGateSettings;
import com.studybridge.api.ai.quality.AiResponseQualityGate;
import com.studybridge.api.ai.quality.GateEvidence;
import com.studybridge.api.ai.quality.QualityEvaluatorClient;
import com.studybridge.api.dto.QuizDTO;
import com.studybridge.api.entity.Material;
import com.studybridge.api.entity.MaterialQuiz;
import com.studybridge.api.entity.MaterialType;
import com.studybridge.api.repository.GroupStudyMemberRepository;
import com.studybridge.api.repository.MaterialGroupShareRepository;
import com.studybridge.api.repository.MaterialMemoRepository;
import com.studybridge.api.repository.MaterialQuestionRepository;
import com.studybridge.api.repository.MaterialQuizRepository;
import com.studybridge.api.repository.MaterialRepository;
import com.studybridge.api.repository.MaterialSummaryRepository;
import com.studybridge.api.repository.RoadmapRepository;
import com.studybridge.api.repository.RoadmapTaskRepository;
import com.studybridge.api.repository.UserRepository;
import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
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
 * 자료 퀴즈 품질 게이트(PDF_QUIZ / quiz_json): 생성(79 거절→80 승인 재생성, hardFail·전부 거절 저장 0, 평가기 503 미노출, 생성 실패 기존 계약,
 * 게이트 OFF 회귀 없음) + 저장 퀴즈 재노출(GET 목록·공유 목록·제출·점수 조회에서 미승인 퀴즈의 AI 생성 필드만 가림).
 * ai07 대역 = 로컬 HttpServer(/api/ai/quiz, /api/ai/quality/evaluate).
 */
class MaterialQuizQualityGateTest {

        static final long USER = 55L;
        static final long MATERIAL = 345L;
        static final ObjectMapper M = new ObjectMapper().findAndRegisterModules();
        static final String PDF_TEXT = "TCP 연결은 3-way handshake(SYN, SYN-ACK, ACK)로 수립한다. 연결 해제는 FIN 과 ACK 를 주고받는 4단계다. ";

        HttpServer server;
        final AtomicInteger quizCalls = new AtomicInteger();
        final List<JsonNode> quizRequests = new CopyOnWriteArrayList<>();
        final List<JsonNode> evaluations = new CopyOnWriteArrayList<>();
        volatile IntFunction<String> evaluatorPolicy = n -> out(90, "APPROVED", false);
        volatile String quizFailureCode;
        MaterialQuizRepository quizzes;
        MaterialQuizScoreService scores;
        Material material;

        @BeforeEach
        void up() throws Exception {
                server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
                server.createContext("/api/ai/quiz", ex -> {
                        int n = quizCalls.incrementAndGet();
                        quizRequests.add(M.readTree(ex.getRequestBody().readAllBytes()));
                        String body = quizFailureCode != null
                                        ? "{\"success\":false,\"errorCode\":\"" + quizFailureCode + "\",\"message\":\"m\",\"retryable\":true,\"schemaVersion\":\"quiz.v2\",\"status\":\"FAILED\",\"quizzes\":[]}"
                                        : quizBody(n);
                        respond(ex, 200, body);
                });
                server.createContext("/api/ai/quality/evaluate", ex -> {
                        JsonNode in = M.readTree(ex.getRequestBody().readAllBytes());
                        evaluations.add(in);
                        String body = evaluatorPolicy.apply(evaluations.size());
                        respond(ex, body == null ? 503 : 200, body == null ? "{}" : body.replace("RID", in.get("requestId").asText()));
                });
                server.start();
        }

        @AfterEach
        void down() {
                server.stop(0);
        }

        static void respond(com.sun.net.httpserver.HttpExchange ex, int status, String body) throws java.io.IOException {
                byte[] b = body.getBytes(StandardCharsets.UTF_8);
                ex.getResponseHeaders().add("Content-Type", "application/json");
                ex.sendResponseHeaders(status, b.length);
                ex.getResponseBody().write(b);
                ex.close();
        }

        static String quizBody(int n) {
                return "{\"success\":true,\"schemaVersion\":\"quiz.v2\",\"quizId\":\"quiz_" + n + "\",\"status\":\"OK\",\"requestedCount\":2,\"generatedCount\":2,"
                                + "\"quizzes\":["
                                + question("q" + n + "a", "초안 " + n + ": TCP 연결 수립 절차는?", "[\"3-way handshake\",\"4-way handshake\",\"slow start\",\"FIN 대기\"]", 0,
                                                "정답은 A. 원문에 따르면 TCP 연결은 3-way handshake 로 수립한다.")
                                + "," + question("q" + n + "b", "초안 " + n + ": TCP 연결 해제는 몇 단계인가?", "[\"2단계\",\"3단계\",\"4단계\",\"5단계\"]", 2,
                                                "정답은 C. 연결 해제는 FIN 과 ACK 를 주고받는 4단계다.")
                                + "],\"metadata\":{\"provider\":\"ollama\"}}";
        }

        static String question(String id, String q, String options, int correct, String expl) {
                String letter = String.valueOf((char) ('A' + correct));
                return "{\"questionId\":\"" + id + "\",\"question\":\"" + q + "\",\"questionType\":\"multiple_choice\",\"answerType\":\"SINGLE_CHOICE\","
                                + "\"options\":" + options + ",\"optionIds\":[\"A\",\"B\",\"C\",\"D\"],\"correctAnswer\":" + correct + ",\"answer\":" + correct
                                + ",\"answerIndex\":" + correct + ",\"correctOptionIds\":[\"" + letter + "\"],\"explanation\":\"" + expl + "\","
                                + "\"wrongExplanations\":[\"오답 해설 " + id + "\"],\"difficulty\":\"normal\"}";
        }

        static String out(double score, String status, boolean hardFail) {
                return "{\"schemaVersion\":\"response-quality.v1\",\"requestId\":\"RID\",\"taskType\":\"PDF_QUIZ\",\"success\":true,\"verified\":"
                                + "APPROVED".equals(status) + ",\"qualityStatus\":\"" + status + "\",\"score\":" + score
                                + ",\"minimumScore\":80,\"hardFail\":" + hardFail + ",\"violations\":"
                                + (hardFail ? "[{\"code\":\"QUIZ_ANSWER_EXPLANATION_MISMATCH\",\"severity\":\"HARD\",\"reason\":\"1번 해설의 정답 표기가 answer 와 다름\"}]" : "[]")
                                + ",\"dimensions\":[],\"evaluatorVersion\":\"stub\",\"latencyMs\":1}";
        }

        AiResponseQualityGate gate(boolean on) {
                WebClient wc = WebClient.create("http://127.0.0.1:" + server.getAddress().getPort());
                AiQualityGateSettings s = AiQualityGateSettings.forTest(on);
                return new AiResponseQualityGate(s, new QualityEvaluatorClient(wc, s, "k".repeat(64)));
        }

        /** AiIntegrationService(생성·목록) + 실제 MaterialQuizService(채점·공유 목록·점수)를 같은 게이트로 묶는다. */
        record Services(AiIntegrationService ai, MaterialQuizService quiz) { }

        Services services(boolean gateOn, List<MaterialQuiz> stored) {
                WebClient wc = WebClient.create("http://127.0.0.1:" + server.getAddress().getPort());
                MaterialRepository materials = mock(MaterialRepository.class);
                material = Material.builder().materialId(MATERIAL).userId(USER).materialType(MaterialType.PDF).title("네트워크")
                                .extractedText(PDF_TEXT.repeat(10)).build();
                when(materials.findById(MATERIAL)).thenReturn(Optional.of(material));
                MaterialSummaryRepository summaries = mock(MaterialSummaryRepository.class);
                when(summaries.findByMaterial_MaterialId(MATERIAL)).thenReturn(Optional.empty());
                quizzes = mock(MaterialQuizRepository.class);
                when(quizzes.save(any(MaterialQuiz.class))).thenAnswer(inv -> {
                        MaterialQuiz q = inv.getArgument(0);
                        q.setQuizId(77L);
                        return q;
                });
                when(quizzes.findByMaterial_MaterialIdOrderByCreatedAtDesc(MATERIAL)).thenReturn(stored);
                for (MaterialQuiz q : stored) {
                        when(quizzes.findById(q.getQuizId())).thenReturn(Optional.of(q));
                }
                scores = mock(MaterialQuizScoreService.class);
                when(scores.record(any(), any())).thenReturn(new MaterialQuizScoreService.RecordOutcome(true, 1, true, 50, false));
                MaterialGroupShareRepository shares = mock(MaterialGroupShareRepository.class);
                when(shares.findByMaterialId(anyLong())).thenReturn(List.of());
                AiResponseQualityGate g = gate(gateOn);
                MaterialQuizService quizService = new MaterialQuizService(materials, quizzes, scores, shares,
                                mock(GroupStudyMemberRepository.class), mock(UserRepository.class));
                quizService.setQualityGate(g);
                AiUpstreams ups = new AiUpstreams(List.of(new AiUpstream("primary", "http://127.0.0.1", wc)));
                AiIntegrationService ai = new AiIntegrationService(materials, summaries, quizzes, mock(MaterialMemoRepository.class),
                                mock(MaterialQuestionRepository.class), mock(RoadmapRepository.class), mock(RoadmapTaskRepository.class), wc,
                                mock(IntentRouterService.class), mock(LearningLoopService.class), quizService, new AiFailoverExecutor(ups), g, null);
                return new Services(ai, quizService);
        }

        static QuizDTO.Request req() {
                return new QuizDTO.Request("보통", 5, null);
        }

        MaterialQuiz saved() {
                ArgumentCaptor<MaterialQuiz> c = ArgumentCaptor.forClass(MaterialQuiz.class);
                verify(quizzes).save(c.capture());
                return c.getValue();
        }

        MaterialQuiz legacyQuiz() {
                String data = "[{\"questionId\":\"lq1\",\"question\":\"레거시 미검증 문항\",\"options\":[\"레거시 보기1\",\"레거시 보기2\",\"레거시 보기3\",\"레거시 보기4\"],"
                                + "\"optionIds\":[\"A\",\"B\",\"C\",\"D\"],\"correctAnswer\":1,\"explanation\":\"레거시 미검증 해설\"}]";
                return MaterialQuiz.builder().quizId(70L).material(material).difficulty("보통").questionCount(1).quizData(data).build();
        }

        /** 게이트 승인 생성 → 저장본(quality_status=APPROVED). 재노출 증거 테스트가 평가기 경유 승인본을 쓰도록 한다. */
        MaterialQuiz generateApproved() {
                evaluatorPolicy = n -> out(80, "APPROVED", false);
                QuizDTO.Response r = services(true, List.of()).ai().generateQuiz(USER, MATERIAL, req());
                assertEquals(Boolean.TRUE, r.getSuccess(), String.valueOf(r.getErrorCode()));
                MaterialQuiz q = saved();
                assertEquals("APPROVED", q.getQualityStatus());
                assertEquals(1, evaluations.size(), "승인본은 평가기를 거쳐 저장된다");
                return q;
        }

        static String json(Object o) throws Exception {
                return M.writeValueAsString(o);
        }

        // ───────────────────────── 생성 POST /api/materials/{materialId}/quiz ─────────────────────────

        @GateEvidence({"POST /api/materials/{materialId}/quiz"})
        @Test
        void rejected79ThenApproved80SavesOnlyTheApprovedDraftAndSendsAllVisibleQuizFields() throws Exception {
                evaluatorPolicy = n -> n == 1 ? out(79, "REJECTED", false) : out(80, "APPROVED", false);
                QuizDTO.Response r = services(true, List.of()).ai().generateQuiz(USER, MATERIAL, req());
                assertEquals(Boolean.TRUE, r.getSuccess());
                assertEquals("APPROVED", r.getQualityStatus());
                assertEquals(80.0, r.getQualityScore());
                assertEquals(Boolean.TRUE, r.getVerified());
                assertEquals(2, quizCalls.get(), "79 거절 → 재생성 1회");
                assertTrue(json(r).contains("초안 2") && !json(r).contains("초안 1"), "승인된 두 번째 초안만 응답");
                MaterialQuiz q = saved();
                assertEquals("APPROVED", q.getQualityStatus());
                assertEquals(80.0, q.getQualityScore());
                assertTrue(q.getQuizData().contains("초안 2") && !q.getQuizData().contains("초안 1"), "거절 초안은 저장 0");

                JsonNode ev = evaluations.get(0);
                assertEquals("PDF_QUIZ", ev.get("taskType").asText());
                assertEquals("quiz_json", ev.get("outputKind").asText());
                JsonNode q0 = ev.get("proposedOutput").get("questions").get(0);
                assertTrue(q0.get("question").asText().contains("초안 1"));
                assertEquals(4, q0.get("options").size());
                assertEquals(0, q0.get("answerIndex").asInt(), "정답은 0-based answerIndex");
                assertTrue(q0.get("explanation").asText().startsWith("정답은 A"), "해설 포함(정답-해설 불일치 HARD 검사 대상)");
                assertEquals("오답 해설 q1a", q0.get("wrongExplanations").get(0).asText());
                assertEquals(2, ev.get("proposedOutput").get("questions").get(1).get("answerIndex").asInt());
                assertTrue(ev.get("groundingEvidence").size() > 0, "자료 원문 근거 동봉");
                assertEquals(MATERIAL, ev.get("groundingEvidence").get(0).get("materialId").asLong());
                assertEquals("PDF_ORIGINAL", ev.get("groundingEvidence").get(0).get("sourceType").asText());
                assertTrue(ev.get("groundingEvidence").get(0).get("text").asText().contains("3-way handshake"));
                assertEquals(MATERIAL, ev.get("constraints").get("allowedMaterialIds").get(0).asLong());
                assertEquals(5, ev.get("constraints").get("expectedQuestionCount").asInt());
                assertEquals(4, ev.get("constraints").get("expectedOptionCount").asInt());
                assertFalse(quizRequests.get(0).has("regenerationAttempt"), "최초 요청 payload 는 기존과 같다");
                assertEquals(1, quizRequests.get(1).get("regenerationAttempt").asInt());
                assertEquals(80.0, saved().getQualityScore());
        }

        @GateEvidence({"POST /api/materials/{materialId}/quiz"})
        @Test
        void hardFailAndRepeatedRejectionSaveNothingAndReturnExplicitFailure() throws Exception {
                evaluatorPolicy = n -> out(95, "REJECTED", true); // 점수가 높아도 정답-해설 불일치(HARD)는 거절
                QuizDTO.Response r = services(true, List.of()).ai().generateQuiz(USER, MATERIAL, req());
                assertEquals(Boolean.FALSE, r.getSuccess());
                assertEquals("AI_QUALITY_REJECTED", r.getErrorCode());
                assertEquals(Boolean.TRUE, r.getRetryable());
                assertEquals("REJECTED", r.getQualityStatus());
                assertEquals(Boolean.FALSE, r.getVerified());
                assertTrue(r.getQuestions().isEmpty());
                assertFalse(json(r).contains("초안"), "거절 초안 본문은 응답에 0");
                assertEquals(3, quizCalls.get(), "최초 1 + 재생성 2");
                verify(quizzes, never()).save(any());
        }

        @Test
        void evaluatorDownIsUnavailableWithoutRegeneration() throws Exception {
                evaluatorPolicy = n -> null; // 503
                QuizDTO.Response r = services(true, List.of()).ai().generateQuiz(USER, MATERIAL, req());
                assertEquals(Boolean.FALSE, r.getSuccess());
                assertEquals("AI_QUALITY_UNAVAILABLE", r.getErrorCode());
                assertEquals(Boolean.TRUE, r.getRetryable());
                assertFalse(json(r).contains("초안"));
                assertEquals(1, quizCalls.get(), "평가기 장애면 재생성하지 않는다");
                verify(quizzes, never()).save(any());
        }

        @Test
        void generationFailureKeepsLegacyContractAndSkipsEvaluation() {
                quizFailureCode = "PDF_TEXT_INSUFFICIENT";
                QuizDTO.Response r = services(true, List.of()).ai().generateQuiz(USER, MATERIAL, req());
                assertEquals("PDF_TEXT_INSUFFICIENT", r.getErrorCode());
                assertEquals(1, quizCalls.get());
                assertEquals(0, evaluations.size(), "생성 실패면 평가하지 않는다");
                verify(quizzes, never()).save(any());
        }

        @Test
        void gateOffIsLegacyBehaviour() throws Exception {
                QuizDTO.Response r = services(false, List.of()).ai().generateQuiz(USER, MATERIAL, req());
                assertEquals(Boolean.TRUE, r.getSuccess());
                assertEquals(0, evaluations.size(), "게이트 OFF: 평가기 호출 0");
                assertNull(saved().getQualityStatus());
                String body = json(r);
                assertFalse(body.contains("qualityStatus") || body.contains("qualityRedacted") || body.contains("verified"),
                                "게이트 OFF 응답 JSON 형태는 기존과 같다");
                assertFalse(quizRequests.get(0).has("regenerationAttempt"));

                MaterialQuiz legacy = legacyQuiz();
                List<QuizDTO.Response> list = services(false, List.of(legacy)).ai().getQuizzes(USER, MATERIAL);
                assertEquals("레거시 미검증 문항", list.get(0).getQuestions().get(0).getQuestion(), "OFF 에선 기존 저장본 그대로");
                assertFalse(json(list).contains("qualityRedacted"));
                QuizDTO.ResultResponse res = services(false, List.of(legacy)).quiz().submit(USER, MATERIAL, 70L, answer("lq1", "B"));
                assertEquals("레거시 미검증 해설", res.getResults().get(0).getExplanation());
                assertNull(res.getQualityRedacted());
        }

        // ───────────────────────── 재노출 GET 목록 / 공유 목록 / 제출 / 점수 ─────────────────────────

        @GateEvidence({"GET /api/materials/{materialId}/quiz"})
        @Test
        void listRedactsUnverifiedStoredQuizButShowsApprovedOne() throws Exception {
                MaterialQuiz approved = generateApproved();
                MaterialQuiz legacy = legacyQuiz();
                evaluations.clear();
                quizCalls.set(0);
                List<QuizDTO.Response> list = services(true, List.of(legacy, approved)).ai().getQuizzes(USER, MATERIAL);
                assertEquals(0, quizCalls.get() + evaluations.size(), "재노출은 AI·평가기 호출 0");
                QuizDTO.Response hidden = list.get(0);
                assertEquals(Boolean.TRUE, hidden.getQualityRedacted());
                assertEquals(Boolean.FALSE, hidden.getVerified());
                assertEquals(MaterialQuizService.REDACTED_QUESTION, hidden.getQuestions().get(0).getQuestion());
                assertEquals("lq1", hidden.getQuestions().get(0).getQuestionId(), "식별자는 유지");
                assertEquals("B", hidden.getQuestions().get(0).getOptions().get(1).getOptionId());
                assertTrue(hidden.getQuestions().get(0).getOptions().stream()
                                .allMatch(o -> MaterialQuizService.REDACTED_OPTION.equals(o.getText())));
                assertFalse(json(hidden).contains("레거시"), "미검증 저장본의 AI 본문은 응답에 0");
                QuizDTO.Response shown = list.get(1);
                assertEquals("APPROVED", shown.getQualityStatus());
                assertNull(shown.getQualityRedacted());
                assertTrue(shown.getQuestions().get(0).getQuestion().contains("TCP 연결 수립"));
        }

        @GateEvidence({"GET /api/materials/{materialId}/shared-quizzes"})
        @Test
        void sharedListRedactsUnverifiedStoredQuizButShowsApprovedOne() throws Exception {
                MaterialQuiz approved = generateApproved();
                MaterialQuiz legacy = legacyQuiz();
                List<QuizDTO.SharedQuiz> list = services(true, List.of(legacy, approved)).quiz().sharedQuizzes(USER, MATERIAL);
                assertEquals(Boolean.TRUE, list.get(0).getQualityRedacted());
                assertEquals(MaterialQuizService.REDACTED_QUESTION, list.get(0).getQuestions().get(0).getQuestion());
                assertFalse(json(list.get(0)).contains("레거시"));
                assertEquals("APPROVED", list.get(1).getQualityStatus());
                assertEquals(Boolean.TRUE, list.get(1).getVerified());
                assertTrue(list.get(1).getQuestions().get(0).getQuestion().contains("TCP 연결 수립"));
        }

        static QuizDTO.SubmitRequest answer(String questionId, String optionId) {
                QuizDTO.SubmitRequest r = new QuizDTO.SubmitRequest();
                r.setAnswers(List.of(QuizDTO.SubmittedAnswer.builder().questionId(questionId).selectedOptionId(optionId).build()));
                return r;
        }

        @GateEvidence({"POST /api/materials/{materialId}/quiz/{quizId}/submit"})
        @Test
        void submitGradesDeterministicallyButHidesUnverifiedExplanationOnly() throws Exception {
                MaterialQuiz approved = generateApproved();
                MaterialQuiz legacy = legacyQuiz();
                Services s = services(true, List.of(legacy, approved));
                QuizDTO.ResultResponse hidden = s.quiz().submit(USER, MATERIAL, 70L, answer("lq1", "B"));
                assertEquals(100, hidden.getScore(), "채점(보기 id 비교)은 그대로");
                assertEquals(List.of("B"), hidden.getResults().get(0).getCorrectOptionIds());
                assertEquals(MaterialQuizService.REDACTED_EXPLANATION, hidden.getResults().get(0).getExplanation());
                assertEquals(Boolean.TRUE, hidden.getQualityRedacted());
                assertFalse(json(hidden).contains("레거시"), "미검증 해설 본문 0");
                verify(scores).record(any(), any()); // 사용자 점수 기록은 유지

                QuizDTO.ResultResponse shown = s.quiz().submit(USER, MATERIAL, 77L, answer("q1a", "A"));
                assertTrue(shown.getResults().get(0).getExplanation().startsWith("정답은 A"), "승인 퀴즈 해설은 노출");
                assertNull(shown.getQualityRedacted());
        }

        @GateEvidence({"GET /api/materials/{materialId}/quiz/{quizId}/score"})
        @Test
        void latestScoreHidesUnverifiedExplanationButKeepsScore() throws Exception {
                MaterialQuiz approved = generateApproved();
                MaterialQuiz legacy = legacyQuiz();
                Services s = services(true, List.of(legacy, approved));
                when(scores.find(70L, USER)).thenReturn(MaterialQuizScoreService.StoredScore.builder().quizId(70L).userId(USER).score(100)
                                .attempt(1).selected(new java.util.LinkedHashMap<>(Map.of("lq1", "B"))).build());
                when(scores.find(77L, USER)).thenReturn(MaterialQuizScoreService.StoredScore.builder().quizId(77L).userId(USER).score(50)
                                .attempt(1).selected(new java.util.LinkedHashMap<>(Map.of("q1a", "A"))).build());
                QuizDTO.ResultResponse hidden = s.quiz().latestResult(USER, MATERIAL, 70L);
                assertEquals(100, hidden.getScore());
                assertEquals(MaterialQuizService.REDACTED_EXPLANATION, hidden.getResults().get(0).getExplanation());
                assertEquals(Boolean.TRUE, hidden.getQualityRedacted());
                assertFalse(json(hidden).contains("레거시"));
                QuizDTO.ResultResponse shown = s.quiz().latestResult(USER, MATERIAL, 77L);
                assertTrue(shown.getResults().get(0).getExplanation().startsWith("정답은 A"));
                // 목록 응답의 lastResult 도 같은 규칙(해설만 가림)
                QuizDTO.Response listed = s.ai().getQuizzes(USER, MATERIAL).get(0);
                assertEquals(MaterialQuizService.REDACTED_EXPLANATION, listed.getLastResult().getResults().get(0).getExplanation());
        }
}
