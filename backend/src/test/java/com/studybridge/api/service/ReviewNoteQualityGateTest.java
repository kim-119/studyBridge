package com.studybridge.api.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.timeout;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.studybridge.api.ai.quality.AiQualityGateSettings;
import com.studybridge.api.ai.quality.AiResponseQualityGate;
import com.studybridge.api.ai.quality.GateEvidence;
import com.studybridge.api.ai.quality.QualityEvaluatorClient;
import com.studybridge.api.dto.ReviewNoteDTO;
import com.studybridge.api.entity.Material;
import com.studybridge.api.entity.MaterialQuiz;
import com.studybridge.api.entity.ReviewNote;
import com.studybridge.api.repository.MaterialQuizRepository;
import com.studybridge.api.repository.MaterialRepository;
import com.studybridge.api.repository.ReviewNoteRepository;
import com.studybridge.api.repository.TodoRepository;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.IntFunction;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;
import org.springframework.web.reactive.function.client.WebClient;

/**
 * 오답노트 품질 게이트(Phase D, WRONG_NOTE_EXPLANATION / SIMILAR_QUESTION):
 *  · 생성(비동기): 초기 응답은 AI 없는 퀴즈 기반본(가림), 백그라운드 보강은 79 거절 → 80 승인분만 PDF/평문/retryJson 반영,
 *    전부 거절·평가기 503·ai07 실패면 아무것도 반영하지 않음(FALLBACK).
 *  · 재노출(목록/상세/retry/다운로드/메모 응답): 게이트 ON 에서 quality_status≠APPROVED 면 AI 필드만 가림(문항·정답·내 답·메모 유지).
 *  · 복습 필요/유사문제: 승인분만 저장·응답, 거절/평가 불가는 success=false + errorCode, 기존 저장본 보존.
 *  · 게이트 OFF 회귀 없음, 근거는 같은 사용자 자료 원문만.
 */
class ReviewNoteQualityGateTest {

        static final long USER = 71L;
        static final long SOURCE = 333L;
        static final long QUIZ = 44L;
        static final long NOTE = 77L;
        static final long ARCHIVE = 900L;
        static final ObjectMapper M = new ObjectMapper();
        static final ObjectMapper JSON = new ObjectMapper().registerModule(new JavaTimeModule())
                        .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);
        static final String SRC_TEXT = "스택은 후입선출(LIFO) 구조로 마지막에 넣은 원소가 먼저 나온다. 큐는 선입선출(FIFO) 구조다. ";
        static final String QUIZ_DATA = "[{\"question\":\"스택의 특징은?\",\"options\":[\"LIFO\",\"FIFO\",\"랜덤\",\"정렬\"],\"answer\":0,"
                        + "\"explanation\":\"퀴즈 해설: 스택은 후입선출(LIFO) 구조이다.\"},"
                        + "{\"question\":\"큐의 특징은?\",\"options\":[\"LIFO\",\"FIFO\",\"랜덤\",\"정렬\"],\"answer\":1,\"explanation\":\"\"}]";
        static final String LEGACY_RETRY = "[{\"question\":\"스택의 특징은?\",\"choices\":[\"LIFO\",\"FIFO\",\"랜덤\",\"정렬\"],"
                        + "\"correct_answer\":\"LIFO\",\"user_answer\":\"FIFO\",\"status\":\"WRONG\",\"explanation\":\"레거시 AI 해설\","
                        + "\"concept\":\"레거시 개념\"}]";

        HttpServer server;
        final AtomicInteger feedbackCalls = new AtomicInteger();
        final AtomicInteger reviewNeededCalls = new AtomicInteger();
        final AtomicInteger variantCalls = new AtomicInteger();
        final List<JsonNode> evaluations = new CopyOnWriteArrayList<>();
        volatile IntFunction<String> evaluatorPolicy = n -> out(90, "APPROVED", false);
        volatile boolean feedbackFails;
        volatile boolean reviewNeededFails;
        volatile boolean variantFails;

        ReviewNoteRepository notes;
        MaterialRepository materials;
        S3Service s3;
        final AtomicReference<ReviewNote> noteRef = new AtomicReference<>();
        final AtomicReference<Material> archiveRef = new AtomicReference<>();
        Material source;

        @BeforeEach
        void up() throws Exception {
                server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
                server.createContext("/api/ai/review/wrong-note-feedback", ex -> {
                        int n = feedbackCalls.incrementAndGet();
                        ex.getRequestBody().readAllBytes();
                        send(ex, 200, feedbackFails ? "{\"error_code\":\"AI_TIMEOUT\",\"wrong_notes\":[]}"
                                        : "{\"overall_feedback\":\"전체 피드백 초안 " + n + "\",\"wrong_notes\":["
                                                        + "{\"index\":1,\"concept\":\"후입선출 개념 초안 " + n + "\"},"
                                                        + "{\"index\":2,\"concept\":\"선입선출 개념 초안 " + n + "\",\"explanation\":\"AI 해설 초안 " + n
                                                        + ": 큐는 FIFO 다.\"}],\"error_code\":null}");
                });
                server.createContext("/api/ai/review-needed", ex -> {
                        int n = reviewNeededCalls.incrementAndGet();
                        ex.getRequestBody().readAllBytes();
                        if (reviewNeededFails) {
                                send(ex, 500, "{}");
                                return;
                        }
                        send(ex, 200, "{\"reviewNeededText\":\"후입선출에 대한 개념이 부족하여 복습이 필요합니다. 분석 초안 " + n
                                        + " 입니다.\",\"generatedBy\":\"ai\"}");
                });
                server.createContext("/api/ai/review/variant-question", ex -> {
                        int n = variantCalls.incrementAndGet();
                        ex.getRequestBody().readAllBytes();
                        if (variantFails) {
                                send(ex, 500, "{}");
                                return;
                        }
                        send(ex, 200, "{\"questions\":[{\"question\":\"유사 초안 " + n + ": 스택에서 마지막에 넣은 원소는?\","
                                        + "\"choices\":[\"가장 먼저 나온다\",\"가장 나중에 나온다\",\"중간에 나온다\",\"나오지 않는다\"],"
                                        + "\"correctAnswer\":\"가장 먼저 나온다\",\"explanation\":\"LIFO 이므로 가장 먼저 나온다.\"}],\"error_code\":null}");
                });
                server.createContext("/api/ai/quality/evaluate", ex -> {
                        JsonNode in = M.readTree(ex.getRequestBody().readAllBytes());
                        evaluations.add(in);
                        String body = evaluatorPolicy.apply(evaluations.size());
                        send(ex, body == null ? 503 : 200, body == null ? "{}"
                                        : body.replace("RID", in.get("requestId").asText()).replace("TASK", in.get("taskType").asText()));
                });
                server.start();
        }

        static void send(HttpExchange ex, int status, String body) throws IOException {
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
                return "{\"schemaVersion\":\"response-quality.v1\",\"requestId\":\"RID\",\"taskType\":\"TASK\",\"success\":true,\"verified\":"
                                + "APPROVED".equals(status) + ",\"qualityStatus\":\"" + status + "\",\"score\":" + score
                                + ",\"minimumScore\":80,\"hardFail\":" + hardFail + ",\"violations\":"
                                + (hardFail ? "[{\"code\":\"MATH_INCORRECT\",\"severity\":\"HARD\",\"reason\":\"r\"}]" : "[]")
                                + ",\"dimensions\":[],\"evaluatorVersion\":\"stub\",\"latencyMs\":1}";
        }

        ReviewNoteService service(boolean gateOn, ReviewNote preset, long sourceOwner) {
                WebClient wc = WebClient.create("http://127.0.0.1:" + server.getAddress().getPort());
                notes = mock(ReviewNoteRepository.class);
                materials = mock(MaterialRepository.class);
                s3 = mock(S3Service.class);
                when(s3.getPresignedUrl(anyString(), anyString())).thenReturn("https://s3.example/presigned-note.pdf");
                noteRef.set(preset);
                archiveRef.set(null);
                source = Material.builder().materialId(SOURCE).userId(sourceOwner).title("자료구조").extractedText(SRC_TEXT.repeat(5)).build();
                when(materials.findById(SOURCE)).thenReturn(Optional.of(source));
                when(materials.save(any(Material.class))).thenAnswer(inv -> {
                        Material m = inv.getArgument(0);
                        if (m.getMaterialId() == null) {
                                m.setMaterialId(ARCHIVE);
                        }
                        archiveRef.set(m);
                        return m;
                });
                when(materials.findById(ARCHIVE)).thenAnswer(inv -> Optional.ofNullable(archiveRef.get()));
                MaterialQuizRepository quizzes = mock(MaterialQuizRepository.class);
                when(quizzes.findById(QUIZ)).thenReturn(Optional.of(MaterialQuiz.builder().quizId(QUIZ).material(source).difficulty("보통")
                                .quizData(QUIZ_DATA).build()));
                when(notes.save(any(ReviewNote.class))).thenAnswer(inv -> {
                        ReviewNote n = inv.getArgument(0);
                        if (n.getReviewNoteId() == null) {
                                n.setReviewNoteId(NOTE);
                        }
                        noteRef.set(n);
                        return n;
                });
                when(notes.findById(NOTE)).thenAnswer(inv -> Optional.ofNullable(noteRef.get()));
                when(notes.findByReviewNoteIdAndUserId(NOTE, USER)).thenAnswer(inv -> Optional.ofNullable(noteRef.get()));
                when(notes.findByUserIdOrderByCreatedAtDesc(USER)).thenAnswer(inv -> noteRef.get() == null ? List.of() : List.of(noteRef.get()));
                ReviewNoteService svc = new ReviewNoteService(notes, quizzes, materials, s3, wc, mock(LearningLoopService.class),
                                mock(TodoRepository.class));
                ReflectionTestUtils.setField(svc, "reviewTimeoutSeconds", 10L);
                AiQualityGateSettings s = AiQualityGateSettings.forTest(gateOn);
                svc.setQualityGate(new AiResponseQualityGate(s, new QualityEvaluatorClient(wc, s, "k".repeat(64))));
                return svc;
        }

        ReviewNoteService service(boolean gateOn, ReviewNote preset) {
                return service(gateOn, preset, USER);
        }

        static ReviewNote legacy(String bodyStatus, String rnStatus) {
                return ReviewNote.builder().reviewNoteId(NOTE).userId(USER).sourceMaterialId(SOURCE).sourceTitle("자료구조").quizId(QUIZ)
                                .archiveMaterialId(ARCHIVE).title("자료구조 오답노트").s3Key("wrong-notes/71/333/44/x/wrong-note.pdf").wrongCount(1)
                                .unansweredCount(0).difficulty("medium").memo("사용자 메모").retryJson(LEGACY_RETRY)
                                .retryResultJson("[{\"index\":1,\"userAnswer\":\"FIFO\",\"correct\":false}]").aiStatus("DONE")
                                .reviewNeededText("레거시 분석 문장").qualityStatus(bodyStatus).reviewNeededQualityStatus(rnStatus).build();
        }

        static final Map<String, Object> ANSWERS = Map.of("0", 1, "1", 0); // 두 문항 모두 오답

        /** 생성 + 백그라운드 보강 완료(초기 저장 1 + 보강/상태 저장 1)까지 기다린다. */
        ReviewNoteDTO createAndAwait(ReviewNoteService svc) {
                ReviewNoteDTO dto = svc.createFromQuiz(USER, QUIZ, ANSWERS);
                verify(notes, timeout(20_000).times(2)).save(any(ReviewNote.class));
                return dto;
        }

        String json(Object o) throws Exception {
                return JSON.writeValueAsString(o);
        }

        /** 목록·상세·retry·다운로드·메모 응답 전부(사용자에게 다시 보이는 저장본). */
        String reexposed(ReviewNoteService svc) throws Exception {
                return json(svc.list(USER)) + json(svc.get(USER, NOTE)) + json(svc.getRetry(USER, NOTE)) + json(svc.getDownloadUrl(USER, NOTE))
                                + json(svc.updateMemo(USER, NOTE, "내 메모"));
        }

        // ───────────────────────── 생성(비동기 보강) + 재노출 ─────────────────────────

        @GateEvidence({"POST /api/review-notes/from-quiz/{quizSessionId}", "GET /api/review-notes", "GET /api/review-notes/{id}",
                        "GET /api/review-notes/{id}/retry", "GET /api/review-notes/{id}/download", "PATCH /api/review-notes/{id}/memo"})
        @Test
        void rejected79ThenApproved80EnrichmentIsTheOnlyAiContentStoredAndReexposed() throws Exception {
                evaluatorPolicy = n -> n == 1 ? out(79, "REJECTED", false) : out(80, "APPROVED", false);
                ReviewNoteService svc = service(true, null);
                ReviewNoteDTO created = createAndAwait(svc);
                assertEquals("PENDING", created.getAiStatus(), "평가 전 AI 응답을 기다리거나 쓰지 않는다");
                assertNull(created.getPdfUrl(), "승인 전 PDF(퀴즈 해설 포함)는 발급하지 않는다");
                assertTrue(created.getQualityRedacted());

                ReviewNote note = noteRef.get();
                assertEquals("APPROVED", note.getQualityStatus());
                assertEquals("DONE", note.getAiStatus());
                assertTrue(note.getRetryJson().contains("선입선출 개념 초안 2") && note.getRetryJson().contains("AI 해설 초안 2"));
                assertFalse(note.getRetryJson().contains("초안 1"), "79 점 보강은 저장되지 않는다");
                assertTrue(archiveRef.get().getExtractedText().contains("전체 피드백 초안 2"));
                assertFalse(archiveRef.get().getExtractedText().contains("초안 1"));
                verify(s3, times(2)).uploadBytes(any(), anyString(), anyString()); // 초기 퀴즈 기반본 + 승인본
                assertEquals(2, feedbackCalls.get(), "거절 1회 → ai07 재호출로 재생성");

                assertEquals(2, evaluations.size());
                JsonNode ev = evaluations.get(0);
                assertEquals("WRONG_NOTE_EXPLANATION", ev.get("taskType").asText());
                assertEquals("text", ev.get("outputKind").asText());
                String proposed = ev.get("proposedOutput").asText();
                assertTrue(proposed.contains("전체 피드백 초안 1") && proposed.contains("AI 해설 초안 1") && proposed.contains("스택의 특징은?")
                                && proposed.contains("퀴즈 해설: 스택은"), "사용자에게 보일 오답노트 본문 전체를 평가");
                assertEquals(SOURCE, ev.get("groundingEvidence").get(0).get("materialId").asLong());
                assertTrue(ev.get("groundingEvidence").get(0).get("text").asText().contains("후입선출(LIFO)"), "원본 자료 원문 근거");
                assertEquals(SOURCE, ev.get("constraints").get("allowedMaterialIds").get(0).asLong());

                String shown = reexposed(svc);
                assertTrue(shown.contains("AI 해설 초안 2") && shown.contains("presigned-note.pdf"), "승인 본문·PDF 는 재노출");
                assertFalse(shown.contains("초안 1"));
                ReviewNoteDTO listed = svc.list(USER).get(0);
                assertEquals("APPROVED", listed.getQualityStatus());
                assertFalse(listed.getQualityRedacted());
                assertEquals(2, evaluations.size(), "재노출 경로는 평가기를 부르지 않는다");
        }

        @GateEvidence({"POST /api/review-notes/from-quiz/{quizSessionId}", "GET /api/review-notes", "GET /api/review-notes/{id}",
                        "GET /api/review-notes/{id}/retry", "GET /api/review-notes/{id}/download", "PATCH /api/review-notes/{id}/memo"})
        @Test
        void allRejectedEnrichmentStoresNothingAndReadPathsRedactAiFieldsOnly() throws Exception {
                evaluatorPolicy = n -> out(70, "REJECTED", false);
                ReviewNoteService svc = service(true, null);
                createAndAwait(svc);
                ReviewNote note = noteRef.get();
                assertNull(note.getQualityStatus());
                assertEquals("FALLBACK", note.getAiStatus());
                assertEquals(3, feedbackCalls.get(), "최초 1 + 재생성 2");
                assertEquals(3, evaluations.size());
                assertFalse(note.getRetryJson().contains("초안"), "거절 보강은 retryJson 에 없다");
                assertFalse(archiveRef.get().getExtractedText().contains("초안"), "거절 보강은 자료보관함 평문에 없다");
                verify(s3, times(1)).uploadBytes(any(), anyString(), anyString());
                verify(materials, times(1)).save(any(Material.class));

                String shown = reexposed(svc);
                assertFalse(shown.contains("초안"), "응답 어디에도 AI 초안 없음");
                assertFalse(shown.contains("퀴즈 해설: 스택은"), "미승인 본문의 해설(퀴즈 해설 포함)은 가린다");
                assertFalse(shown.contains("presigned"), "미승인 PDF URL 미발급");
                assertTrue(shown.contains("스택의 특징은?") && shown.contains("\"correct_answer\":\"LIFO\"") && shown.contains("\"user_answer\":\"FIFO\""),
                                "원래 문제·정답·내 답은 사용자 데이터라 유지");
                ReviewNoteDTO dto = svc.updateMemo(USER, NOTE, "내가 쓴 메모");
                assertEquals("내가 쓴 메모", dto.getMemo(), "사용자 메모는 가리지 않는다");
                assertTrue(dto.getQualityRedacted());
                assertNotNull(dto.getQualityNotice());
                Map<String, Object> dl = svc.getDownloadUrl(USER, NOTE);
                assertNull(dl.get("url"));
                assertEquals(true, dl.get("qualityRedacted"));
                verify(s3, never()).getPresignedUrl(anyString(), anyString());
        }

        @Test
        void evaluatorDownOrAi07FailureAppliesNoEnrichment() throws Exception {
                evaluatorPolicy = n -> null; // 503
                ReviewNoteService svc = service(true, null);
                createAndAwait(svc);
                assertEquals("FALLBACK", noteRef.get().getAiStatus());
                assertNull(noteRef.get().getQualityStatus());
                assertEquals(1, feedbackCalls.get(), "평가기 장애 시 재생성하지 않는다");
                assertEquals(1, evaluations.size());

                evaluations.clear();
                feedbackCalls.set(0);
                feedbackFails = true;
                ReviewNoteService svc2 = service(true, null);
                createAndAwait(svc2);
                assertEquals("FALLBACK", noteRef.get().getAiStatus());
                assertEquals(0, evaluations.size(), "ai07 실패면 평가하지 않는다");
                assertEquals(1, feedbackCalls.get());
        }

        @GateEvidence({"GET /api/review-notes", "GET /api/review-notes/{id}", "GET /api/review-notes/{id}/retry",
                        "GET /api/review-notes/{id}/download", "PATCH /api/review-notes/{id}/memo"})
        @Test
        void legacyUnapprovedNoteIsRedactedApprovedIsShownAndGateOffUnchanged() throws Exception {
                ReviewNoteService on = service(true, legacy(null, null));
                String shown = reexposed(on);
                assertFalse(shown.contains("레거시 AI 해설") || shown.contains("레거시 개념") || shown.contains("레거시 분석 문장"),
                                "미검증 저장본의 AI 필드는 게이트 ON 에서 재노출 금지");
                assertFalse(shown.contains("presigned"));
                assertTrue(shown.contains("\"retryResults\":[{\"index\":1,\"userAnswer\":\"FIFO\",\"correct\":false}]"), "재풀이 기록 유지");
                ReviewNoteDTO dto = on.get(USER, NOTE);
                assertNull(dto.getReviewNeededText());
                assertTrue(dto.getQualityRedacted());
                assertEquals("자료구조 오답노트", dto.getTitle());
                assertEquals(1, dto.getWrongCount());
                Map<String, Object> submitted = on.submitRetryResult(USER, NOTE, Map.<String, Object>of("index", 1, "userAnswer", "LIFO"));
                assertFalse(json(submitted).contains("레거시 AI 해설"), "재풀이 채점 응답 = 사용자 기록만(EXEMPT 근거)");

                ReviewNoteService approved = service(true, legacy("APPROVED", "APPROVED"));
                String ok = reexposed(approved);
                assertTrue(ok.contains("레거시 AI 해설") && ok.contains("레거시 개념") && ok.contains("레거시 분석 문장") && ok.contains("presigned"));
                assertFalse(approved.get(USER, NOTE).getQualityRedacted());

                ReviewNoteService off = service(false, legacy(null, null));
                ReviewNoteDTO legacyShown = off.get(USER, NOTE);
                assertEquals("레거시 분석 문장", legacyShown.getReviewNeededText(), "게이트 OFF 는 기존 그대로");
                assertNull(legacyShown.getQualityRedacted());
                assertNull(legacyShown.getQualityStatus());
                assertFalse(off.getRetry(USER, NOTE).containsKey("qualityRedacted"));
                assertEquals(0, evaluations.size());
        }

        @Test
        void gateOffCreationIsLegacyBehaviour() {
                ReviewNoteService svc = service(false, null);
                createAndAwait(svc);
                assertEquals("DONE", noteRef.get().getAiStatus());
                assertNull(noteRef.get().getQualityStatus());
                assertTrue(noteRef.get().getRetryJson().contains("선입선출 개념 초안 1"), "OFF: 기존처럼 보강 즉시 반영");
                assertEquals(0, evaluations.size(), "게이트 OFF: 평가기 호출 0");
        }

        // ───────────────────────── 복습 필요 분석 ─────────────────────────

        @GateEvidence({"POST /api/review-notes/{id}/review-needed"})
        @Test
        void reviewNeeded79Then80SavesOnlyApprovedText() {
                evaluatorPolicy = n -> n == 1 ? out(79, "REJECTED", false) : out(80, "APPROVED", false);
                ReviewNoteService svc = service(true, legacy("APPROVED", null));
                Map<String, Object> r = svc.generateReviewNeeded(USER, NOTE);
                assertEquals("APPROVED", r.get("qualityStatus"));
                assertEquals(true, r.get("verified"));
                assertTrue(r.get("reviewNeededText").toString().contains("분석 초안 2"));
                assertEquals(2, reviewNeededCalls.get());
                ReviewNote note = noteRef.get();
                assertTrue(note.getReviewNeededText().contains("분석 초안 2"));
                assertEquals("APPROVED", note.getReviewNeededQualityStatus());
                JsonNode ev = evaluations.get(0);
                assertEquals("WRONG_NOTE_EXPLANATION", ev.get("taskType").asText());
                assertTrue(ev.get("proposedOutput").asText().contains("분석 초안 1"), "후처리한 최종 문장 그대로 평가");
                assertTrue(ev.get("groundingEvidence").get(0).get("text").asText().contains("후입선출(LIFO)"));
                assertTrue(ev.get("originalRequest").asText().contains("스택의 특징은?"));
                // 승인 저장본은 다음 클릭에서 AI·평가 없이 그대로
                Map<String, Object> again = svc.generateReviewNeeded(USER, NOTE);
                assertEquals(true, again.get("cached"));
                assertEquals(2, reviewNeededCalls.get());
                assertEquals(2, evaluations.size());
        }

        @GateEvidence({"POST /api/review-notes/{id}/review-needed"})
        @Test
        void reviewNeededRejectedHardFailOrUnavailableSavesNothingAndKeepsExisting() throws Exception {
                evaluatorPolicy = n -> out(70, "REJECTED", false);
                ReviewNoteService svc = service(true, legacy(null, null));
                Map<String, Object> r = svc.generateReviewNeeded(USER, NOTE);
                assertEquals(false, r.get("success"));
                assertEquals("AI_QUALITY_REJECTED", r.get("errorCode"));
                assertEquals(true, r.get("retryable"));
                assertNull(r.get("reviewNeededText"));
                assertFalse(json(r).contains("분석 초안"), "거절 초안 미노출");
                assertEquals(3, reviewNeededCalls.get(), "미승인 레거시 저장본은 재노출하지 않고 다시 생성(최초 1 + 재생성 2)");
                verify(notes, never()).save(any());
                assertEquals("레거시 분석 문장", noteRef.get().getReviewNeededText(), "기존 저장본을 덮어쓰지 않는다");

                evaluatorPolicy = n -> out(95, "REJECTED", true);
                Map<String, Object> hard = service(true, legacy(null, null)).generateReviewNeeded(USER, NOTE);
                assertEquals("AI_QUALITY_REJECTED", hard.get("errorCode"), "hardFail 은 점수와 무관하게 거절");

                reviewNeededCalls.set(0);
                evaluatorPolicy = n -> null;
                Map<String, Object> down = service(true, legacy(null, null)).generateReviewNeeded(USER, NOTE);
                assertEquals("AI_QUALITY_UNAVAILABLE", down.get("errorCode"));
                assertEquals(1, reviewNeededCalls.get());
                verify(notes, never()).save(any());
        }

        @Test
        void reviewNeededAi07FailureReturnsUnsavedRuleTextAndOtherUsersMaterialIsNotEvidence() {
                reviewNeededFails = true;
                ReviewNoteService svc = service(true, legacy("APPROVED", null));
                Map<String, Object> r = svc.generateReviewNeeded(USER, NOTE);
                assertEquals("rule", r.get("generatedBy"));
                assertEquals(false, r.get("verified"));
                assertNotNull(r.get("reviewNeededText"));
                assertEquals(0, evaluations.size(), "생성 실패면 평가하지 않는다");
                verify(notes, never()).save(any());

                reviewNeededFails = false;
                ReviewNoteService foreign = service(true, legacy("APPROVED", null), 999L); // 원본 자료 소유자가 다름
                foreign.generateReviewNeeded(USER, NOTE);
                assertEquals(0, evaluations.get(0).get("groundingEvidence").size(), "다른 사용자 자료 원문은 근거로 쓰지 않는다");
        }

        // ───────────────────────── 유사문제 ─────────────────────────

        @GateEvidence({"POST /api/review-notes/{id}/variant-question"})
        @Test
        void variant79Then80ReturnsOnlyApprovedQuestions() throws Exception {
                evaluatorPolicy = n -> n == 1 ? out(79, "REJECTED", false) : out(80, "APPROVED", false);
                ReviewNoteService svc = service(true, legacy(null, null));
                Map<String, Object> r = svc.variantQuestion(USER, NOTE, Map.of("count", 1, "difficulty", "normal"));
                assertEquals(true, r.get("success"));
                assertEquals("APPROVED", r.get("qualityStatus"));
                assertTrue(json(r.get("questions")).contains("유사 초안 2"));
                assertFalse(json(r).contains("유사 초안 1"));
                assertEquals(2, variantCalls.get());
                JsonNode ev = evaluations.get(0);
                assertEquals("SIMILAR_QUESTION", ev.get("taskType").asText());
                assertEquals("quiz_json", ev.get("outputKind").asText());
                assertTrue(ev.get("proposedOutput").get("questions").get(0).get("question").asText().contains("유사 초안 1"),
                                "보일 문항 전체(문제·보기·정답·해설)를 quiz_json 으로 평가");
                assertEquals("가장 먼저 나온다", ev.get("proposedOutput").get("questions").get(0).get("correctAnswer").asText());
                assertTrue(ev.get("groundingEvidence").get(0).get("text").asText().contains("후입선출(LIFO)"));
        }

        @GateEvidence({"POST /api/review-notes/{id}/variant-question"})
        @Test
        void variantRejectedOrUnavailableIsExplicitFailureWithoutDraft() throws Exception {
                evaluatorPolicy = n -> out(70, "REJECTED", false);
                Map<String, Object> r = service(true, legacy(null, null)).variantQuestion(USER, NOTE, Map.of("count", 1));
                assertEquals(false, r.get("success"));
                assertEquals("AI_QUALITY_REJECTED", r.get("errorCode"));
                assertEquals(List.of(), r.get("questions"));
                assertFalse(json(r).contains("유사 초안"));
                assertEquals(3, variantCalls.get());

                variantCalls.set(0);
                evaluatorPolicy = n -> null;
                Map<String, Object> down = service(true, legacy(null, null)).variantQuestion(USER, NOTE, Map.of("count", 1));
                assertEquals("AI_QUALITY_UNAVAILABLE", down.get("errorCode"));
                assertEquals(1, variantCalls.get());
        }

        @Test
        void variantAi07FailureFallsBackToOriginalQuestionWithRedactedExplanation() throws Exception {
                variantFails = true;
                Map<String, Object> r = service(true, legacy(null, null)).variantQuestion(USER, NOTE, Map.of("count", 1));
                assertEquals(true, r.get("usedFallback"));
                String q = json(r.get("questions"));
                assertTrue(q.contains("스택의 특징은?"), "원본 오답 재출제(비AI)");
                assertFalse(q.contains("레거시 AI 해설"), "본문 미승인 노트의 해설은 폴백 문항에서도 가린다");
                assertEquals(0, evaluations.size());
        }
}
