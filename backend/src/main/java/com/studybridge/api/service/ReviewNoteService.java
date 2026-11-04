package com.studybridge.api.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.studybridge.api.ai.contract.v1.ResponseQualityV1;
import com.studybridge.api.ai.quality.AiResponseQualityGate;
import com.studybridge.api.ai.quality.GateDecision;
import com.studybridge.api.dto.ReviewNoteDTO;
import com.studybridge.api.entity.ExtractionStatus;
import com.studybridge.api.entity.LearningEventType;
import com.studybridge.api.entity.LearningLoopEvent;
import com.studybridge.api.entity.LearningSourceType;
import com.studybridge.api.entity.Material;
import com.studybridge.api.entity.MaterialQuiz;
import com.studybridge.api.entity.MaterialType;
import com.studybridge.api.entity.ReviewNote;
import com.studybridge.api.repository.MaterialQuizRepository;
import com.studybridge.api.repository.MaterialRepository;
import com.studybridge.api.repository.ReviewNoteRepository;
import com.lowagie.text.Document;
import com.lowagie.text.Font;
import com.lowagie.text.PageSize;
import com.lowagie.text.Paragraph;
import com.lowagie.text.pdf.BaseFont;
import com.lowagie.text.pdf.PdfWriter;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.web.reactive.function.client.WebClient;

import java.awt.Color;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * 오답노트 생성/조회 서비스.
 * 흐름: 퀴즈 채점으로 틀린 문제 추출 → (ai07 wrong-note-feedback 을 백그라운드로 발사) →
 *   퀴즈 자체 해설로 PDF 즉시 생성 → S3 업로드 → review_note 메타 저장 → 자료보관함(Material) 자동 추가
 *   → 응답. ai07 응답이 도착하면 백그라운드에서 PDF/평문/다시풀기 JSON 을 AI 강화본으로 교체한다.
 *
 * ★ 왜 비동기인가: ai07 wrong-note-feedback 은 문항 수에 따라 15~60초가 걸린다(운영 로그 elapsedMs=58329).
 *   예전엔 이 응답을 동기로 기다려 "저장 중..." 이 그만큼 길었다. 오답노트의 핵심 데이터(문항/정답/내 답/
 *   퀴즈 해설)는 이미 DB 에 있으므로 먼저 만들어 주고, AI 보강은 도착하는 대로 덮어쓴다(aiStatus 로 추적).
 */
@Slf4j
@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class ReviewNoteService {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private final ReviewNoteRepository reviewNoteRepository;
    private final MaterialQuizRepository quizRepository;
    private final MaterialRepository materialRepository;
    private final S3Service s3Service;
    private final WebClient fastApiWebClient;
    private final LearningLoopService learningLoopService;
    private final com.studybridge.api.repository.TodoRepository todoRepository;

    @Value("${ai.server.fastapi.review-timeout-seconds:120}")
    private long reviewTimeoutSeconds;

    // 생성 요청이 ai07 응답을 동기로 기다려 주는 최대 시간(초). 0 이면 기다리지 않고 즉시 폴백본으로 응답.
    // ai07 이 이 시간 안에 답하면 처음부터 AI 강화본으로 저장되고, 늦으면 백그라운드 보강으로 넘어간다.
    @Value("${ai.server.fastapi.review-sync-budget-seconds:0}")
    private long reviewSyncBudgetSeconds;

    // aiStatus 값: PENDING(백그라운드 보강 대기) | DONE(AI 강화본 반영) | FALLBACK(AI 실패, 퀴즈 해설본 유지)
    static final String AI_STATUS_PENDING = "PENDING";
    static final String AI_STATUS_DONE = "DONE";
    static final String AI_STATUS_FALLBACK = "FALLBACK";

    // ai07 호출 + 백그라운드 보강 전용 소형 풀(요청 스레드/doc-extract 풀과 분리). final+초기화라 생성자 인자에서 제외됨.
    private final ExecutorService aiEnrichExecutor = Executors.newFixedThreadPool(2, new java.util.concurrent.ThreadFactory() {
        private final AtomicInteger seq = new AtomicInteger();
        @Override public Thread newThread(Runnable r) {
            Thread t = new Thread(r, "review-note-ai-" + seq.incrementAndGet());
            t.setDaemon(true);
            return t;
        }
    });

    // 품질 게이트 백그라운드 보강 전용 풀(재생성 시 ai07 재호출 + 평가가 길어도 최초 ai07 호출 풀을 막지 않게 분리).
    private final ExecutorService aiGateExecutor = Executors.newFixedThreadPool(2, new java.util.concurrent.ThreadFactory() {
        private final AtomicInteger seq = new AtomicInteger();
        @Override public Thread newThread(Runnable r) {
            Thread t = new Thread(r, "review-note-gate-" + seq.incrementAndGet());
            t.setDaemon(true);
            return t;
        }
    });

    private byte[] cachedFont;

    // ── 품질 게이트(response-quality.v1, 기본 OFF). 생성자 시그니처를 바꾸지 않도록 setter 주입(null 이면 OFF) ──
    //  · 오답노트 본문(문항 해설·다시 볼 개념·전체 피드백·PDF) = WRONG_NOTE_EXPLANATION, 백그라운드 보강을 평가 → 승인분만 반영.
    //  · 복습 필요 분석 = WRONG_NOTE_EXPLANATION(text), 유사문제 = SIMILAR_QUESTION(quiz_json).
    //  · 게이트 ON 조회(목록/상세/retry/다운로드/메모 응답): APPROVED 가 아닌 AI 필드만 가린다. 문항·보기·정답·내 답·재풀이 기록·메모는 유지.
    private AiResponseQualityGate qualityGate;
    static final String QUALITY_APPROVED = "APPROVED";
    static final String QUALITY_NOTICE = "AI 해설·다시 볼 개념·PDF·복습 필요 분석은 품질 검증을 통과한 뒤에만 표시됩니다. 문제·정답·내 답·메모는 그대로 볼 수 있습니다.";

    @Autowired(required = false)
    public void setQualityGate(AiResponseQualityGate qualityGate) {
        this.qualityGate = qualityGate;
    }

    private boolean gateOn() {
        return qualityGate != null && qualityGate.enabled();
    }

    // ---------------------------------------------------------------------
    // 생성: POST /api/review-notes/from-quiz/{quizId}
    // ---------------------------------------------------------------------
    @Transactional
    public ReviewNoteDTO createFromQuiz(Long userId, Long quizId, Map<String, Object> answers) {
        MaterialQuiz quiz = quizRepository.findById(quizId)
                .orElseThrow(() -> new IllegalArgumentException("퀴즈를 찾을 수 없습니다."));
        Material source = quiz.getMaterial();
        if (source == null) {
            throw new IllegalArgumentException("퀴즈의 원본 자료를 찾을 수 없습니다.");
        }
        if (!source.getUserId().equals(userId)) {
            throw new SecurityException("권한이 없습니다.");
        }

        // 1) 저장된 퀴즈 + 제출 답안으로 복습 대상(오답 + 미응답) 추출 (프론트 parseQuizQuestions 규칙 미러링)
        //    - WRONG     : 응답했지만 정답이 아님
        //    - UNANSWERED: 제출하지 않음(answers 에 키가 없거나 null) → "내가 고른 답: 미응답" 으로 포함
        //    - 정답(CORRECT)만 제외한다.
        List<ParsedQuestion> questions = parseQuizData(quiz.getQuizData());
        List<WrongItem> reviewItems = new ArrayList<>();   // 오답 + 미응답 (원본 순서 유지)
        List<Map<String, Object>> wrongQuestions = new ArrayList<>();
        int wrongOnly = 0;
        int unansweredOnly = 0;
        for (int idx = 0; idx < questions.size(); idx++) {
            ParsedQuestion q = questions.get(idx);
            Integer selected = answerIndexFor(answers, idx);
            boolean unanswered = (selected == null);
            if (!unanswered && selected.equals(q.correctIndex)) continue; // 정답은 제외
            if (unanswered) unansweredOnly++; else wrongOnly++;
            reviewItems.add(new WrongItem(q.question, q.options, q.correctIndex, selected, q.explanation, unanswered, q.page));
            Map<String, Object> wq = new LinkedHashMap<>();
            wq.put("question", q.question);
            wq.put("options", q.options);
            wq.put("choices", q.options);
            wq.put("correct_answer", optionAt(q.options, q.correctIndex));
            wq.put("user_answer", unanswered ? "미응답" : optionAt(q.options, selected));
            wq.put("status", unanswered ? "UNANSWERED" : "WRONG");
            wq.put("explanation", q.explanation);
            wq.put("page", q.page);
            wrongQuestions.add(wq);
        }

        if (reviewItems.isEmpty()) {
            throw new IllegalStateException("복습할 문제가 없습니다. 모든 문제를 맞혔어요.");
        }

        // 2) ai07 호출을 백그라운드로 발사. 기본(sync budget 0)은 기다리지 않고 바로 폴백본을 만든다.
        Map<String, Object> requestBody = new LinkedHashMap<>();
        requestBody.put("material_id", source.getMaterialId());
        requestBody.put("material_title", source.getTitle());
        String docText = source.getExtractedText();
        if (docText != null && docText.length() > 6000) docText = docText.substring(0, 6000);
        requestBody.put("document_text", docText != null ? docText : "");
        requestBody.put("difficulty", mapDifficulty(quiz.getDifficulty()));
        requestBody.put("wrong_questions", wrongQuestions);

        long t0 = System.currentTimeMillis();
        log.info("[REVIEW_NOTE] start userId={} quizId={} materialId={} wrong={} unanswered={} syncBudgetSec={}",
                userId, quizId, source.getMaterialId(), wrongOnly, unansweredOnly, reviewSyncBudgetSeconds);

        final Long quizIdF = quizId;
        CompletableFuture<Map> aiFuture = CompletableFuture.supplyAsync(
                () -> callWrongNoteFeedback(requestBody, quizIdF), aiEnrichExecutor);

        // 게이트 ON: 평가 전 AI 응답은 쓰지 않는다 — 항상 AI 없는 퀴즈 기반본으로 저장하고, 보강은 백그라운드 게이트를 거친다.
        final boolean gated = gateOn();
        Map response = null;
        if (reviewSyncBudgetSeconds > 0 && !gated) {
            try {
                response = aiFuture.get(reviewSyncBudgetSeconds, TimeUnit.SECONDS);
            } catch (TimeoutException te) {
                log.info("[REVIEW_NOTE] ai07 응답이 {}s 내 미도착 quizId={} -> 폴백본 즉시 저장 + 백그라운드 보강", reviewSyncBudgetSeconds, quizId);
            } catch (Exception e) {
                log.warn("[REVIEW_NOTE] ai07 sync wait 실패 quizId={} cause={}", quizId, e.getMessage());
            }
        }

        boolean aiEnriched = !gated && isAiOk(response);
        boolean aiSettled = !gated && aiFuture.isDone();   // 이미 결론(성공/실패)이 났으면 백그라운드 보강 불필요

        String defaultFeedback = defaultOverallFeedback(unansweredOnly);
        String overallFeedback = aiEnriched ? overallFeedbackOf(response, defaultFeedback) : defaultFeedback;
        if (aiEnriched) enrichFromAi(reviewItems, response);

        // 2-1) 구조화된 오답노트 문서 모델 → PDF + 검색용 평문 + 다시풀기 JSON
        String createdDate = java.time.LocalDate.now().toString();
        String noteTitle = safeTitle(source.getTitle()) + " 오답노트";
        String fileName = noteTitle + ".pdf";
        String diffKo = quiz.getDifficulty() == null || quiz.getDifficulty().isBlank() ? "보통" : quiz.getDifficulty();
        String plainText = buildFallbackPlainText(noteTitle, source.getTitle(), diffKo, createdDate,
                wrongOnly, unansweredOnly, overallFeedback, reviewItems);
        String retryJson = buildRetryJsonFromWrong(reviewItems);

        // 3) PDF 생성 (NanumGothic, 카드형 레이아웃)
        byte[] pdf = buildPdf(noteTitle, source.getTitle(), diffKo, createdDate,
                wrongOnly, unansweredOnly, overallFeedback, reviewItems);

        // 4) S3 업로드
        String s3Key = "wrong-notes/" + userId + "/" + source.getMaterialId() + "/" + quizId + "/" + UUID.randomUUID() + "/wrong-note.pdf";
        s3Service.uploadBytes(pdf, s3Key, "application/pdf");

        String aiStatus = aiEnriched ? AI_STATUS_DONE : (aiSettled ? AI_STATUS_FALLBACK : AI_STATUS_PENDING);

        // 5) 자료보관함 노출용 Material(REVIEW_NOTE) 자동 추가
        Material archive = Material.builder()
                .userId(userId)
                .title(noteTitle)
                .materialType(MaterialType.REVIEW_NOTE)
                .originalFileName(fileName)
                .storedFileName(s3Key)
                .s3FileUrl(s3Key)
                .fileSize((long) pdf.length)
                .extractedText(plainText)
                .extractionStatus(ExtractionStatus.SUCCESS)
                .build();
        archive = materialRepository.save(archive);

        // 6) review_note 메타 저장 (오답/미응답 수 분리)
        ReviewNote note = ReviewNote.builder()
                .userId(userId)
                .sourceMaterialId(source.getMaterialId())
                .sourceTitle(source.getTitle())
                .quizId(quizId)
                .archiveMaterialId(archive.getMaterialId())
                .title(noteTitle)
                .s3Key(s3Key)
                .wrongCount(wrongOnly)
                .unansweredCount(unansweredOnly)
                .difficulty(mapDifficulty(quiz.getDifficulty()))
                .retryJson(retryJson)
                .aiStatus(aiStatus)
                .build();
        // 복습 세션 완료 = 오답노트 생성. 같은 트랜잭션에서 추천 복습일을 결정적으로 확정해 저장한다(ai07 의존 없음).
        LearningLoopService.ReviewRecommendation rec = LearningLoopService.computeReviewRecommendation(
                note.getDifficulty(), wrongOnly + unansweredOnly, java.time.LocalDate.now());
        note.setRecommendReviewInDays(rec.days());
        note.setRecommendedReviewDate(rec.date());
        note.setReviewReason(rec.reason());
        note = reviewNoteRepository.save(note);

        log.info("[REVIEW_NOTE] OK userId={} reviewNoteId={} archiveMaterialId={} wrong={} unanswered={} aiStatus={} elapsedMs={}",
                userId, note.getReviewNoteId(), archive.getMaterialId(), wrongOnly, unansweredOnly, aiStatus, System.currentTimeMillis() - t0);

        // 6-1) ai07 응답이 아직이면: 트랜잭션 커밋 후 도착 시점에 PDF/평문/retryJson 을 AI 강화본으로 교체
        if (AI_STATUS_PENDING.equals(aiStatus)) {
            final Long noteId = note.getReviewNoteId();
            final Long archiveId = archive.getMaterialId();
            final String srcTitle = source.getTitle();
            final List<WrongItem> itemsF = reviewItems;
            final int wrongF = wrongOnly, unansweredF = unansweredOnly;
            final EnrichJob job = new EnrichJob(noteId, archiveId, s3Key, itemsF, noteTitle, srcTitle, diffKo, createdDate,
                    wrongF, unansweredF, defaultFeedback, t0, requestBody, quizIdF, source.getMaterialId(), source.getExtractedText());
            Runnable hook = gated
                    // 게이트: 평가·재생성이 길어질 수 있으므로 요청 스레드(이미 완료된 future 의 동기 콜백)에서 돌리지 않는다.
                    ? () -> aiFuture.whenCompleteAsync((resp, err) -> {
                        if (err != null) log.warn("[REVIEW_NOTE] ai07 background 실패 reviewNoteId={} cause={}", noteId, err.toString());
                        applyAiEnrichmentGated(job, err == null ? resp : null);
                    }, aiGateExecutor)
                    : () -> aiFuture.whenComplete((resp, err) -> {
                if (err != null) log.warn("[REVIEW_NOTE] ai07 background 실패 reviewNoteId={} cause={}", noteId, err.toString());
                applyAiEnrichment(noteId, archiveId, s3Key, err == null ? resp : null, itemsF,
                        noteTitle, srcTitle, diffKo, createdDate, wrongF, unansweredF, defaultFeedback, t0);
            });
            if (TransactionSynchronizationManager.isSynchronizationActive()) {
                TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                    @Override public void afterCommit() { hook.run(); }
                });
            } else {
                hook.run();
            }
        }

        // 학습 왕복 루프: 퀴즈 제출 + 오답노트 생성 이벤트 기록(best-effort, 본 기능에 영향 없음)
        int reviewTotal = wrongOnly + unansweredOnly;
        int answered = questions.size() - unansweredOnly;
        int correct = answered - wrongOnly;
        int scorePct = questions.isEmpty() ? 0 : Math.round((correct * 100f) / questions.size());
        learningLoopService.recordSafe(LearningLoopEvent.builder()
                .userId(userId)
                .eventType(LearningEventType.QUIZ_SUBMITTED)
                .sourceType(LearningSourceType.QUIZ)
                .sourceId(quizId)
                .materialId(source.getMaterialId())
                .quizId(quizId)
                .score(scorePct)
                .difficulty(mapDifficulty(quiz.getDifficulty()))
                .aiOutputSummary("퀴즈 채점 " + questions.size() + "문항 중 정답 " + correct + " · 복습필요 " + reviewTotal)
                .userAction("QUIZ_SUBMITTED")
                .build());
        learningLoopService.recordSafe(LearningLoopEvent.builder()
                .userId(userId)
                .eventType(LearningEventType.WRONG_NOTE_CREATED)
                .sourceType(LearningSourceType.WRONG_NOTE)
                .sourceId(note.getReviewNoteId())
                .materialId(source.getMaterialId())
                .wrongNoteId(note.getReviewNoteId())
                .quizId(quizId)
                .difficulty(mapDifficulty(quiz.getDifficulty()))
                .aiOutputSummary(noteTitle + " (오답 " + wrongOnly + " · 미응답 " + unansweredOnly + ")")
                .userAction("WRONG_NOTE_CREATED")
                .build());

        return toDTO(note, true);
    }

    private String asStr(Object o) { return o == null ? null : o.toString(); }

    private String firstNonBlank(String... vals) {
        if (vals == null) return null;
        for (String v : vals) if (v != null && !v.isBlank()) return v;
        return null;
    }

    // ai07 wrong-note-feedback 동기 호출(백그라운드 스레드에서 실행). 실패/404 는 null 로 돌려 폴백을 유도한다.
    private Map callWrongNoteFeedback(Map<String, Object> requestBody, Long quizId) {
        long t = System.currentTimeMillis();
        try {
            Map resp = fastApiWebClient.post().uri("/api/ai/review/wrong-note-feedback")
                    .bodyValue(requestBody).retrieve().bodyToMono(Map.class)
                    .block(Duration.ofSeconds(reviewTimeoutSeconds));
            log.info("[REVIEW_NOTE] ai07 wrong-note-feedback 응답 quizId={} ok={} elapsedMs={}",
                    quizId, isAiOk(resp), System.currentTimeMillis() - t);
            return resp;
        } catch (Exception e) {
            log.warn("[REVIEW_NOTE] ai07 unavailable quizId={} cause={} elapsedMs={} -> 폴백 유지",
                    quizId, e.getClass().getSimpleName() + ": " + e.getMessage(), System.currentTimeMillis() - t);
            return null;
        }
    }

    private boolean isAiOk(Map response) {
        return response != null && response.get("error_code") == null;
    }

    private String defaultOverallFeedback(int unansweredOnly) {
        return "아래 문제들을 다시 확인하고, 정답과 해설을 비교하며 복습하세요."
                + (unansweredOnly > 0 ? " 미응답 문제는 시간 내에 풀이를 시도하는 연습이 필요합니다." : "");
    }

    private String overallFeedbackOf(Map response, String dflt) {
        String fb = firstNonBlank(
                asStr(response.get("overall_feedback")), asStr(response.get("overallFeedback")),
                asStr(response.get("feedback")), asStr(response.get("summary")));
        return (fb == null || fb.isBlank()) ? dflt : fb;
    }

    /**
     * 백그라운드 보강: ai07 응답으로 항목을 보강해 PDF 를 다시 만들고 같은 S3 key 에 덮어쓴 뒤,
     * 자료보관함 Material 평문/크기와 review_note 의 retryJson/aiStatus 를 갱신한다.
     * 요청 트랜잭션과 무관한 스레드에서 실행되며 각 repository.save 는 자체 트랜잭션이다. 어떤 실패도 사용자 응답에 영향 없음.
     */
    void applyAiEnrichment(Long noteId, Long archiveId, String s3Key, Map response, List<WrongItem> items,
                           String noteTitle, String sourceTitle, String diffKo, String createdDate,
                           int wrongOnly, int unansweredOnly, String defaultFeedback, long t0) {
        if (!isAiOk(response)) {
            markAiStatus(noteId, AI_STATUS_FALLBACK);
            log.info("[REVIEW_NOTE] background enrich skip(폴백 유지) reviewNoteId={} totalMs={}", noteId, System.currentTimeMillis() - t0);
            return;
        }
        try {
            String overallFeedback = overallFeedbackOf(response, defaultFeedback);
            enrichFromAi(items, response);
            String plainText = buildFallbackPlainText(noteTitle, sourceTitle, diffKo, createdDate,
                    wrongOnly, unansweredOnly, overallFeedback, items);
            String retryJson = buildRetryJsonFromWrong(items);
            byte[] pdf = buildPdf(noteTitle, sourceTitle, diffKo, createdDate,
                    wrongOnly, unansweredOnly, overallFeedback, items);
            s3Service.uploadBytes(pdf, s3Key, "application/pdf");

            materialRepository.findById(archiveId).ifPresent(m -> {
                m.setExtractedText(plainText);
                m.setFileSize((long) pdf.length);
                materialRepository.save(m);
            });
            ReviewNote note = reviewNoteRepository.findById(noteId).orElse(null);
            if (note == null) {
                log.warn("[REVIEW_NOTE] background enrich: note 없음(삭제됨?) reviewNoteId={}", noteId);
                return;
            }
            note.setRetryJson(retryJson);
            note.setAiStatus(AI_STATUS_DONE);
            reviewNoteRepository.save(note);
            log.info("[REVIEW_NOTE] background enrich DONE reviewNoteId={} archiveMaterialId={} totalMs={}",
                    noteId, archiveId, System.currentTimeMillis() - t0);
        } catch (Exception e) {
            log.warn("[REVIEW_NOTE] background enrich 실패(폴백 유지) reviewNoteId={} cause={}", noteId, e.toString());
            markAiStatus(noteId, AI_STATUS_FALLBACK);
        }
    }

    /** 백그라운드 게이트 보강 작업 단위(요청 트랜잭션 밖에서 실행). sourceText = 소유권 확인을 마친 원본 자료 원문(평가 근거). */
    record EnrichJob(Long noteId, Long archiveId, String s3Key, List<WrongItem> items, String noteTitle, String sourceTitle,
                     String diffKo, String createdDate, int wrongOnly, int unansweredOnly, String defaultFeedback, long t0,
                     Map<String, Object> requestBody, Long quizId, Long sourceMaterialId, String sourceText) { }

    /** 한 시도의 AI 보강 결과(사용자에게 보일 본문 전체 = plainText). */
    record Enriched(List<WrongItem> items, String overallFeedback, String plainText) { }

    /**
     * 게이트 ON 백그라운드 보강: ai07 응답으로 만든 오답노트 본문 전체(문항·정답·내 답·해설·다시 볼 개념·전체 피드백)를
     * WRONG_NOTE_EXPLANATION 으로 평가 → 거절 시 ai07 재호출로 최대 2회 재생성 → 승인분만 PDF/자료보관함 평문/retryJson 에 반영하고
     * quality_status=APPROVED 를 기록한다. 거절/평가 불가/ai07 실패는 아무것도 반영하지 않고 aiStatus=FALLBACK(퀴즈 기반본 유지)으로 끝난다.
     */
    void applyAiEnrichmentGated(EnrichJob job, Map firstResponse) {
        Long noteId = job.noteId();
        try {
            String rid = "wn-" + noteId + "-" + UUID.randomUUID().toString().substring(0, 8);
            AiResponseQualityGate.Spec spec = new AiResponseQualityGate.Spec(rid, ResponseQualityV1.TaskType.WRONG_NOTE_EXPLANATION,
                    ResponseQualityV1.OutputKind.TEXT, wrongNoteRequest(job), sourceEvidence(job.sourceMaterialId(), job.sourceText()),
                    materialConstraints(job.sourceMaterialId()), null);
            AiResponseQualityGate.Outcome<Enriched> outcome = qualityGate.generateApproved(spec, (attempt, previous) -> {
                Map resp = attempt == 0 ? firstResponse : callWrongNoteFeedback(job.requestBody(), job.quizId());
                if (!isAiOk(resp)) {
                    throw new AiResponseQualityGate.StopGeneration("GENERATION_FAILED");
                }
                List<WrongItem> copy = new ArrayList<>();
                for (WrongItem w : job.items()) copy.add(w.copy());
                enrichFromAi(copy, resp);
                String overall = overallFeedbackOf(resp, job.defaultFeedback());
                return new Enriched(copy, overall, buildFallbackPlainText(job.noteTitle(), job.sourceTitle(), job.diffKo(),
                        job.createdDate(), job.wrongOnly(), job.unansweredOnly(), overall, copy));
            }, e -> AiResponseQualityGate.text(e.plainText()));
            if (!outcome.approved()) {
                markAiStatus(noteId, AI_STATUS_FALLBACK);
                log.info("[REVIEW_NOTE] gated enrich 미승인(퀴즈 기반본 유지) reviewNoteId={} status={} codes={} attempts={} totalMs={}",
                        noteId, outcome.decision().qualityStatus(), outcome.decision().reasonCodes(), outcome.decision().attempts(),
                        System.currentTimeMillis() - job.t0());
                return;
            }
            Enriched e = outcome.value();
            ReviewNote existing = reviewNoteRepository.findById(noteId).orElse(null);
            if (existing == null) {
                log.warn("[REVIEW_NOTE] gated enrich: note 없음(삭제됨?) reviewNoteId={}", noteId);
                return;
            }
            byte[] pdf = buildPdf(job.noteTitle(), job.sourceTitle(), job.diffKo(), job.createdDate(),
                    job.wrongOnly(), job.unansweredOnly(), e.overallFeedback(), e.items());
            s3Service.uploadBytes(pdf, job.s3Key(), "application/pdf");
            materialRepository.findById(job.archiveId()).ifPresent(m -> {
                m.setExtractedText(e.plainText());
                m.setFileSize((long) pdf.length);
                materialRepository.save(m);
            });
            existing.setRetryJson(buildRetryJsonFromWrong(e.items()));
            existing.setAiStatus(AI_STATUS_DONE);
            existing.setQualityStatus(QUALITY_APPROVED);
            reviewNoteRepository.save(existing);
            log.info("[REVIEW_NOTE] gated enrich APPROVED reviewNoteId={} score={} attempts={} totalMs={}",
                    noteId, outcome.decision().score(), outcome.decision().attempts(), System.currentTimeMillis() - job.t0());
        } catch (Exception ex) {
            log.warn("[REVIEW_NOTE] gated enrich 실패(퀴즈 기반본 유지) reviewNoteId={} cause={}", noteId, ex.toString());
            markAiStatus(noteId, AI_STATUS_FALLBACK);
        }
    }

    /** 평가 요청 문장: 무엇을 만들었어야 하는지 + 문항/정답/내 답(관련성 판정용). 평가기에만 간다(로그 미기록). */
    private String wrongNoteRequest(EnrichJob job) {
        StringBuilder b = new StringBuilder("다음 오답 문제들에 대해 정답 근거 해설, 다시 봐야 할 개념, 전체 복습 피드백을 작성해 주세요. 자료: ")
                .append(nz(job.sourceTitle())).append('\n');
        int i = 1;
        for (WrongItem w : job.items()) {
            b.append(i++).append(". 문제: ").append(clip(w.question, 300))
                    .append(" / 정답: ").append(clip(optionAt(w.options, w.correctIndex), 120))
                    .append(" / 내 답: ").append(w.unanswered ? "미응답" : clip(optionAt(w.options, w.selectedIndex), 120)).append('\n');
        }
        return b.toString();
    }

    /** 평가 근거 = 원본 자료(PDF) 원문. 호출자가 소유권을 확인한 자료만 넘긴다. */
    private static List<ResponseQualityV1.GroundingEvidence> sourceEvidence(Long materialId, String text) {
        return materialId == null ? List.of() : AiResponseQualityGate.pdfEvidence(materialId, text, 4000, 48000);
    }

    private static ResponseQualityV1.Constraints materialConstraints(Long materialId) {
        return new ResponseQualityV1.Constraints(materialId == null ? null : List.of(materialId), null, null, null, null, null, null,
                false, false, null, null, null, null, null, null);
    }

    /** 게이트 경로 근거용: 오답노트 원본 자료 원문(같은 사용자 소유일 때만 — 다른 사용자 자료를 근거로 쓰지 않는다). */
    private String ownedSourceText(Long userId, Long materialId) {
        if (materialId == null) return null;
        try {
            return materialRepository.findById(materialId)
                    .filter(m -> userId != null && userId.equals(m.getUserId()))
                    .map(Material::getExtractedText).orElse(null);
        } catch (Exception e) {
            log.warn("[REVIEW_NOTE] 근거 원문 조회 실패 materialId={} cause={}", materialId, e.toString());
            return null;
        }
    }

    private boolean noteApproved(ReviewNote n) {
        return QUALITY_APPROVED.equals(n.getQualityStatus());
    }

    /** 게이트 ON + 본문 미승인: retryJson 문항에서 AI 필드(해설·다시 볼 개념)만 뺀다. 문항·보기·정답·내 답·상태·페이지는 유지. */
    private static List<Map<String, Object>> redactRetryItems(List<Map<String, Object>> items) {
        List<Map<String, Object>> out = new ArrayList<>();
        for (Map<String, Object> q : items) {
            Map<String, Object> m = new LinkedHashMap<>(q);
            m.remove("explanation");
            m.remove("concept");
            m.put("qualityRedacted", true);
            out.add(m);
        }
        return out;
    }

    private void markAiStatus(Long noteId, String status) {
        try {
            reviewNoteRepository.findById(noteId).ifPresent(n -> { n.setAiStatus(status); reviewNoteRepository.save(n); });
        } catch (Exception e) {
            log.warn("[REVIEW_NOTE] aiStatus 갱신 실패 reviewNoteId={} status={} cause={}", noteId, status, e.toString());
        }
    }

    // ai07 wrong-note-feedback 응답의 per-문제 해설/개념을 reviewItems 순서대로 보강(있을 때만).
    @SuppressWarnings("unchecked")
    private void enrichFromAi(List<WrongItem> items, Map response) {
        Object notes = response.get("wrong_notes");
        if (!(notes instanceof List)) notes = response.get("notes");
        if (!(notes instanceof List)) return;
        List<?> list = (List<?>) notes;
        for (int i = 0; i < items.size() && i < list.size(); i++) {
            if (!(list.get(i) instanceof Map)) continue;
            Map<String, Object> n = (Map<String, Object>) list.get(i);
            String exp = firstNonBlank(asStr(n.get("explanation")), asStr(n.get("ai_explanation")), asStr(n.get("feedback")));
            String concept = firstNonBlank(asStr(n.get("concept")), asStr(n.get("review_concept")),
                    asStr(n.get("key_concept")), asStr(n.get("concept_to_review")));
            WrongItem w = items.get(i);
            if (concept != null) w.concept = concept;
            if (exp != null && (w.explanation == null || w.explanation.isBlank())) w.explanation = exp;
        }
    }

    // ---------------------------------------------------------------------
    // 목록 / 단건 / 다운로드 / 다시풀기 / 메모
    // ---------------------------------------------------------------------
    public List<ReviewNoteDTO> list(Long userId) {
        return reviewNoteRepository.findByUserIdOrderByCreatedAtDesc(userId).stream()
                .map(n -> toDTO(n, true))
                .collect(java.util.stream.Collectors.toList());
    }

    public ReviewNoteDTO get(Long userId, Long id) {
        return toDTO(loadOwned(userId, id), true);
    }

    public Map<String, Object> getDownloadUrl(Long userId, Long id) {
        ReviewNote note = loadOwned(userId, id);
        Map<String, Object> out = new LinkedHashMap<>();
        // 게이트 ON: PDF 에는 해설·개념·전체 피드백이 실린다 → 본문 승인 전에는 URL 을 발급하지 않는다(가림 표식만).
        boolean redact = gateOn() && !noteApproved(note);
        out.put("url", redact ? null : presign(note));
        out.put("fileName", note.getTitle() + ".pdf");
        if (redact) {
            out.put("qualityStatus", note.getQualityStatus());
            out.put("qualityRedacted", true);
            out.put("qualityNotice", QUALITY_NOTICE);
        }
        return out;
    }

    public Map<String, Object> getRetry(Long userId, Long id) {
        ReviewNote note = loadOwned(userId, id);
        Map<String, Object> out = new LinkedHashMap<>();
        List<Object> questions = new ArrayList<>();
        try {
            if (note.getRetryJson() != null && !note.getRetryJson().isBlank()) {
                JsonNode arr = MAPPER.readTree(note.getRetryJson());
                if (arr.isArray()) {
                    for (JsonNode n : arr) questions.add(MAPPER.convertValue(n, Map.class));
                }
            }
        } catch (Exception e) {
            log.warn("[REVIEW_NOTE] retry parse fail id={} msg={}", id, e.getMessage());
        }
        boolean redact = gateOn() && !noteApproved(note);
        if (redact) {
            List<Map<String, Object>> typed = new ArrayList<>();
            for (Object q : questions) {
                if (q instanceof Map<?, ?> m) {
                    Map<String, Object> copy = new LinkedHashMap<>();
                    m.forEach((k, v) -> copy.put(String.valueOf(k), v));
                    typed.add(copy);
                }
            }
            questions = new ArrayList<>(redactRetryItems(typed));
        }
        out.put("reviewNoteId", id);
        out.put("sourceMaterialId", note.getSourceMaterialId());
        out.put("questions", questions);
        // 다시 풀기는 문제당 1회다. 이미 기록된 결과를 함께 내려 중복 제출을 막는다.
        out.put("retryResults", parseRetryResults(note.getRetryResultJson()));
        if (gateOn()) {
            out.put("qualityStatus", note.getQualityStatus());
            out.put("qualityRedacted", redact);
            if (redact) out.put("qualityNotice", QUALITY_NOTICE);
        }
        return out;
    }

    @Transactional
    public ReviewNoteDTO updateMemo(Long userId, Long id, String memo) {
        ReviewNote note = loadOwned(userId, id);
        note.setMemo(memo);
        note = reviewNoteRepository.save(note);
        return toDTO(note, false);
    }

    // 오답노트 삭제: 소유 검증 → S3 PDF 삭제 → 자료보관함 연동 Material 삭제 → ReviewNote 삭제
    @Transactional
    public void delete(Long userId, Long id) {
        ReviewNote note = loadOwned(userId, id);

        if (note.getS3Key() != null && !note.getS3Key().isBlank()) {
            try {
                s3Service.deleteFile(note.getS3Key());
            } catch (Exception e) {
                log.warn("[REVIEW_NOTE] S3 삭제 실패 reviewNoteId={} s3Key={} msg={}", id, note.getS3Key(), e.getMessage());
            }
        }

        // 자료보관함 노출용 Material도 함께 정리(소유자 일치 시에만)
        if (note.getArchiveMaterialId() != null) {
            materialRepository.findById(note.getArchiveMaterialId()).ifPresent(m -> {
                if (userId.equals(m.getUserId())) {
                    materialRepository.delete(m);
                }
            });
        }

        reviewNoteRepository.delete(note);
        log.info("[REVIEW_NOTE] DELETE OK userId={} reviewNoteId={} archiveMaterialId={}",
                userId, id, note.getArchiveMaterialId());
    }

    // ---------------------------------------------------------------------
    // 복습 필요 분석: POST /api/review-notes/{id}/review-needed
    //   오답노트 데이터 기반 "{구체 개념}에 대한 개념이 부족하여 복습이 필요합니다. ..." 500자 내외 생성.
    //   AI(/api/ai/multi-chat, basic) 호출 → 실패/빈응답 시 데이터 기반 결정적 폴백.
    // ---------------------------------------------------------------------
    @Transactional
    public Map<String, Object> generateReviewNeeded(Long userId, Long id) {
        ReviewNote note = loadOwnedStrict(userId, id);
        boolean gated = gateOn();
        // 이미 저장된 분석이 있으면 ai07 재호출 없이 DB 값을 돌려준다(새로고침/재클릭 idempotent).
        // 게이트 ON: 승인 기록이 없는 저장본(레거시/게이트 OFF 시기/결정론 폴백)은 재노출하지 않고 게이트를 거쳐 다시 만든다.
        if (note.getReviewNeededText() != null && !note.getReviewNeededText().isBlank()
                && (!gated || QUALITY_APPROVED.equals(note.getReviewNeededQualityStatus()))) {
            ensureRecommendation(note);
            Map<String, Object> cached = new LinkedHashMap<>();
            cached.put("reviewNoteId", id);
            cached.put("reviewNeededText", note.getReviewNeededText());
            cached.put("recommendedReviewDate", note.getRecommendedReviewDate() != null ? note.getRecommendedReviewDate().toString() : null);
            cached.put("recommendReviewInDays", note.getRecommendReviewInDays());
            cached.put("cached", true);
            if (gated) {
                cached.put("qualityStatus", QUALITY_APPROVED);
                cached.put("verified", true);
            }
            return cached;
        }
        if (gated) {
            return generateReviewNeededGated(userId, note);
        }

        List<Map<String, Object>> items = parseRetryQuestions(note.getRetryJson());
        // 최초 풀이 결과에 '다시 풀기 1회' 결과를 합친다. 재풀이 기록이 없으면 최초 결과만 간다.
        List<Map<String, Object>> merged = mergeRetryResults(items, note.getRetryResultJson());
        String sourceTitle = (note.getSourceTitle() == null || note.getSourceTitle().isBlank())
                ? "학습자료" : note.getSourceTitle();
        String difficultyKo = difficultyLabel(note.getDifficulty());

        String text;
        if (items.isEmpty()) {
            text = "문제의 핵심 개념을 정확히 식별하기 어려워 기본 개념 복습이 필요합니다. "
                    + "원본 자료와 기존 해설을 다시 확인한 뒤, 오답 선택지가 왜 틀렸는지 비교하며 복습해 주세요.";
        } else {
            String aiText = callReviewNeededAi(id, sourceTitle, difficultyKo, merged);
            text = (aiText != null && !aiText.isBlank())
                    ? ensureLeadSentence(trimToLength(aiText.trim(), 600), items)
                    : buildReviewNeededFallback(sourceTitle, merged);
        }

        learningLoopService.recordSafe(LearningLoopEvent.builder()
                .userId(userId)
                .eventType(LearningEventType.AI_EXPLANATION_GENERATED)
                .sourceType(LearningSourceType.WRONG_NOTE)
                .sourceId(id)
                .materialId(note.getSourceMaterialId())
                .wrongNoteId(id)
                .difficulty(note.getDifficulty())
                .aiOutputSummary(text)
                .userAction("REVIEW_NEEDED")
                .build());

        // 분석 결과 + 추천 복습일을 같은 트랜잭션에서 저장 → "복습 필요" 판정은 DB 가 소유한다.
        note.setReviewNeededText(text);
        note.setReviewNeededAt(java.time.LocalDateTime.now());
        ensureRecommendation(note);
        reviewNoteRepository.save(note);

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("reviewNoteId", id);
        out.put("reviewNeededText", text);
        out.put("recommendedReviewDate", note.getRecommendedReviewDate() != null ? note.getRecommendedReviewDate().toString() : null);
        out.put("recommendReviewInDays", note.getRecommendReviewInDays());
        out.put("cached", false);
        return out;
    }

    /**
     * 게이트 ON 복습 필요 분석: /api/ai/review-needed 생성 → 후처리(첫 문장 계약·600자) 후 사용자에게 보일 최종 문장을
     * WRONG_NOTE_EXPLANATION(text, 원본 자료 원문 근거)으로 평가 → 거절 시 최대 2회 재생성 → 승인분만 저장
     * (review_needed_quality_status=APPROVED)·응답. 거절/평가 불가는 저장하지 않고(기존 저장본도 덮어쓰지 않음)
     * success=false + errorCode(AI_QUALITY_REJECTED/AI_QUALITY_UNAVAILABLE) + retryable 로 끝난다.
     * ai07 자체 실패(응답 없음)는 기존 계약대로 오답노트 데이터 기반 결정론 문장을 돌려주되 AI 결과가 아님을 표시하고 저장하지 않는다.
     */
    private Map<String, Object> generateReviewNeededGated(Long userId, ReviewNote note) {
        Long id = note.getReviewNoteId();
        List<Map<String, Object>> items = parseRetryQuestions(note.getRetryJson());
        List<Map<String, Object>> merged = mergeRetryResults(items, note.getRetryResultJson());
        String sourceTitle = (note.getSourceTitle() == null || note.getSourceTitle().isBlank()) ? "학습자료" : note.getSourceTitle();
        String difficultyKo = difficultyLabel(note.getDifficulty());
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("reviewNoteId", id);
        if (items.isEmpty()) {
            // AI 를 부르지 않는 고정 안내(문항 데이터가 없는 레거시) — 저장하지 않는다(게이트 ON 에서 미승인 저장본은 가려지므로).
            out.put("reviewNeededText", "문제의 핵심 개념을 정확히 식별하기 어려워 기본 개념 복습이 필요합니다. "
                    + "원본 자료와 기존 해설을 다시 확인한 뒤, 오답 선택지가 왜 틀렸는지 비교하며 복습해 주세요.");
            out.put("cached", false);
            out.put("generatedBy", "rule");
            out.put("verified", false);
            return out;
        }
        String rid = "rn-" + id + "-" + UUID.randomUUID().toString().substring(0, 8);
        AiResponseQualityGate.Spec spec = new AiResponseQualityGate.Spec(rid, ResponseQualityV1.TaskType.WRONG_NOTE_EXPLANATION,
                ResponseQualityV1.OutputKind.TEXT, buildReviewNeededPrompt(sourceTitle, difficultyKo, merged),
                sourceEvidence(note.getSourceMaterialId(), ownedSourceText(userId, note.getSourceMaterialId())),
                materialConstraints(note.getSourceMaterialId()), null);
        final boolean[] upstreamFailed = new boolean[1];
        AiResponseQualityGate.Outcome<String> outcome = qualityGate.generateApproved(spec, (attempt, previous) -> {
            String aiText = callReviewNeededAi(id, sourceTitle, difficultyKo, merged);
            if (aiText == null || aiText.isBlank()) {
                upstreamFailed[0] = true;
                throw new AiResponseQualityGate.StopGeneration("GENERATION_FAILED");
            }
            return ensureLeadSentence(trimToLength(aiText.trim(), 600), items);
        }, AiResponseQualityGate::text);
        if (outcome.approved()) {
            String text = outcome.value();
            learningLoopService.recordSafe(LearningLoopEvent.builder()
                    .userId(userId)
                    .eventType(LearningEventType.AI_EXPLANATION_GENERATED)
                    .sourceType(LearningSourceType.WRONG_NOTE)
                    .sourceId(id)
                    .materialId(note.getSourceMaterialId())
                    .wrongNoteId(id)
                    .difficulty(note.getDifficulty())
                    .aiOutputSummary(text)
                    .userAction("REVIEW_NEEDED")
                    .build());
            note.setReviewNeededText(text);
            note.setReviewNeededQualityStatus(QUALITY_APPROVED);
            note.setReviewNeededAt(java.time.LocalDateTime.now());
            ensureRecommendation(note);
            reviewNoteRepository.save(note);
            out.put("reviewNeededText", text);
            out.put("recommendedReviewDate", note.getRecommendedReviewDate() != null ? note.getRecommendedReviewDate().toString() : null);
            out.put("recommendReviewInDays", note.getRecommendReviewInDays());
            out.put("cached", false);
            out.put("qualityStatus", QUALITY_APPROVED);
            out.put("qualityScore", outcome.decision().score());
            out.put("verified", true);
            return out;
        }
        if (upstreamFailed[0] && outcome.decision().attempts() <= 1) {
            // 기존 계약: AI 실패 시 데이터 기반 결정론 문장(AI 생성 아님). 게이트 ON 에서는 저장하지 않는다.
            out.put("reviewNeededText", buildReviewNeededFallback(sourceTitle, merged));
            out.put("cached", false);
            out.put("usedFallback", true);
            out.put("generatedBy", "rule");
            out.put("verified", false);
            return out;
        }
        GateDecision d = outcome.decision();
        log.info("[REVIEW_NOTE] review-needed 미승인 reviewNoteId={} status={} codes={} — 저장 안 함(기존 저장본 유지)",
                id, d.qualityStatus(), d.reasonCodes());
        Map<String, Object> fail = new LinkedHashMap<>(out);
        fail.putAll(d.failureBody(rid));
        fail.put("reviewNeededText", null);
        fail.put("cached", false);
        return fail;
    }

    /** 추천 복습일이 비어 있는 레거시 row 에 결정적 추천을 채운다(생성일 기준). 호출자가 save 한다. */
    private void ensureRecommendation(ReviewNote note) {
        if (note.getRecommendedReviewDate() != null) return;
        int cnt = (note.getWrongCount() == null ? 0 : note.getWrongCount())
                + (note.getUnansweredCount() == null ? 0 : note.getUnansweredCount());
        java.time.LocalDate base = note.getCreatedAt() != null ? note.getCreatedAt().toLocalDate() : java.time.LocalDate.now();
        LearningLoopService.ReviewRecommendation rec = LearningLoopService.computeReviewRecommendation(note.getDifficulty(), cnt, base);
        note.setRecommendReviewInDays(rec.days());
        note.setRecommendedReviewDate(rec.date());
        note.setReviewReason(rec.reason());
    }

    @SuppressWarnings({"rawtypes", "unchecked"})
    private String callReviewNeededAi(Long reviewNoteId, String sourceTitle, String difficultyKo,
                                      List<Map<String, Object>> items) {
        // 일반 채팅(/api/ai/multi-chat) 을 쓰지 않는다.
        //  - 그 경로는 대화 기억을 붙이므로 이전 문제 내용이 이번 분석에 섞일 수 있다.
        //  - 전용 엔드포인트는 현재 오답노트 데이터만 보고, 실패해도 200 + 데이터 기반 문장을 준다.
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("reviewNoteId", reviewNoteId);
        body.put("subject", sourceTitle);
        body.put("materialTitle", sourceTitle);
        body.put("difficulty", difficultyKo);
        body.put("questions", items);

        try {
            Map resp = fastApiWebClient.post().uri("/api/ai/review-needed")
                    .bodyValue(body).retrieve().bodyToMono(Map.class)
                    .block(Duration.ofSeconds(reviewTimeoutSeconds));
            if (resp == null) return null;
            Object text = resp.get("reviewNeededText");
            log.info("[REVIEW_NOTE] review-needed ai ok reviewNoteId={} generatedBy={} cases={}",
                    reviewNoteId, resp.get("generatedBy"), resp.get("cases"));
            return text == null ? null : text.toString();
        } catch (Exception e) {
            log.warn("[REVIEW_NOTE] review-needed ai unavailable reviewNoteId={} -> 폴백 cause={}",
                    reviewNoteId, e.getMessage());
            return null;
        }
    }

    private String buildReviewNeededPrompt(String sourceTitle, String difficultyKo, List<Map<String, Object>> items) {
        StringBuilder b = new StringBuilder();
        b.append("너는 대학생 학습자의 오답노트를 분석하는 학습 코치다.\n");
        b.append("아래 오답노트 정보를 바탕으로 학습자가 어떤 개념이 부족해서 복습이 필요한지 한국어로 500자 내외로 설명하라.\n\n");
        b.append("반드시 첫 문장은 다음 형식을 따른다.\n");
        b.append("\"{구체 개념명}에 대한 개념이 부족하여 복습이 필요합니다.\"\n\n");
        b.append("작성 규칙:\n1. {구체 개념명}은 과목명 전체가 아니라 문제에서 드러난 세부 개념으로 작성한다.\n");
        b.append("2. 사용자를 비난하지 않는다.\n3. 정답만 반복하지 않는다.\n4. 오답 원인, 부족 개념, 복습 순서를 포함한다.\n");
        b.append("5. 500자 내외로 작성한다.\n6. 불필요한 인사말, 제목, 마크다운은 쓰지 않는다.\n\n");
        b.append("[오답노트 정보]\n과목명: ").append(sourceTitle).append("\n원본 자료명: ").append(sourceTitle).append("\n난이도: ").append(difficultyKo).append("\n");
        int n = Math.min(items.size(), 5);
        for (int i = 0; i < n; i++) {
            Map<String, Object> q = items.get(i);
            b.append("\n문제").append(i + 1).append(": ").append(clip(asStr(q.get("question")), 300)).append("\n");
            b.append("보기: ").append(clip(joinChoices(q.get("choices")), 300)).append("\n");
            b.append("정답: ").append(clip(asStr(q.get("correct_answer")), 120)).append("\n");
            b.append("사용자 오답: ").append(clip(asStr(q.get("user_answer")), 120)).append("\n");
            b.append("기존 해설: ").append(clip(asStr(q.get("explanation")), 400)).append("\n");
            String concept = asStr(q.get("concept"));
            if (concept != null && !concept.isBlank()) b.append("관련 개념: ").append(clip(concept, 120)).append("\n");
        }
        return b.toString();
    }

    private String buildReviewNeededFallback(String sourceTitle, List<Map<String, Object>> items) {
        String concept = deriveConcept(items, sourceTitle);
        Map<String, Object> first = items.get(0);
        String userAns = asStr(first.get("user_answer"));
        String correct = asStr(first.get("correct_answer"));
        StringBuilder b = new StringBuilder();
        b.append(concept).append("에 대한 개념이 부족하여 복습이 필요합니다. ");
        // 재풀이 1회 결과가 있으면 그 사실을 문장에 반영한다(의미 없는 고정 문장 금지).
        Boolean retryCorrect = boolVal(first.get("retryCorrect"));
        if (retryCorrect != null) {
            b.append(retryCorrect
                    ? "다시 풀기에서는 정답을 골랐지만 최초 풀이에서 틀린 이유가 정리되지 않았다면 같은 개념에서 다시 흔들릴 수 있습니다. "
                    : "다시 풀기에서도 같은 문제를 정확히 해결하지 못해 개념 자체가 아직 정착되지 않은 상태입니다. ");
        }
        if (userAns != null && userAns.contains("미응답")) {
            b.append("일부 문제에 답하지 못한 것으로 보아 해당 개념을 떠올릴 단서가 충분히 정리되지 않은 상태입니다. ");
        } else if (correct != null && !correct.isBlank()) {
            b.append("정답과 다른 선택지를 고른 것으로 보아 비슷한 개념을 혼동하고 있을 가능성이 큽니다. ");
        } else {
            b.append("틀린 문제에서 핵심 개념을 정확히 적용하지 못한 것으로 보입니다. ");
        }
        b.append("먼저 ").append(sourceTitle).append(" 자료에서 해당 개념이 설명된 부분을 다시 읽고, ");
        b.append("정답과 내가 고른 답의 차이를 비교하며 왜 틀렸는지 한 줄로 정리해 보세요. ");
        b.append("그다음 기존 해설을 천천히 따라가며 개념의 정의와 적용 조건을 구분하고, ");
        b.append("마지막으로 유사문제를 다시 풀어 개념이 정착되었는지 확인하면 효과적으로 복습할 수 있습니다.");
        return trimToLength(b.toString(), 600);
    }

    private String ensureLeadSentence(String text, List<Map<String, Object>> items) {
        if (text == null || text.isBlank()) return text;
        String head = text.length() > 60 ? text.substring(0, 60) : text;
        if (head.contains("복습이 필요합니다")) return text;
        String concept = deriveConcept(items, "핵심 개념");
        return trimToLength(concept + "에 대한 개념이 부족하여 복습이 필요합니다. " + text, 600);
    }

    private String deriveConcept(List<Map<String, Object>> items, String fallback) {
        if (items != null) {
            for (Map<String, Object> q : items) {
                String c = asStr(q.get("concept"));
                if (c != null && !c.isBlank()) return clip(c.trim(), 40);
            }
        }
        if (fallback != null && !fallback.isBlank() && !fallback.equals("학습자료")) return clip(fallback.trim(), 40);
        return "핵심 개념";
    }

    private String joinChoices(Object choices) {
        if (!(choices instanceof List)) return "";
        StringBuilder sb = new StringBuilder();
        int i = 1;
        for (Object o : (List<?>) choices) {
            if (o == null) continue;
            if (sb.length() > 0) sb.append(" / ");
            sb.append(i++).append(") ").append(o);
        }
        return sb.toString();
    }

    private String clip(String s, int max) {
        if (s == null) return "";
        s = s.trim();
        return s.length() <= max ? s : s.substring(0, max) + "…";
    }

    private String trimToLength(String s, int max) {
        if (s == null) return "";
        if (s.length() <= max) return s;
        String cut = s.substring(0, max);
        int lastDot = Math.max(cut.lastIndexOf("."), Math.max(cut.lastIndexOf("다."), cut.lastIndexOf("요.")));
        if (lastDot > max / 2) return cut.substring(0, lastDot + 1);
        return cut.trim();
    }

    private String difficultyLabel(String difficulty) {
        if (difficulty == null) return "보통";
        switch (difficulty.trim().toLowerCase()) {
            case "easy": return "쉬움";
            case "hard": return "어려움";
            case "medium": case "normal": return "보통";
            default: return difficulty;
        }
    }

    @SuppressWarnings({"rawtypes", "unchecked"})
    private String flattenChatAnswer(Map resp) {
        if (resp == null) return null;
        String direct = asStr(resp.get("answer"));
        if (direct != null && !direct.isBlank()) return direct.trim();
        for (String key : new String[]{"replies", "answers", "revisedAnswers", "initialAnswers"}) {
            Object rows = resp.get(key);
            if (rows instanceof List) {
                StringBuilder sb = new StringBuilder();
                for (Object o : (List) rows) {
                    if (o instanceof Map) {
                        String a = firstNonBlank(asStr(((Map) o).get("answer")), asStr(((Map) o).get("content")), asStr(((Map) o).get("text")));
                        if (a != null && !a.isBlank()) { if (sb.length() > 0) sb.append("\n\n"); sb.append(a.trim()); }
                    } else if (o != null && !o.toString().isBlank()) {
                        if (sb.length() > 0) sb.append("\n\n"); sb.append(o);
                    }
                }
                if (sb.length() > 0) return sb.toString();
            }
        }
        String c = firstNonBlank(asStr(resp.get("content")), asStr(resp.get("text")));
        return (c == null || c.isBlank()) ? null : c.trim();
    }

    private ReviewNote loadOwnedStrict(Long userId, Long id) {
        ReviewNote note = reviewNoteRepository.findById(id)
                .orElseThrow(() -> new java.util.NoSuchElementException("오답노트를 찾을 수 없습니다."));
        if (!note.getUserId().equals(userId)) {
            throw new SecurityException("해당 오답노트에 대한 권한이 없습니다.");
        }
        return note;
    }

    // ---------------------------------------------------------------------
    // 유사문제: POST /api/review-notes/{id}/variant-question
    //   body { wrongQuestionId, difficulty: easy|normal|hard, count }
    //   ai07 variant 엔드포인트가 살아있으면 AI 변형, 없으면(404 등) 원본 오답을 재출제로 폴백.
    // ---------------------------------------------------------------------
    // ★ 클래스 기본 @Transactional(readOnly=true)를 read-write로 덮어쓴다. 폴백 경로가 항상
    //   recordSimilarQuestion(학습이벤트 write)을 호출하는데, readOnly 트랜잭션에서 write가
    //   일어나면 트랜잭션이 poison 되어 커밋 시 500이 났다(다른 write 메서드와 동일 패턴).
    @Transactional
    public Map<String, Object> variantQuestion(Long userId, Long id, Map<String, Object> body) {
        ReviewNote note = loadOwned(userId, id);

        int wrongQuestionId = intVal(body, "wrongQuestionId", 1);
        String difficulty = strVal(body, "difficulty", "normal");
        int count = Math.max(1, Math.min(5, intVal(body, "count", 1)));

        // 1) retryJson 에서 대상 오답 문제 조회 (wrongQuestionId 는 1-base)
        List<Map<String, Object>> retry = parseRetryQuestions(note.getRetryJson());
        Map<String, Object> base = (wrongQuestionId >= 1 && wrongQuestionId <= retry.size())
                ? retry.get(wrongQuestionId - 1)
                : (retry.isEmpty() ? null : retry.get(0));

        // 2) ai07 호출 시도
        Map<String, Object> req = new LinkedHashMap<>();
        req.put("review_note_id", id);
        req.put("difficulty", difficulty);
        req.put("count", count);
        if (base != null) {
            req.put("original_question", base.get("question"));
            req.put("choices", base.get("choices"));
            req.put("correct_answer", base.get("correct_answer"));
            req.put("explanation", base.get("explanation"));
        }
        if (gateOn()) {
            return variantQuestionGated(userId, note, id, wrongQuestionId, difficulty, count, retry, base, req);
        }
        Map aiResp = null;
        try {
            aiResp = fastApiWebClient.post().uri("/api/ai/review/variant-question")
                    .bodyValue(req).retrieve().bodyToMono(Map.class)
                    .block(Duration.ofSeconds(reviewTimeoutSeconds));
        } catch (Exception e) {
            log.warn("[REVIEW_NOTE] variant ai07 unavailable id={} cause={} -> 폴백", id, e.getMessage());
        }
        if (aiResp != null && aiResp.get("questions") instanceof List<?> firstRet) {
            log.info("[REVIEW_NOTE] variant ai first return id={} requested={} returned={}", id, count, firstRet.size());
        }
        // count 계약 top-up: AI 가 요청 수보다 적게 돌려주면(예: count=3 에 1개) 부족분만큼 최대 2회 더 요청해 채운다(문항 본문 기준 중복 제거).
        if (aiResp != null && aiResp.get("error_code") == null && aiResp.get("questions") instanceof List<?> firstList && firstList.size() < count) {
            List<Object> merged = new ArrayList<>(firstList);
            java.util.Set<String> seen = new java.util.HashSet<>();
            for (Object q : merged) seen.add(variantKey(q));
            for (int attempt = 0; attempt < 2 && merged.size() < count; attempt++) {
                Map<String, Object> topReq = new LinkedHashMap<>(req);
                topReq.put("count", count - merged.size());
                try {
                    Map more = fastApiWebClient.post().uri("/api/ai/review/variant-question")
                            .bodyValue(topReq).retrieve().bodyToMono(Map.class)
                            .block(Duration.ofSeconds(reviewTimeoutSeconds));
                    if (more == null || more.get("error_code") != null || !(more.get("questions") instanceof List<?> moreList)) break;
                    int before = merged.size();
                    for (Object q : moreList) { if (merged.size() >= count) break; if (seen.add(variantKey(q))) merged.add(q); }
                    if (merged.size() == before) break; // 새 문항이 없으면 중단
                } catch (Exception e) {
                    log.warn("[REVIEW_NOTE] variant top-up failed id={} attempt={} cause={}", id, attempt, e.getMessage());
                    break;
                }
            }
            // 그래도 부족하면 이 오답노트의 다른 오답 문제(원본)로 나머지를 채워 요청 수를 확정적으로 맞춘다(partialFallback 표시).
            if (merged.size() < count && !retry.isEmpty()) {
                int filled = 0;
                for (int i = 0; i < retry.size() && merged.size() < count; i++) {
                    int idx = ((wrongQuestionId - 1 + i) % retry.size() + retry.size()) % retry.size();
                    Map<String, Object> fq = fallbackQuestion(id, retry.get(idx), idx, difficulty,
                            "AI 가 요청한 문항 수만큼 변형하지 못해 원본 오답 문제로 채웠습니다.");
                    if (seen.add(variantKey(fq))) { merged.add(fq); filled++; }
                }
                if (filled > 0) { aiResp = new LinkedHashMap<>(aiResp); aiResp.put("partialFallback", true); }
            }
            aiResp = new LinkedHashMap<>(aiResp);
            aiResp.put("questions", merged);
            log.info("[REVIEW_NOTE] variant count contract id={} requested={} delivered={}", id, count, merged.size());
        }

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("reviewNoteId", id);
        out.put("difficulty", difficulty);
        if (aiResp != null && aiResp.get("error_code") == null && aiResp.get("questions") != null) {
            out.put("success", aiResp.get("questions") instanceof List<?> list && list.size() >= count);
            out.put("requestedCount", count);
            out.put("returnedCount", aiResp.get("questions") instanceof List<?> list ? Math.min(count, list.size()) : 0);
            if (!Boolean.TRUE.equals(out.get("success"))) out.put("message", "요청한 문항 수를 모두 생성하지 못했습니다. 다시 시도해 주세요.");
            out.put("usedFallback", false);
            if (Boolean.TRUE.equals(aiResp.get("partialFallback"))) out.put("partialFallback", true);
            // 요청 문항 수(count) 계약: AI 가 더 많이 돌려줘도 count 만큼만 응답한다(프론트 3 선택 → 응답 3).
            Object qsObj = aiResp.get("questions");
            if (qsObj instanceof List<?> qsList && qsList.size() > count) {
                qsObj = new ArrayList<>(qsList.subList(0, count));
            }
            out.put("questions", qsObj);
            recordSimilarQuestion(userId, id, note.getSourceMaterialId(), difficulty, false);
            return out;
        }
        // 3) 폴백: AI 변형 불가 시 이 오답노트의 오답 문제를 다시 출제.
        //    프론트 "유사문제 리스트"가 비지 않도록 count 만큼 서로 다른 오답을
        //    wrongQuestionId 부터 순환 선택해 반환한다(오답이 1개면 1개만).
        List<Map<String, Object>> questions = new ArrayList<>();
        if (!retry.isEmpty()) {
            int n = Math.min(count, retry.size());
            for (int i = 0; i < n; i++) {
                int idx = ((wrongQuestionId - 1 + i) % retry.size() + retry.size()) % retry.size();
                questions.add(fallbackQuestion(id, retry.get(idx), idx, difficulty,
                        "AI 변형을 일시적으로 사용할 수 없어 원본 오답 문제를 다시 출제했습니다."));
            }
        }
        out.put("success", questions.size() == count);
        out.put("requestedCount", count);
        out.put("returnedCount", questions.size());
        if (!Boolean.TRUE.equals(out.get("success"))) out.put("message", "요청한 문항 수를 모두 생성하지 못했습니다. 다시 시도해 주세요.");
        out.put("usedFallback", true);
        out.put("questions", questions);
        recordSimilarQuestion(userId, id, note.getSourceMaterialId(), difficulty, true);
        return out;
    }

    /**
     * 게이트 ON 유사문제: 한 시도 = ai07 호출 + 부족분 top-up(최대 2회)으로 모은 AI 문항(요청 수 이내).
     * 그 문항 전부(문제·보기·정답·해설·개념)를 SIMILAR_QUESTION(quiz_json, 원본 자료 원문 근거)으로 평가 → 거절 시 최대 2회 재생성
     * → 승인 문항만 응답. 부족분은 기존 계약대로 원본 오답 재출제(partialFallback)로 채운다(비AI, 해설은 본문 승인 시에만).
     * 거절/평가 불가는 success=false + errorCode + retryable, questions=[](초안 0). ai07 실패는 기존 원본 재출제 폴백.
     */
    @SuppressWarnings({"rawtypes", "unchecked"})
    private Map<String, Object> variantQuestionGated(Long userId, ReviewNote note, Long id, int wrongQuestionId, String difficulty,
                                                     int count, List<Map<String, Object>> retry, Map<String, Object> base,
                                                     Map<String, Object> req) {
        List<Map<String, Object>> visibleRetry = noteApproved(note) ? retry : redactRetryItems(retry);
        String rid = "vq-" + id + "-" + UUID.randomUUID().toString().substring(0, 8);
        StringBuilder ask = new StringBuilder("다음 오답 문제와 같은 개념을 묻는 난이도 ").append(difficulty).append(" 유사 4지선다 문제 ")
                .append(count).append("개를 만들어 주세요.");
        if (base != null) {
            ask.append("\n기존 문제: ").append(clip(asStr(base.get("question")), 600))
                    .append("\n보기: ").append(clip(joinChoices(base.get("choices")), 600))
                    .append("\n정답: ").append(clip(asStr(base.get("correct_answer")), 200));
        }
        AiResponseQualityGate.Spec spec = new AiResponseQualityGate.Spec(rid, ResponseQualityV1.TaskType.SIMILAR_QUESTION,
                ResponseQualityV1.OutputKind.QUIZ_JSON, ask.toString(),
                sourceEvidence(note.getSourceMaterialId(), ownedSourceText(userId, note.getSourceMaterialId())),
                materialConstraints(note.getSourceMaterialId()), null);
        final boolean[] upstreamFailed = new boolean[1];
        AiResponseQualityGate.Outcome<List<Object>> outcome = qualityGate.generateApproved(spec, (attempt, previous) -> {
            List<Object> qs = fetchVariantQuestions(id, req, count);
            if (qs == null || qs.isEmpty()) {
                upstreamFailed[0] = true;
                throw new AiResponseQualityGate.StopGeneration("GENERATION_FAILED");
            }
            return qs;
        }, qs -> {
            com.fasterxml.jackson.databind.node.ObjectNode root = MAPPER.createObjectNode();
            root.set("questions", MAPPER.valueToTree(qs));
            return root;
        });

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("reviewNoteId", id);
        out.put("difficulty", difficulty);
        if (outcome.approved()) {
            List<Object> merged = new ArrayList<>(outcome.value());
            java.util.Set<String> seen = new java.util.HashSet<>();
            for (Object q : merged) seen.add(variantKey(q));
            boolean filledAny = false;
            for (int i = 0; i < visibleRetry.size() && merged.size() < count; i++) {
                int idx = ((wrongQuestionId - 1 + i) % visibleRetry.size() + visibleRetry.size()) % visibleRetry.size();
                Map<String, Object> fq = fallbackQuestion(id, visibleRetry.get(idx), idx, difficulty,
                        "AI 가 요청한 문항 수만큼 변형하지 못해 원본 오답 문제로 채웠습니다.");
                if (seen.add(variantKey(fq))) { merged.add(fq); filledAny = true; }
            }
            out.put("success", merged.size() >= count);
            out.put("requestedCount", count);
            out.put("returnedCount", Math.min(count, merged.size()));
            if (merged.size() < count) out.put("message", "요청한 문항 수를 모두 생성하지 못했습니다. 다시 시도해 주세요.");
            out.put("usedFallback", false);
            if (filledAny) out.put("partialFallback", true);
            out.put("questions", merged.size() > count ? new ArrayList<>(merged.subList(0, count)) : merged);
            out.put("qualityStatus", QUALITY_APPROVED);
            out.put("qualityScore", outcome.decision().score());
            out.put("verified", true);
            recordSimilarQuestion(userId, id, note.getSourceMaterialId(), difficulty, false);
            return out;
        }
        if (upstreamFailed[0] && outcome.decision().attempts() <= 1) {
            // 기존 계약: AI 변형 불가 → 이 오답노트의 원본 오답 재출제(AI 생성 아님). 해설은 본문 승인 시에만 실린다.
            List<Map<String, Object>> questions = new ArrayList<>();
            int n = Math.min(count, visibleRetry.size());
            for (int i = 0; i < n; i++) {
                int idx = ((wrongQuestionId - 1 + i) % visibleRetry.size() + visibleRetry.size()) % visibleRetry.size();
                questions.add(fallbackQuestion(id, visibleRetry.get(idx), idx, difficulty,
                        "AI 변형을 일시적으로 사용할 수 없어 원본 오답 문제를 다시 출제했습니다."));
            }
            out.put("success", questions.size() == count);
            out.put("requestedCount", count);
            out.put("returnedCount", questions.size());
            if (questions.size() != count) out.put("message", "요청한 문항 수를 모두 생성하지 못했습니다. 다시 시도해 주세요.");
            out.put("usedFallback", true);
            out.put("questions", questions);
            recordSimilarQuestion(userId, id, note.getSourceMaterialId(), difficulty, true);
            return out;
        }
        GateDecision d = outcome.decision();
        log.info("[REVIEW_NOTE] variant 미승인 id={} status={} codes={} attempts={} — 문항 미노출", id, d.qualityStatus(), d.reasonCodes(),
                d.attempts());
        out.putAll(d.failureBody(rid));
        out.put("requestedCount", count);
        out.put("returnedCount", 0);
        out.put("usedFallback", false);
        out.put("questions", List.of());
        return out;
    }

    /** 게이트 시도 1회분 AI 유사문제: 최초 호출 + 부족분 top-up(최대 2회, 본문 중복 제거). ai07 실패/빈 결과면 null. */
    @SuppressWarnings({"rawtypes", "unchecked"})
    private List<Object> fetchVariantQuestions(Long id, Map<String, Object> req, int count) {
        Map aiResp;
        try {
            aiResp = fastApiWebClient.post().uri("/api/ai/review/variant-question")
                    .bodyValue(req).retrieve().bodyToMono(Map.class)
                    .block(Duration.ofSeconds(reviewTimeoutSeconds));
        } catch (Exception e) {
            log.warn("[REVIEW_NOTE] variant(gated) ai07 unavailable id={} cause={}", id, e.getMessage());
            return null;
        }
        if (aiResp == null || aiResp.get("error_code") != null || !(aiResp.get("questions") instanceof List<?> first)) {
            return null;
        }
        List<Object> merged = new ArrayList<>();
        java.util.Set<String> seen = new java.util.HashSet<>();
        for (Object q : first) { if (merged.size() >= count) break; if (seen.add(variantKey(q))) merged.add(q); }
        for (int attempt = 0; attempt < 2 && merged.size() < count; attempt++) {
            Map<String, Object> topReq = new LinkedHashMap<>(req);
            topReq.put("count", count - merged.size());
            try {
                Map more = fastApiWebClient.post().uri("/api/ai/review/variant-question")
                        .bodyValue(topReq).retrieve().bodyToMono(Map.class)
                        .block(Duration.ofSeconds(reviewTimeoutSeconds));
                if (more == null || more.get("error_code") != null || !(more.get("questions") instanceof List<?> moreList)) break;
                int before = merged.size();
                for (Object q : moreList) { if (merged.size() >= count) break; if (seen.add(variantKey(q))) merged.add(q); }
                if (merged.size() == before) break;
            } catch (Exception e) {
                log.warn("[REVIEW_NOTE] variant(gated) top-up failed id={} attempt={} cause={}", id, attempt, e.getMessage());
                break;
            }
        }
        return merged;
    }

    // 학습 왕복 루프: 유사문제 생성 이벤트(원본 오답노트와 연결)
    private void recordSimilarQuestion(Long userId, Long reviewNoteId, Long materialId, String difficulty, boolean fallback) {
        learningLoopService.recordSafe(LearningLoopEvent.builder()
                .userId(userId)
                .eventType(LearningEventType.SIMILAR_QUESTION_GENERATED)
                .sourceType(LearningSourceType.WRONG_NOTE)
                .sourceId(reviewNoteId)
                .materialId(materialId)
                .wrongNoteId(reviewNoteId)
                .difficulty(difficulty)
                .aiOutputSummary("유사문제 생성" + (fallback ? "(원본 재출제 폴백)" : ""))
                .userAction("SIMILAR_QUESTION")
                .build());
    }

    // ---------------------------------------------------------------------
    // 다시 풀기(문제당 정확히 1회) 결과 저장 / 병합
    //   재풀이는 1회뿐이다. 시도 횟수·힌트 같은 필드는 만들지 않는다.
    // ---------------------------------------------------------------------
    @Transactional
    public Map<String, Object> submitRetryResult(Long userId, Long id, Map<String, Object> body) {
        ReviewNote note = loadOwnedStrict(userId, id);
        List<Map<String, Object>> incoming = extractRetryResults(body);
        if (incoming.isEmpty()) {
            throw new IllegalArgumentException("다시 풀기 결과가 비어 있습니다.");
        }
        List<Map<String, Object>> questions = parseRetryQuestions(note.getRetryJson());

        Map<Integer, Map<String, Object>> saved = new LinkedHashMap<>();
        for (Map<String, Object> r : parseRetryResults(note.getRetryResultJson())) {
            saved.put(intVal(r, "index", 0), r);
        }
        int stored = 0;
        for (Map<String, Object> r : incoming) {
            int index = intVal(r, "index", 0);
            if (index <= 0 || index > questions.size()) continue;
            // 재풀이는 1회다. 이미 기록이 있으면 덮어쓰지 않는다.
            if (saved.containsKey(index)) continue;
            Map<String, Object> q = questions.get(index - 1);
            String userAnswer = asStr(r.get("userAnswer"));
            Boolean correct = boolVal(r.get("correct"));
            if (correct == null) {
                correct = userAnswer != null && !userAnswer.isBlank()
                        && userAnswer.trim().equals(asStr(q.get("correct_answer")) == null
                            ? "" : asStr(q.get("correct_answer")).trim());
            }
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("index", index);
            row.put("userAnswer", (userAnswer == null || userAnswer.isBlank()) ? "미응답" : userAnswer);
            row.put("correct", correct);
            row.put("answeredAt", java.time.LocalDateTime.now().toString());
            saved.put(index, row);
            stored++;
        }
        try {
            note.setRetryResultJson(MAPPER.writeValueAsString(new ArrayList<>(saved.values())));
            reviewNoteRepository.save(note);
        } catch (Exception e) {
            log.warn("[REVIEW_NOTE] retry 결과 저장 실패 reviewNoteId={} msg={}", id, e.getMessage());
            throw new IllegalStateException("다시 풀기 결과를 저장하지 못했습니다.");
        }
        log.info("[REVIEW_NOTE] retry 결과 저장 reviewNoteId={} stored={} total={}/{}",
                id, stored, saved.size(), questions.size());

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("reviewNoteId", id);
        out.put("retryResults", new ArrayList<>(saved.values()));
        out.put("completed", saved.size());
        out.put("total", questions.size());
        return out;
    }

    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> extractRetryResults(Map<String, Object> body) {
        List<Map<String, Object>> out = new ArrayList<>();
        if (body == null) return out;
        Object results = body.get("results");
        if (results instanceof List<?> list) {
            for (Object o : list) if (o instanceof Map) out.add((Map<String, Object>) o);
            return out;
        }
        if (body.get("index") != null) out.add(body);
        return out;
    }

    private List<Map<String, Object>> parseRetryResults(String json) {
        List<Map<String, Object>> out = new ArrayList<>();
        if (json == null || json.isBlank()) return out;
        try {
            JsonNode arr = MAPPER.readTree(json);
            if (arr.isArray()) for (JsonNode n : arr) out.add(MAPPER.convertValue(n, Map.class));
        } catch (Exception e) {
            log.warn("[REVIEW_NOTE] retryResult parse fail msg={}", e.getMessage());
        }
        return out;
    }

    /** 최초 풀이 문제 + 재풀이 1회 결과를 ai07 review-needed 계약으로 합친다. */
    private List<Map<String, Object>> mergeRetryResults(List<Map<String, Object>> questions, String retryResultJson) {
        Map<Integer, Map<String, Object>> results = new LinkedHashMap<>();
        for (Map<String, Object> r : parseRetryResults(retryResultJson)) {
            results.put(intVal(r, "index", 0), r);
        }
        List<Map<String, Object>> out = new ArrayList<>();
        for (int i = 0; i < questions.size(); i++) {
            Map<String, Object> q = questions.get(i);
            Map<String, Object> m = new LinkedHashMap<>(q);
            String first = asStr(q.get("user_answer"));
            m.put("firstAnswer", first == null ? "" : first);
            // 오답노트에 실린 문제는 정의상 최초 오답 또는 미응답이다.
            m.put("firstCorrect", false);
            Map<String, Object> r = results.get(i + 1);
            if (r != null) {
                m.put("retryAnswer", asStr(r.get("userAnswer")));
                Boolean c = boolVal(r.get("correct"));
                m.put("retryCorrect", c != null && c);
            }
            out.add(m);
        }
        return out;
    }

    private Boolean boolVal(Object v) {
        if (v == null) return null;
        if (v instanceof Boolean b) return b;
        String t = v.toString().trim().toLowerCase();
        if (t.equals("true") || t.equals("1") || t.equals("정답")) return true;
        if (t.equals("false") || t.equals("0") || t.equals("오답")) return false;
        return null;
    }

    private List<Map<String, Object>> parseRetryQuestions(String retryJson) {
        List<Map<String, Object>> out = new ArrayList<>();
        if (retryJson == null || retryJson.isBlank()) return out;
        try {
            JsonNode arr = MAPPER.readTree(retryJson);
            if (arr.isArray()) for (JsonNode n : arr) out.add(MAPPER.convertValue(n, Map.class));
        } catch (Exception e) {
            log.warn("[REVIEW_NOTE] variant retry parse fail id-json msg={}", e.getMessage());
        }
        return out;
    }

    private int intVal(Map<String, Object> m, String k, int dflt) {
        if (m == null || m.get(k) == null) return dflt;
        Object v = m.get(k);
        if (v instanceof Number) return ((Number) v).intValue();
        try { return Integer.parseInt(v.toString().trim()); } catch (Exception e) { return dflt; }
    }

    private String strVal(Map<String, Object> m, String k, String dflt) {
        if (m == null || m.get(k) == null) return dflt;
        String v = m.get(k).toString().trim();
        // 하/중/상 한글도 허용
        if (v.equals("하")) return "easy";
        if (v.equals("중")) return "normal";
        if (v.equals("상")) return "hard";
        return v.isBlank() ? dflt : v;
    }

    // ---------------------------------------------------------------------
    // 내부 헬퍼
    // ---------------------------------------------------------------------
    private ReviewNote loadOwned(Long userId, Long id) {
        return reviewNoteRepository.findByReviewNoteIdAndUserId(id, userId)
                .orElseThrow(() -> new IllegalArgumentException("오답노트를 찾을 수 없습니다."));
    }

    private ReviewNoteDTO toDTO(ReviewNote n, boolean withPresign) {
        int wrong = n.getWrongCount() == null ? 0 : n.getWrongCount();
        int unanswered = n.getUnansweredCount() == null ? 0 : n.getUnansweredCount();
        // 복습 필요/일정 상태는 DB(review_notes + todos) 기준으로 계산한다. 레거시 row(추천일 null)는 조회 시 결정적으로 보정(저장은 안 함).
        java.time.LocalDate recDate = n.getRecommendedReviewDate();
        Integer recDays = n.getRecommendReviewInDays();
        String recReason = n.getReviewReason();
        if (recDate == null) {
            java.time.LocalDate base = n.getCreatedAt() != null ? n.getCreatedAt().toLocalDate() : java.time.LocalDate.now();
            LearningLoopService.ReviewRecommendation rec = LearningLoopService.computeReviewRecommendation(n.getDifficulty(), wrong + unanswered, base);
            recDate = rec.date(); recDays = rec.days(); recReason = rec.reason();
        }
        java.util.List<com.studybridge.api.entity.Todo> sched = todoRepository
                .findByUserIdAndSourceTypeAndSourceIdOrderByScheduleDateDesc(n.getUserId(), "REVIEW_NOTE", n.getReviewNoteId());
        com.studybridge.api.entity.Todo latest = sched.isEmpty() ? null : sched.get(0);
        boolean scheduled = latest != null;
        boolean completed = latest != null && Boolean.TRUE.equals(latest.getCompleted());
        boolean needed = !recDate.isAfter(java.time.LocalDate.now()) && !completed;
        // 게이트 ON: 미승인 AI 필드만 가린다 — PDF(해설·개념 포함)는 본문 승인, reviewNeededText 는 분석 승인 기준.
        boolean gated = gateOn();
        boolean bodyRedacted = gated && !noteApproved(n);
        boolean rnRedacted = gated && n.getReviewNeededText() != null && !n.getReviewNeededText().isBlank()
                && !QUALITY_APPROVED.equals(n.getReviewNeededQualityStatus());
        return ReviewNoteDTO.builder()
                .qualityStatus(gated ? n.getQualityStatus() : null)
                .qualityRedacted(gated ? (bodyRedacted || rnRedacted) : null)
                .qualityNotice(gated && (bodyRedacted || rnRedacted) ? QUALITY_NOTICE : null)
                .recommendReviewInDays(recDays)
                .recommendedReviewDate(recDate)
                .reviewReason(recReason)
                .reviewNeededText(rnRedacted ? null : n.getReviewNeededText())
                .reviewNeeded(needed)
                .reviewScheduled(scheduled)
                .reviewTodoId(latest != null ? latest.getId() : null)
                .reviewScheduledDate(latest != null ? latest.getScheduleDate() : null)
                .reviewCompleted(completed)
                .id(n.getReviewNoteId())
                .title(n.getTitle())
                .sourceName(n.getSourceTitle())
                .originalMaterialTitle(n.getSourceTitle())
                .sourceMaterialId(n.getSourceMaterialId())
                .quizId(n.getQuizId())
                .archiveMaterialId(n.getArchiveMaterialId())
                .wrongCount(wrong)
                .unansweredCount(unanswered)
                .reviewCount(wrong + unanswered)
                .difficulty(n.getDifficulty())
                .memo(n.getMemo())
                .aiStatus(n.getAiStatus())
                .pdfUrl(withPresign && !bodyRedacted ? presign(n) : null)
                .downloadUrl("/api/review-notes/" + n.getReviewNoteId() + "/download")
                .createdAt(n.getCreatedAt())
                .build();
    }

    private String presign(ReviewNote n) {
        if (n.getS3Key() == null || n.getS3Key().isBlank()) return null;
        try {
            return s3Service.getPresignedUrl(n.getS3Key(), n.getTitle() + ".pdf");
        } catch (Exception e) {
            log.warn("[REVIEW_NOTE] presign fail id={} msg={}", n.getReviewNoteId(), e.getMessage());
            return null;
        }
    }

    private String mapDifficulty(String difficulty) {
        if (difficulty == null) return "medium";
        String v = difficulty.trim();
        if (v.contains("쉬") || v.equalsIgnoreCase("easy")) return "easy";
        if (v.contains("어려") || v.equalsIgnoreCase("hard")) return "hard";
        return "medium";
    }

    private String safeTitle(String title) {
        if (title == null || title.isBlank()) return "학습자료";
        return title.replaceAll("[\\\\/:*?\"<>|]", " ").trim();
    }

    private String optionAt(List<String> options, Integer idx) {
        if (options == null || idx == null || idx < 0 || idx >= options.size()) return "";
        return options.get(idx);
    }

    private Integer answerIndexFor(Map<String, Object> answers, int idx) {
        if (answers == null) return null;
        Object v = answers.get(String.valueOf(idx));
        if (v == null) v = answers.get(idx);
        if (v == null) return null;
        if (v instanceof Number) return ((Number) v).intValue();
        try { return Integer.parseInt(v.toString().trim()); } catch (Exception e) { return null; }
    }

    private List<ParsedQuestion> parseQuizData(String quizData) {
        List<ParsedQuestion> result = new ArrayList<>();
        if (quizData == null || quizData.isBlank()) return result;
        try {
            JsonNode root = MAPPER.readTree(quizData);
            JsonNode arr = null;
            if (root.isArray()) arr = root;
            else if (root.has("quizzes")) arr = root.get("quizzes");
            else if (root.has("questions")) arr = root.get("questions");
            else if (root.has("quizData") && root.get("quizData").isTextual()) {
                JsonNode inner = MAPPER.readTree(root.get("quizData").asText());
                arr = inner.isArray() ? inner : (inner.has("quizzes") ? inner.get("quizzes") : inner.get("questions"));
            }
            if (arr == null || !arr.isArray()) return result;

            for (JsonNode node : arr) {
                List<String> options = readOptions(node);
                Integer correct = readCorrectIndex(node, options);
                String question = textOf(node, "question", textOf(node, "q", "문제"));
                String explanation = textOf(node, "explanation", "");
                int page = readPage(node);
                result.add(new ParsedQuestion(question, options, correct, explanation, page));
            }
        } catch (Exception e) {
            log.warn("[REVIEW_NOTE] quizData parse fail: {}", e.getMessage());
        }
        return result;
    }

    private List<String> readOptions(JsonNode node) {
        JsonNode opts = node.has("options") ? node.get("options")
                : node.has("choices") ? node.get("choices")
                : node.get("answers");
        List<String> out = new ArrayList<>();
        if (opts != null && opts.isArray()) {
            for (JsonNode o : opts) {
                if (o.isTextual()) out.add(o.asText());
                else if (o.has("text")) out.add(o.get("text").asText());
                else if (o.has("content")) out.add(o.get("content").asText());
                else if (o.has("option")) out.add(o.get("option").asText());
                else out.add(o.asText());
            }
        }
        return out;
    }

    private Integer readCorrectIndex(JsonNode node, List<String> options) {
        if (node.has("answerIndex") && node.get("answerIndex").isInt()) return node.get("answerIndex").asInt();
        JsonNode ans = node.get("answer");
        if (ans != null) {
            if (ans.isInt()) return ans.asInt();
            if (ans.isTextual() && options.contains(ans.asText())) return options.indexOf(ans.asText());
        }
        JsonNode ca = node.get("correctAnswer");
        if (ca != null) {
            if (ca.isInt()) return ca.asInt();
            if (ca.isTextual() && options.contains(ca.asText())) return options.indexOf(ca.asText());
        }
        JsonNode cas = node.get("correct_answer");
        if (cas != null) {
            if (cas.isInt()) return cas.asInt();
            if (cas.isTextual() && options.contains(cas.asText())) return options.indexOf(cas.asText());
        }
        return 0;
    }

    private String textOf(JsonNode node, String key, String dflt) {
        if (node.has(key) && !node.get(key).isNull()) return node.get(key).asText();
        return dflt;
    }

    private int readPage(JsonNode node) {
        for (String k : new String[]{"page", "pageNumber", "page_number", "pageNo"}) {
            if (node.has(k) && !node.get(k).isNull()) {
                JsonNode v = node.get(k);
                if (v.isInt()) return v.asInt();
                try { return Integer.parseInt(v.asText().trim()); } catch (Exception ignore) {}
            }
        }
        return 0;
    }

    // ---------------- 검색/미리보기용 평문(자료보관함 extractedText) ----------------
    private String buildFallbackPlainText(String noteTitle, String sourceTitle, String difficultyKo, String createdDate,
                                          int wrongCount, int unansweredCount, String overallFeedback, List<WrongItem> items) {
        String src = (sourceTitle == null || sourceTitle.isBlank()) ? "학습자료" : sourceTitle;
        StringBuilder sb = new StringBuilder();
        sb.append(noteTitle).append("\n");
        sb.append("자료명: ").append(src).append("\n");
        sb.append("난이도: ").append(difficultyKo).append("\n");
        sb.append("생성일: ").append(createdDate).append("\n");
        sb.append("오답 수: ").append(wrongCount).append("\n");
        sb.append("미응답 수: ").append(unansweredCount).append("\n");
        sb.append("복습 필요 수: ").append(wrongCount + unansweredCount).append("\n\n");
        sb.append("전체 피드백: ").append(nz(overallFeedback)).append("\n\n");
        int i = 1;
        for (WrongItem w : items) {
            sb.append(i++).append(". 문제: ").append(nz(w.question)).append("\n");
            sb.append("내가 고른 답: ").append(w.unanswered ? "미응답" : optionAt(w.options, w.selectedIndex)).append("\n");
            sb.append("정답: ").append(optionAt(w.options, w.correctIndex)).append("\n");
            sb.append("해설: ").append(explanationOf(w)).append("\n");
            if (w.concept != null && !w.concept.isBlank()) sb.append("다시 봐야 할 개념: ").append(w.concept).append("\n");
            if (w.page > 0) sb.append("참고 페이지: ").append(w.page).append("p\n");
            sb.append("\n");
        }
        return sb.toString();
    }

    private String explanationOf(WrongItem w) {
        return (w.explanation == null || w.explanation.isBlank())
                ? "해설 정보가 없습니다. 자료의 해당 개념을 다시 확인하세요." : w.explanation;
    }

    private String buildRetryJsonFromWrong(List<WrongItem> items) {
        try {
            ArrayNode out = MAPPER.createArrayNode();
            for (WrongItem w : items) {
                com.fasterxml.jackson.databind.node.ObjectNode n = MAPPER.createObjectNode();
                n.put("question", nz(w.question));
                ArrayNode ch = MAPPER.createArrayNode();
                if (w.options != null) for (String o : w.options) ch.add(o);
                n.set("choices", ch);
                n.put("correct_answer", optionAt(w.options, w.correctIndex));
                n.put("user_answer", w.unanswered ? "미응답" : optionAt(w.options, w.selectedIndex));
                n.put("status", w.unanswered ? "UNANSWERED" : "WRONG");
                n.put("explanation", explanationOf(w));
                if (w.concept != null) n.put("concept", w.concept);
                if (w.page > 0) n.put("page", w.page);
                out.add(n);
            }
            return MAPPER.writeValueAsString(out);
        } catch (Exception e) {
            return "[]";
        }
    }

    private String nz(String s) { return s == null ? "" : s; }

    // ---------------- PDF 생성 (OpenPDF + NanumGothic, 카드형 레이아웃) ----------------
    //  - 제목(초록) → 상단 메타 박스(자료명/난이도/생성일/오답·미응답·복습필요 수) → 전체 피드백
    //  - 문제별 카드: 문제 / 내가 고른 답(빨강·미응답) / 정답(초록) / 해설 / 다시 봐야 할 개념 / 참고 페이지
    private static final Color C_GREEN = new Color(21, 128, 61);
    private static final Color C_GREEN_BG = new Color(236, 253, 245);
    private static final Color C_RED = new Color(185, 28, 28);
    private static final Color C_RED_BG = new Color(254, 242, 242);
    private static final Color C_AMBER = new Color(146, 64, 14);
    private static final Color C_AMBER_BG = new Color(255, 251, 235);
    private static final Color C_TEXT = new Color(31, 41, 55);
    private static final Color C_MUTED = new Color(107, 114, 128);
    private static final Color C_BORDER = new Color(229, 231, 235);
    private static final Color C_BOX_BG = new Color(247, 248, 250);

    // ---- A4 학습지 레이아웃 상수 (단위: pt, 1mm≈2.8346pt) ----
    private static final float MM = 2.834645f;
    private static final float PAGE_MARGIN = 10f * MM;   // 여백 ≈10mm
    private static final float MAIN_MIN_H = 540f;        // 문제/풀이 영역 최소 높이
    private static final float MEMO_MIN_H = 150f;        // 메모 영역 최소 높이
    private static final float GRID_STEP = 6f * MM;      // 모눈 간격 6mm
    private static final GridBackground GRID_BG = new GridBackground();

    /** 셀 영역에 연한 모눈 배경을 그린다(배경 캔버스 → 텍스트/테두리 아래에 깔림). */
    private static class GridBackground implements com.lowagie.text.pdf.PdfPCellEvent {
        private static final Color GRID = new Color(214, 219, 226);
        @Override
        public void cellLayout(com.lowagie.text.pdf.PdfPCell cell, com.lowagie.text.Rectangle pos,
                               com.lowagie.text.pdf.PdfContentByte[] canvases) {
            com.lowagie.text.pdf.PdfContentByte cb = canvases[com.lowagie.text.pdf.PdfPTable.BACKGROUNDCANVAS];
            cb.saveState();
            cb.setColorStroke(GRID);
            cb.setLineWidth(0.4f);
            for (float x = pos.getLeft() + GRID_STEP; x < pos.getRight() - 1f; x += GRID_STEP) {
                cb.moveTo(x, pos.getBottom()); cb.lineTo(x, pos.getTop());
            }
            for (float y = pos.getBottom() + GRID_STEP; y < pos.getTop() - 1f; y += GRID_STEP) {
                cb.moveTo(pos.getLeft(), y); cb.lineTo(pos.getRight(), y);
            }
            cb.stroke();
            cb.restoreState();
        }
    }

    // A4 세로 학습지. 틀린 문제 1개당 한 장: [상단 헤더] / [문제 | 풀이 2분할(모눈)] / [하단 메모(모눈)].
    private byte[] buildPdf(String noteTitle, String sourceTitle, String difficultyKo, String createdDate,
                            int wrongCount, int unansweredCount, String overallFeedback, List<WrongItem> items) {
        try (ByteArrayOutputStream baos = new ByteArrayOutputStream()) {
            Document doc = new Document(PageSize.A4, PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN);
            PdfWriter.getInstance(doc, baos);
            doc.open();
            BaseFont base = BaseFont.createFont("NanumGothic.ttf", BaseFont.IDENTITY_H,
                    BaseFont.EMBEDDED, BaseFont.CACHED, fontBytes(), null);

            String src = (sourceTitle == null || sourceTitle.isBlank()) ? "학습자료" : sourceTitle;
            int total = (items == null) ? 0 : items.size();

            if (total == 0) {
                // 안전장치: 항목이 없어도 빈 학습지 한 장(헤더/2분할/메모)을 보장한다.
                doc.add(buildHeaderBox(base, createdDate, src, difficultyKo, wrongCount, unansweredCount, 0, 0));
                doc.add(buildMainSplit(base, 0, null, overallFeedback));
                doc.add(buildMemoBox(base));
                doc.close();
                return baos.toByteArray();
            }

            for (int i = 0; i < total; i++) {
                if (i > 0) doc.newPage();   // 문제마다 A4 한 장
                WrongItem w = items.get(i);
                doc.add(buildHeaderBox(base, createdDate, src, difficultyKo, wrongCount, unansweredCount, i + 1, total));
                // 전체 피드백은 동일 내용이므로 첫 장 풀이 영역에만 싣는다.
                doc.add(buildMainSplit(base, i + 1, w, i == 0 ? overallFeedback : null));
                doc.add(buildMemoBox(base));
            }

            doc.close();
            return baos.toByteArray();
        } catch (Exception e) {
            throw new RuntimeException("오답노트 PDF 생성에 실패했습니다.", e);
        }
    }

    // 상단 헤더: "{자료명} 오답노트" + 날짜 / 난이도 / 틀린 문제 수 / 문항 번호
    private com.lowagie.text.pdf.PdfPTable buildHeaderBox(BaseFont base, String date, String src, String diff,
                                                          int wrongCount, int unansweredCount, int no, int total) {
        com.lowagie.text.pdf.PdfPTable h = new com.lowagie.text.pdf.PdfPTable(1);
        h.setWidthPercentage(100);
        h.setSpacingAfter(8f);
        com.lowagie.text.pdf.PdfPCell c = new com.lowagie.text.pdf.PdfPCell();
        c.setBorder(com.lowagie.text.Rectangle.BOTTOM);
        c.setBorderWidthBottom(2f);
        c.setBorderColorBottom(C_GREEN);
        c.setPaddingTop(2f);
        c.setPaddingBottom(8f);
        Paragraph title = new Paragraph(src + " 오답노트", new Font(base, 17, Font.BOLD, C_GREEN));
        c.addElement(title);
        Paragraph m = new Paragraph();
        m.setSpacingBefore(6f);
        addMeta(base, m, "날짜", date);
        addMeta(base, m, "난이도", diff);
        addMeta(base, m, "틀린 문제 수", (wrongCount + unansweredCount) + "문제");
        if (total > 0) addMeta(base, m, "문항", no + " / " + total);
        c.addElement(m);
        h.addCell(c);
        return h;
    }

    private void addMeta(BaseFont base, Paragraph p, String label, String value) {
        p.add(new com.lowagie.text.Chunk(label + " ", new Font(base, 10, Font.BOLD, C_MUTED)));
        p.add(new com.lowagie.text.Chunk(nz(value).isBlank() ? "-" : value, new Font(base, 10, Font.BOLD, C_TEXT)));
        p.add(new com.lowagie.text.Chunk("        ", new Font(base, 10, Font.NORMAL, C_MUTED)));
    }

    // 중단 2분할: 좌(문제) / 우(풀이). 둘 다 연한 모눈 배경, 같은 높이로 채워진다.
    private com.lowagie.text.pdf.PdfPTable buildMainSplit(BaseFont base, int no, WrongItem w, String overallFeedback) {
        com.lowagie.text.pdf.PdfPTable main = new com.lowagie.text.pdf.PdfPTable(2);
        main.setWidthPercentage(100);
        try { main.setWidths(new float[]{1f, 1f}); } catch (Exception ignore) {}
        main.setSplitLate(false);   // 내용이 길어 넘치면 다음 페이지로 이어지게(잘림 방지)
        main.addCell(problemCell(base, no, w));
        main.addCell(solutionCell(base, w, overallFeedback));
        return main;
    }

    private com.lowagie.text.pdf.PdfPCell gridCell() {
        com.lowagie.text.pdf.PdfPCell c = new com.lowagie.text.pdf.PdfPCell();
        c.setMinimumHeight(MAIN_MIN_H);
        c.setPadding(11f);
        c.setBorderColor(C_BORDER);
        c.setBorderWidth(1f);
        c.setCellEvent(GRID_BG);   // 모눈 배경(셀 배경색은 지정하지 않아야 모눈이 보인다)
        return c;
    }

    // 좌측 문제 영역: 문제 번호 / 문제 본문 / 보기 / 내가 고른 답
    private com.lowagie.text.pdf.PdfPCell problemCell(BaseFont base, int no, WrongItem w) {
        com.lowagie.text.pdf.PdfPCell c = gridCell();
        Paragraph area = new Paragraph("문제", new Font(base, 11, Font.BOLD, C_GREEN));
        area.setSpacingAfter(8f);
        c.addElement(area);
        if (w != null) {
            Paragraph head = new Paragraph();
            head.add(new com.lowagie.text.Chunk("문제 " + no, new Font(base, 10.5f, Font.BOLD, C_TEXT)));
            head.add(new com.lowagie.text.Chunk(w.unanswered ? "  [미응답]" : "  [오답]",
                    new Font(base, 9.5f, Font.BOLD, w.unanswered ? C_AMBER : C_RED)));
            head.setSpacingAfter(5f);
            c.addElement(head);

            Paragraph q = new Paragraph(nz(w.question), new Font(base, 11, Font.BOLD, C_TEXT));
            q.setLeading(15f);
            q.setSpacingAfter(8f);
            c.addElement(q);

            if (w.options != null && !w.options.isEmpty()) {
                Paragraph ol = new Paragraph("보기", new Font(base, 9.5f, Font.BOLD, C_MUTED));
                ol.setSpacingAfter(3f);
                c.addElement(ol);
                String[] marks = {"①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧"};
                for (int k = 0; k < w.options.size(); k++) {
                    String mark = k < marks.length ? marks[k] : (k + 1) + ".";
                    boolean mine = w.selectedIndex != null && w.selectedIndex == k;
                    Paragraph op = new Paragraph();
                    op.add(new com.lowagie.text.Chunk(mark + " " + nz(w.options.get(k)),
                            new Font(base, 10, Font.NORMAL, C_TEXT)));
                    if (mine) op.add(new com.lowagie.text.Chunk("  (내 선택)", new Font(base, 9, Font.BOLD, C_RED)));
                    op.setLeading(14f);
                    c.addElement(op);
                }
            }
            com.lowagie.text.pdf.PdfPTable mineLine = answerLine(base, "내가 고른 답",
                    w.unanswered ? "미응답" : optionAt(w.options, w.selectedIndex),
                    w.unanswered ? C_AMBER : C_RED, w.unanswered ? C_AMBER_BG : C_RED_BG);
            mineLine.setSpacingBefore(8f);
            c.addElement(mineLine);
        }
        return c;
    }

    // 우측 풀이 영역: 정답 / AI 해설 / 핵심 개념·다시 볼 포인트 / (첫 장) 전체 피드백
    private com.lowagie.text.pdf.PdfPCell solutionCell(BaseFont base, WrongItem w, String overallFeedback) {
        Font fLabel = new Font(base, 9.5f, Font.BOLD, C_MUTED);
        Font fBody = new Font(base, 10, Font.NORMAL, C_TEXT);

        com.lowagie.text.pdf.PdfPCell c = gridCell();
        Paragraph area = new Paragraph("풀이", new Font(base, 11, Font.BOLD, C_GREEN));
        area.setSpacingAfter(8f);
        c.addElement(area);
        if (w != null) {
            c.addElement(answerLine(base, "정답", optionAt(w.options, w.correctIndex), C_GREEN, C_GREEN_BG));

            Paragraph expLabel = new Paragraph("AI 해설", fLabel);
            expLabel.setSpacingBefore(8f);
            expLabel.setSpacingAfter(2f);
            c.addElement(expLabel);
            Paragraph exp = new Paragraph(explanationOf(w), fBody);
            exp.setLeading(15f);
            c.addElement(exp);

            if (w.concept != null && !w.concept.isBlank()) {
                Paragraph cl = new Paragraph("핵심 개념 · 다시 볼 포인트", fLabel);
                cl.setSpacingBefore(8f);
                cl.setSpacingAfter(2f);
                c.addElement(cl);
                Paragraph cv = new Paragraph(w.concept, fBody);
                cv.setLeading(14f);
                c.addElement(cv);
            }
            if (w.page > 0) {
                Paragraph pg = new Paragraph("참고 페이지: " + w.page + "p", new Font(base, 9, Font.NORMAL, C_MUTED));
                pg.setSpacingBefore(6f);
                c.addElement(pg);
            }
        }
        if (overallFeedback != null && !overallFeedback.isBlank()) {
            Paragraph fl = new Paragraph("전체 피드백", fLabel);
            fl.setSpacingBefore(8f);
            fl.setSpacingAfter(2f);
            c.addElement(fl);
            Paragraph fb = new Paragraph(overallFeedback, fBody);
            fb.setLeading(14f);
            c.addElement(fb);
        }
        return c;
    }

    // 하단 메모 영역: 연한 모눈 배경 위에 사용자가 직접 작성
    private com.lowagie.text.pdf.PdfPTable buildMemoBox(BaseFont base) {
        com.lowagie.text.pdf.PdfPTable t = new com.lowagie.text.pdf.PdfPTable(1);
        t.setWidthPercentage(100);
        t.setSpacingBefore(8f);
        com.lowagie.text.pdf.PdfPCell c = new com.lowagie.text.pdf.PdfPCell();
        c.setMinimumHeight(MEMO_MIN_H);
        c.setPadding(11f);
        c.setBorderColor(C_BORDER);
        c.setBorderWidth(1f);
        c.setCellEvent(GRID_BG);
        c.addElement(new Paragraph("메모", new Font(base, 11, Font.BOLD, C_GREEN)));
        t.addCell(c);
        return t;
    }

    // "라벨: 값" 한 줄을 옅은 배경 박스로 강조 (정답=초록, 오답/미응답=빨강/앰버)
    private com.lowagie.text.pdf.PdfPTable answerLine(BaseFont base, String label, String value, Color fg, Color bg) {
        com.lowagie.text.pdf.PdfPTable t = new com.lowagie.text.pdf.PdfPTable(1);
        t.setWidthPercentage(100);
        t.setSpacingBefore(3f);
        com.lowagie.text.pdf.PdfPCell c = new com.lowagie.text.pdf.PdfPCell();
        c.setPadding(8f);
        c.setBackgroundColor(bg);
        c.setBorderColor(bg);
        Paragraph p = new Paragraph();
        p.add(new com.lowagie.text.Chunk(label + ": ", new Font(base, 10, Font.BOLD, fg)));
        p.add(new com.lowagie.text.Chunk(nz(value).isBlank() ? "-" : value, new Font(base, 10.5f, Font.NORMAL, C_TEXT)));
        p.setLeading(15f);
        c.addElement(p);
        t.addCell(c);
        return t;
    }

    private byte[] fontBytes() {
        if (cachedFont == null) {
            try (InputStream is = ReviewNoteService.class.getResourceAsStream("/fonts/NanumGothic.ttf")) {
                if (is == null) throw new IllegalStateException("NanumGothic.ttf 폰트를 찾을 수 없습니다.");
                cachedFont = is.readAllBytes();
            } catch (Exception e) {
                throw new RuntimeException("한글 폰트 로딩 실패", e);
            }
        }
        return cachedFont;
    }

    // 복습 대상(오답 + 미응답) 단위. unanswered=true 이면 "내가 고른 답: 미응답".
    private static class WrongItem {
        final String question;
        final List<String> options;
        final Integer correctIndex;
        final Integer selectedIndex;   // 미응답이면 null
        String explanation;            // ai07 enrich 가능
        final boolean unanswered;
        final int page;
        String concept;                // 다시 봐야 할 개념 (ai07 enrich 가능)
        WrongItem(String question, List<String> options, Integer correctIndex, Integer selectedIndex,
                  String explanation, boolean unanswered, int page) {
            this.question = question;
            this.options = options;
            this.correctIndex = correctIndex;
            this.selectedIndex = selectedIndex;
            this.explanation = explanation;
            this.unanswered = unanswered;
            this.page = page;
        }
        /** 게이트 재생성 시도마다 독립 사본(거절된 시도의 보강이 다음 시도·저장본에 섞이지 않게). */
        WrongItem copy() {
            WrongItem c = new WrongItem(question, options, correctIndex, selectedIndex, explanation, unanswered, page);
            c.concept = concept;
            return c;
        }
    }

    private static class ParsedQuestion {
        final String question;
        final List<String> options;
        final Integer correctIndex;
        final String explanation;
        final int page;
        ParsedQuestion(String question, List<String> options, Integer correctIndex, String explanation, int page) {
            this.question = question;
            this.options = options;
            this.correctIndex = correctIndex;
            this.explanation = explanation;
            this.page = page;
        }
    }

    // 유사문제 중복 판정 키(문항 본문 정규화). top-up 재요청 결과 병합에 사용.
    private static String variantKey(Object q) {
        if (q instanceof Map<?, ?> m) {
            Object t = m.get("question") != null ? m.get("question") : (m.get("prompt") != null ? m.get("prompt") : m.get("text"));
            return t == null ? String.valueOf(m.hashCode()) : String.valueOf(t).replaceAll("\\s+", " ").trim().toLowerCase();
        }
        return String.valueOf(q);
    }

    // 폴백 유사문제 1건(원본 오답을 다시 출제). AI 폴백/부분 top-up 공용.
    private static Map<String, Object> fallbackQuestion(Long noteId, Map<String, Object> src, int idx, String difficulty, String variationPoint) {
        Map<String, Object> q = new LinkedHashMap<>();
        q.put("id", "fallback-" + noteId + "-" + (idx + 1));
        q.put("wrongQuestionId", idx + 1);
        q.put("sourceWrongNoteId", noteId);
        q.put("question", src.get("question"));
        q.put("choices", src.get("choices"));
        q.put("correctAnswer", src.get("correct_answer"));
        q.put("answer", src.get("correct_answer"));
        q.put("explanation", src.get("explanation"));
        q.put("difficulty", difficulty);
        q.put("variationPoint", variationPoint);
        return q;
    }
}
