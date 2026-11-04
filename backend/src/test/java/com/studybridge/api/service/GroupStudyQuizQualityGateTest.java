package com.studybridge.api.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
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
import com.studybridge.api.dto.GroupStudyMaterialDTO;
import com.studybridge.api.dto.GroupStudyQuizDTO;
import com.studybridge.api.dto.GroupStudySocketDTO;
import com.studybridge.api.entity.GroupStudy;
import com.studybridge.api.entity.GroupStudyMaterial;
import com.studybridge.api.entity.GroupStudyMemberStatus;
import com.studybridge.api.entity.GroupStudyQuiz;
import com.studybridge.api.entity.GroupStudyQuizQuestion;
import com.studybridge.api.entity.GroupStudyQuizSession;
import com.studybridge.api.entity.GroupStudyQuizSessionStatus;
import com.studybridge.api.entity.User;
import com.studybridge.api.exception.AiUpstreamException;
import com.studybridge.api.repository.GroupStudyMaterialRepository;
import com.studybridge.api.repository.GroupStudyMemberRepository;
import com.studybridge.api.repository.GroupStudyQuizQuestionRepository;
import com.studybridge.api.repository.GroupStudyQuizRepository;
import com.studybridge.api.repository.GroupStudyQuizSessionAnswerRepository;
import com.studybridge.api.repository.GroupStudyQuizSessionRepository;
import com.studybridge.api.repository.GroupStudyRepository;
import com.studybridge.api.repository.UserRepository;
import com.sun.net.httpserver.HttpServer;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import java.util.function.IntFunction;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.scheduling.concurrent.ThreadPoolTaskScheduler;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.web.reactive.function.client.WebClient;

/**
 * 그룹 퀴즈 품질 게이트(PDF_QUIZ / quiz_json): 자료 기반 생성·업로드+생성(79→80 재생성 승인, hardFail/503 저장 0·명시 실패, 업로드 거절 시
 * S3 정리), 원본 파일에서 결정적으로 뽑은 원문 근거(한글 PDF), 저장 퀴즈 목록·세션 스냅샷의 미승인 AI 필드 가림, 게이트 OFF 회귀 없음.
 */
class GroupStudyQuizQualityGateTest {

        static final long USER = 9L;
        static final long GROUP = 31L;
        static final long GM = 501L;
        static final ObjectMapper M = new ObjectMapper().findAndRegisterModules();
        static final String SOURCE = "트랜잭션 격리 수준 READ COMMITTED 는 커밋된 데이터만 읽는다. 팬텀 읽기는 SERIALIZABLE 에서 막힌다.";

        HttpServer server;
        final AtomicInteger aiCalls = new AtomicInteger();
        final List<JsonNode> aiRequests = new CopyOnWriteArrayList<>();
        final List<JsonNode> evaluations = new CopyOnWriteArrayList<>();
        volatile IntFunction<String> evaluatorPolicy = n -> out(90, "APPROVED", false);
        volatile boolean aiFails;
        GroupStudyQuizRepository quizzes;
        GroupStudyQuizQuestionRepository questions;
        GroupStudyMaterialRepository materials;
        S3Service s3;
        final List<GroupStudyQuizQuestion> savedQuestions = new CopyOnWriteArrayList<>();
        GroupStudy group;
        User user;

        @BeforeEach
        void up() throws Exception {
                server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
                server.createContext("/api/ai/quiz/generate", ex -> {
                        int n = aiCalls.incrementAndGet();
                        aiRequests.add(M.readTree(ex.getRequestBody().readAllBytes()));
                        String body = aiFails ? "{\"success\":false,\"errorCode\":\"PDF_TEXT_EMPTY\",\"message\":\"m\",\"questions\":[]}"
                                        : "{\"success\":true,\"status\":\"OK\",\"quizTitle\":\"초안 " + n + " 트랜잭션 퀴즈\",\"questions\":["
                                                        + "{\"question\":\"초안 " + n + ": 커밋된 데이터만 읽는 격리 수준은?\",\"options\":[\"READ UNCOMMITTED\",\"READ COMMITTED\",\"REPEATABLE READ\",\"SERIALIZABLE\"],"
                                                        + "\"correctAnswer\":1,\"explanation\":\"정답은 2번 READ COMMITTED 다.\"},"
                                                        + "{\"question\":\"정답 키 없는 문항\",\"options\":[\"a\",\"b\"]}]}";
                        MaterialQuizQualityGateTest.respond(ex, 200, body);
                });
                server.createContext("/api/ai/quality/evaluate", ex -> {
                        JsonNode in = M.readTree(ex.getRequestBody().readAllBytes());
                        evaluations.add(in);
                        String body = evaluatorPolicy.apply(evaluations.size());
                        MaterialQuizQualityGateTest.respond(ex, body == null ? 503 : 200,
                                        body == null ? "{}" : body.replace("RID", in.get("requestId").asText()));
                });
                server.start();
                group = GroupStudy.builder().id(GROUP).title("DB 스터디").build();
                user = User.builder().id(USER).displayName("민수").build();
        }

        @AfterEach
        void down() {
                server.stop(0);
        }

        static String out(double score, String status, boolean hardFail) {
                return MaterialQuizQualityGateTest.out(score, status, hardFail);
        }

        /** 원문이 든 한글 PDF(OpenPDF + NanumGothic, Identity-H). 근거 추출이 실제 PDF 바이트에서 동작하는지 본다. */
        static byte[] koreanPdf(String text) throws Exception {
                byte[] font;
                try (InputStream is = GroupStudyQuizQualityGateTest.class.getResourceAsStream("/fonts/NanumGothic.ttf")) {
                        font = is.readAllBytes();
                }
                ByteArrayOutputStream out = new ByteArrayOutputStream();
                com.lowagie.text.Document doc = new com.lowagie.text.Document();
                com.lowagie.text.pdf.PdfWriter.getInstance(doc, out);
                doc.open();
                com.lowagie.text.pdf.BaseFont base = com.lowagie.text.pdf.BaseFont.createFont("NanumGothic.ttf",
                                com.lowagie.text.pdf.BaseFont.IDENTITY_H, com.lowagie.text.pdf.BaseFont.EMBEDDED, true, font, null);
                doc.add(new com.lowagie.text.Paragraph(text, new com.lowagie.text.Font(base, 11)));
                doc.close();
                return out.toByteArray();
        }

        AiResponseQualityGate gate(boolean on) {
                WebClient wc = WebClient.create("http://127.0.0.1:" + server.getAddress().getPort());
                AiQualityGateSettings s = AiQualityGateSettings.forTest(on);
                return new AiResponseQualityGate(s, new QualityEvaluatorClient(wc, s, "k".repeat(64)));
        }

        GroupStudyMaterialService service(boolean gateOn, List<GroupStudyQuiz> stored) throws Exception {
                WebClient wc = WebClient.create("http://127.0.0.1:" + server.getAddress().getPort());
                GroupStudyMemberRepository members = mock(GroupStudyMemberRepository.class);
                when(members.existsByGroupStudyIdAndUserIdAndStatus(GROUP, USER, GroupStudyMemberStatus.JOINED)).thenReturn(true);
                UserRepository users = mock(UserRepository.class);
                when(users.findById(USER)).thenReturn(Optional.of(user));
                GroupStudyRepository groups = mock(GroupStudyRepository.class);
                when(groups.findById(GROUP)).thenReturn(Optional.of(group));
                materials = mock(GroupStudyMaterialRepository.class);
                GroupStudyMaterial gm = GroupStudyMaterial.builder().id(GM).groupStudy(group).uploader(user).title("트랜잭션")
                                .s3Key("materials/user_9/x/tx.pdf").fileSize(10L).originalFileName("tx.pdf").contentType("application/pdf").build();
                when(materials.findById(GM)).thenReturn(Optional.of(gm));
                when(materials.save(any(GroupStudyMaterial.class))).thenAnswer(inv -> {
                        GroupStudyMaterial m = inv.getArgument(0);
                        m.setId(GM);
                        return m;
                });
                quizzes = mock(GroupStudyQuizRepository.class);
                AtomicLong ids = new AtomicLong(800);
                when(quizzes.save(any(GroupStudyQuiz.class))).thenAnswer(inv -> {
                        GroupStudyQuiz q = inv.getArgument(0);
                        q.setId(ids.incrementAndGet());
                        return q;
                });
                when(quizzes.findByGroupStudyIdOrderByCreatedAtDesc(GROUP)).thenReturn(stored);
                questions = mock(GroupStudyQuizQuestionRepository.class);
                savedQuestions.clear();
                when(questions.save(any(GroupStudyQuizQuestion.class))).thenAnswer(inv -> {
                        savedQuestions.add(inv.getArgument(0));
                        return inv.getArgument(0);
                });
                s3 = mock(S3Service.class);
                when(s3.downloadBytes("materials/user_9/x/tx.pdf")).thenReturn(koreanPdf(SOURCE));
                when(s3.uploadFile(any(), eq(USER))).thenReturn("materials/user_9/y/upload.pdf");
                AiUpstreams ups = new AiUpstreams(List.of(new AiUpstream("primary", "http://127.0.0.1", wc)));
                GroupStudyMaterialService svc = new GroupStudyMaterialService(materials, groups, members, quizzes, questions,
                                mock(GroupStudyQuizSessionRepository.class), mock(GroupStudyQuizSessionAnswerRepository.class), users, s3,
                                new AiFailoverExecutor(ups), new ObjectMapper());
                svc.setQualityGate(gate(gateOn));
                return svc;
        }

        GroupStudyQuiz savedQuiz() {
                ArgumentCaptor<GroupStudyQuiz> c = ArgumentCaptor.forClass(GroupStudyQuiz.class);
                verify(quizzes).save(c.capture());
                return c.getValue();
        }

        GroupStudyQuiz legacyQuiz() {
                return GroupStudyQuiz.builder().id(700L).groupStudy(group).creator(user).title("레거시 미검증 퀴즈 제목")
                                .questions(new ArrayList<>(List.of(new GroupStudyQuizQuestion()))).build();
        }

        static MockMultipartFile upload(byte[] pdf) {
                return new MockMultipartFile("file", "upload.pdf", "application/pdf", pdf);
        }

        // ───────────────────────── 생성 ─────────────────────────

        @GateEvidence({"POST /api/groups/{groupId}/materials/{materialId}/quiz"})
        @Test
        void regenerate79Then80PersistsOnlyApprovedDraftWithPdfEvidence() throws Exception {
                evaluatorPolicy = n -> n == 1 ? out(79, "REJECTED", false) : out(80, "APPROVED", false);
                GroupStudyQuizDTO.QuizResponse r = service(true, List.of()).generateQuizForMaterial(USER, GROUP, GM, 5, 20);
                assertEquals("APPROVED", r.getQualityStatus());
                assertEquals(80.0, r.getQualityScore());
                assertEquals("초안 2 트랜잭션 퀴즈", r.getTitle());
                assertEquals(2, aiCalls.get());
                GroupStudyQuiz q = savedQuiz();
                assertEquals("APPROVED", q.getQualityStatus());
                assertEquals(1, savedQuestions.size(), "평가한 채점 가능 문항만 저장");
                assertTrue(savedQuestions.get(0).getQuestion().startsWith("초안 2"), "거절 초안 저장 0");
                assertEquals(1, savedQuestions.get(0).getCorrectAnswer());

                JsonNode ev = evaluations.get(0);
                assertEquals("PDF_QUIZ", ev.get("taskType").asText());
                assertEquals("quiz_json", ev.get("outputKind").asText());
                JsonNode po = ev.get("proposedOutput");
                assertEquals("초안 1 트랜잭션 퀴즈", po.get("title").asText(), "AI 생성 제목도 평가 대상");
                assertEquals(1, po.get("questions").size(), "저장될 문항과 평가 문항이 같다(정답 키 없는 문항 제외)");
                assertEquals(1, po.get("questions").get(0).get("answerIndex").asInt());
                assertEquals("정답은 2번 READ COMMITTED 다.", po.get("questions").get(0).get("explanation").asText());
                JsonNode g0 = ev.get("groundingEvidence").get(0);
                assertEquals("group-material-" + GM, g0.get("documentId").asText());
                assertTrue(g0.get("materialId") == null || g0.get("materialId").isNull(), "개인 자료 id 공간과 섞지 않는다");
                assertTrue(g0.get("text").asText().contains("READ COMMITTED"), "S3 원본 PDF 에서 추출한 원문: " + g0.get("text").asText());
                assertTrue(g0.get("text").asText().contains("커밋된 데이터만"), "한글 원문 추출");
                assertEquals("group-material-" + GM, ev.get("constraints").get("allowedDocumentIds").get(0).asText());
                assertEquals(5, ev.get("constraints").get("expectedQuestionCount").asInt());
                assertFalse(aiRequests.get(0).has("regenerationAttempt"), "최초 payload 는 기존과 같다");
                assertEquals(1, aiRequests.get(1).get("regenerationAttempt").asInt());
                assertEquals(5, aiRequests.get(1).get("numQuestions").asInt(), "재생성도 같은 요청(문항 수·자료)");
        }

        @GateEvidence({"POST /api/groups/{groupId}/materials/{materialId}/quiz"})
        @Test
        void regenerateHardFailOrEvaluatorDownSavesNothingAndFailsExplicitly() throws Exception {
                evaluatorPolicy = n -> out(96, "REJECTED", true);
                GroupStudyMaterialService svc = service(true, List.of());
                AiUpstreamException e = assertThrows(AiUpstreamException.class, () -> svc.generateQuizForMaterial(USER, GROUP, GM, 5, 20));
                assertEquals("AI_QUALITY_REJECTED", e.getCode());
                assertEquals(422, e.getStatus().value());
                assertTrue(e.isRetryable());
                assertEquals(3, aiCalls.get(), "최초 1 + 재생성 2");
                verify(quizzes, never()).save(any());
                verify(questions, never()).save(any());

                aiCalls.set(0);
                evaluatorPolicy = n -> null; // 503
                GroupStudyMaterialService svc2 = service(true, List.of());
                AiUpstreamException u = assertThrows(AiUpstreamException.class, () -> svc2.generateQuizForMaterial(USER, GROUP, GM, 5, 20));
                assertEquals("AI_QUALITY_UNAVAILABLE", u.getCode());
                assertEquals(503, u.getStatus().value());
                assertEquals(1, aiCalls.get(), "평가기 장애면 재생성하지 않는다");
                verify(quizzes, never()).save(any());
        }

        @Test
        void generationFailureKeepsLegacyContract() throws Exception {
                aiFails = true;
                IllegalStateException e = assertThrows(IllegalStateException.class,
                                () -> service(true, List.of()).generateQuizForMaterial(USER, GROUP, GM, 5, 20));
                assertTrue(e.getMessage().contains("퀴즈 생성에 실패"));
                assertEquals(1, aiCalls.get());
                assertEquals(0, evaluations.size(), "생성 실패면 평가하지 않는다");
        }

        @GateEvidence({"POST /api/groups/{groupId}/materials/upload-quiz"})
        @Test
        void uploadQuizRejectedFailsExplicitlyAndRemovesUploadApprovedPersists() throws Exception {
                byte[] pdf = koreanPdf(SOURCE);
                evaluatorPolicy = n -> out(70, "REJECTED", false);
                GroupStudyMaterialService svc = service(true, List.of());
                AiUpstreamException e = assertThrows(AiUpstreamException.class,
                                () -> svc.uploadMaterialAndGenerateQuiz(USER, GROUP, "트랜잭션", upload(pdf), 5, 20));
                assertEquals("AI_QUALITY_REJECTED", e.getCode());
                assertTrue(e.isRetryable());
                verify(quizzes, never()).save(any());
                verify(s3).deleteFile("materials/user_9/y/upload.pdf"); // 성공 위장 없음 + 고아 객체 정리(트랜잭션 밖 = 즉시)
                assertTrue(evaluations.get(0).get("groundingEvidence").get(0).get("text").asText().contains("READ COMMITTED"),
                                "업로드 본문에서 추출한 원문 근거");

                evaluations.clear();
                aiCalls.set(0);
                evaluatorPolicy = n -> out(80, "APPROVED", false);
                GroupStudyMaterialService ok = service(true, List.of());
                GroupStudyMaterialDTO dto = ok.uploadMaterialAndGenerateQuiz(USER, GROUP, "트랜잭션", upload(pdf), 5, 20);
                assertEquals(GM, dto.getId());
                assertEquals(1, evaluations.size(), "승인 경로도 평가기를 거친다");
                assertEquals("APPROVED", savedQuiz().getQualityStatus());
                assertTrue(savedQuestions.get(0).getQuestion().startsWith("초안 1"));
                verify(s3, never()).deleteFile(any());
        }

        @Test
        void gateOffIsLegacyBehaviour() throws Exception {
                GroupStudyQuizDTO.QuizResponse r = service(false, List.of()).generateQuizForMaterial(USER, GROUP, GM, 5, 20);
                assertNotNull(r.getId());
                assertNull(r.getQualityStatus());
                assertEquals(0, evaluations.size(), "게이트 OFF: 평가기 호출 0");
                verify(s3, never()).downloadBytes(any()); // 근거 추출도 하지 않는다
                assertNull(savedQuiz().getQualityStatus());
                assertFalse(aiRequests.get(0).has("regenerationAttempt") || aiRequests.get(0).has("regenerationHints"));
                String body = M.writeValueAsString(r);
                assertFalse(body.contains("qualityStatus") || body.contains("qualityRedacted"), "응답 JSON 형태는 기존과 같다");

                List<GroupStudyQuizDTO.QuizResponse> list = service(false, List.of(legacyQuiz())).getGroupQuizzes(USER, GROUP);
                assertEquals("레거시 미검증 퀴즈 제목", list.get(0).getTitle());
                assertNull(list.get(0).getQualityRedacted());
        }

        @Test
        void sourceTextExtractorHandlesPdfTxtAndGarbage() throws Exception {
                assertTrue(GroupStudyQuizSourceText.extract(koreanPdf(SOURCE), "application/pdf", "a.pdf", 48000).contains("SERIALIZABLE"));
                assertEquals("가나다", GroupStudyQuizSourceText.extract("가나다".getBytes(StandardCharsets.UTF_8), "text/plain", "a.txt", 100));
                assertEquals("", GroupStudyQuizSourceText.extract("%PDF-1.4 broken".getBytes(StandardCharsets.US_ASCII), "application/pdf", "a.pdf", 100));
                assertEquals("", GroupStudyQuizSourceText.extract(null, null, null, 100));
                assertEquals(10, GroupStudyQuizSourceText.extract("0123456789abcdef".getBytes(StandardCharsets.UTF_8), "text/plain", "a.txt", 10).length());
                assertTrue(GroupStudyQuizSourceText.evidence("d", "", 10, 100).isEmpty());
                assertEquals(3, GroupStudyQuizSourceText.evidence("d", "x".repeat(25), 10, 100).size());
        }

        // ───────────────────────── 재노출 ─────────────────────────

        @GateEvidence({"GET /api/groups/{groupId}/quizzes"})
        @Test
        void quizListRedactsUnverifiedTitleButShowsApprovedOne() throws Exception {
                evaluatorPolicy = n -> out(80, "APPROVED", false);
                service(true, List.of()).generateQuizForMaterial(USER, GROUP, GM, 5, 20);
                GroupStudyQuiz approved = savedQuiz();
                assertEquals(1, evaluations.size());
                List<GroupStudyQuizDTO.QuizResponse> list = service(true, List.of(legacyQuiz(), approved)).getGroupQuizzes(USER, GROUP);
                GroupStudyQuizDTO.QuizResponse hidden = list.get(0);
                assertEquals(GroupStudyMaterialService.REDACTED_QUIZ_TITLE, hidden.getTitle());
                assertEquals(Boolean.TRUE, hidden.getQualityRedacted());
                assertEquals(700L, hidden.getId(), "식별자 유지");
                assertFalse(M.writeValueAsString(hidden).contains("레거시"), "미검증 AI 제목 0");
                GroupStudyQuizDTO.QuizResponse shown = list.get(1);
                assertEquals("초안 1 트랜잭션 퀴즈", shown.getTitle());
                assertEquals("APPROVED", shown.getQualityStatus());
                assertNull(shown.getQualityRedacted());
        }

        GroupStudyQuizSessionService sessionService(boolean gateOn, GroupStudyQuiz quiz) {
                GroupStudyMemberRepository members = mock(GroupStudyMemberRepository.class);
                when(members.existsByGroupStudyIdAndUserIdAndStatus(GROUP, USER, GroupStudyMemberStatus.JOINED)).thenReturn(true);
                when(members.findByGroupStudyIdAndStatus(GROUP, GroupStudyMemberStatus.JOINED)).thenReturn(List.of());
                GroupStudyQuizQuestion question = GroupStudyQuizQuestion.builder().id(901L).quiz(quiz)
                                .question(quiz.getTitle() + " 문항 본문").optionsJson("[\"보기 가\",\"보기 나\"]").correctAnswer(1).build();
                GroupStudyQuizQuestionRepository qs = mock(GroupStudyQuizQuestionRepository.class);
                when(qs.findById(901L)).thenReturn(Optional.of(question));
                GroupStudyQuizSession session = GroupStudyQuizSession.builder().id(61L).groupStudy(group).quiz(quiz)
                                .quizTitleSnapshot(quiz.getTitle()).status(GroupStudyQuizSessionStatus.QUESTION).currentQuestionIndex(0)
                                .questionOrderJson("[901]").currentQuestionId(901L).questionStartedAt(LocalDateTime.now())
                                .questionEndsAt(LocalDateTime.now().plusSeconds(30)).build();
                GroupStudyQuizSessionRepository sessions = mock(GroupStudyQuizSessionRepository.class);
                when(sessions.findTopByGroupStudyIdAndStatusInOrderByCreatedAtDesc(eq(GROUP), any())).thenReturn(Optional.of(session));
                GroupStudyQuizSessionAnswerRepository answers = mock(GroupStudyQuizSessionAnswerRepository.class);
                when(answers.findBySessionIdAndUserIdAndQuestionId(anyLong(), anyLong(), anyLong())).thenReturn(Optional.empty());
                when(answers.findBySessionIdAndQuestionIdOrderBySubmittedAtAsc(anyLong(), anyLong())).thenReturn(List.of());
                GroupRankingService ranking = mock(GroupRankingService.class);
                when(ranking.getPointsMap(GROUP)).thenReturn(java.util.Map.of());
                GroupStudyQuizSessionService svc = new GroupStudyQuizSessionService(members, mock(GroupStudyQuizRepository.class), qs, sessions,
                                answers, ranking, mock(SimpMessagingTemplate.class), mock(ThreadPoolTaskScheduler.class), new ObjectMapper(),
                                mock(PlatformTransactionManager.class));
                svc.setQualityGate(gate(gateOn));
                return svc;
        }

        @GateEvidence({"GET /api/groups/{groupId}/quiz/session"})
        @Test
        void sessionSnapshotRedactsUnverifiedQuizButShowsApprovedOne() throws Exception {
                evaluatorPolicy = n -> out(80, "APPROVED", false);
                service(true, List.of()).generateQuizForMaterial(USER, GROUP, GM, 5, 20);
                GroupStudyQuiz approved = savedQuiz();
                assertEquals(1, evaluations.size());

                GroupStudySocketDTO.QuizSessionPayload hidden = sessionService(true, legacyQuiz()).getCurrentSession(GROUP, USER);
                assertEquals(Boolean.TRUE, hidden.getQualityRedacted());
                assertEquals(GroupStudyQuizSessionService.REDACTED_QUIZ_TITLE, hidden.getQuizTitle());
                assertEquals(GroupStudyQuizSessionService.REDACTED_QUESTION, hidden.getQuestionText());
                assertEquals(List.of(GroupStudyQuizSessionService.REDACTED_OPTION, GroupStudyQuizSessionService.REDACTED_OPTION), hidden.getOptions());
                assertEquals(901L, hidden.getQuestionId(), "진행 상태·식별자 유지");
                assertFalse(M.writeValueAsString(hidden).contains("레거시") || M.writeValueAsString(hidden).contains("보기 가"));

                GroupStudySocketDTO.QuizSessionPayload shown = sessionService(true, approved).getCurrentSession(GROUP, USER);
                assertNull(shown.getQualityRedacted());
                assertEquals("초안 1 트랜잭션 퀴즈", shown.getQuizTitle());
                assertEquals(List.of("보기 가", "보기 나"), shown.getOptions());

                GroupStudySocketDTO.QuizSessionPayload off = sessionService(false, legacyQuiz()).getCurrentSession(GROUP, USER);
                assertEquals("레거시 미검증 퀴즈 제목", off.getQuizTitle(), "게이트 OFF 는 기존 스냅샷 그대로");
                assertNull(off.getQualityRedacted());
                assertFalse(M.writeValueAsString(off).contains("qualityRedacted"));
        }
}
