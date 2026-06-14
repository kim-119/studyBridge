package com.studybridge.api.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.studybridge.api.dto.ReviewNoteDTO;
import com.studybridge.api.entity.ExtractionStatus;
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
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
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

/**
 * 오답노트 생성/조회 서비스.
 * 흐름: 퀴즈 채점으로 틀린 문제 추출 → ai07 wrong-note-feedback 호출(없으면 폴백) →
 *   PDF 생성 → S3 업로드 → review_note 메타 저장 → 자료보관함(Material) 자동 추가.
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

    @Value("${ai.server.fastapi.review-timeout-seconds:120}")
    private long reviewTimeoutSeconds;

    private byte[] cachedFont;

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

        // 2) ai07 호출 (있으면 AI 강화본, 실패/부재 시 보유 데이터로 폴백)
        Map<String, Object> requestBody = new LinkedHashMap<>();
        requestBody.put("material_id", source.getMaterialId());
        requestBody.put("material_title", source.getTitle());
        String docText = source.getExtractedText();
        if (docText != null && docText.length() > 6000) docText = docText.substring(0, 6000);
        requestBody.put("document_text", docText != null ? docText : "");
        requestBody.put("difficulty", mapDifficulty(quiz.getDifficulty()));
        requestBody.put("wrong_questions", wrongQuestions);

        long t0 = System.currentTimeMillis();
        log.info("[REVIEW_NOTE] start userId={} quizId={} materialId={} wrong={} unanswered={}",
                userId, quizId, source.getMaterialId(), wrongOnly, unansweredOnly);

        Map response = null;
        try {
            response = fastApiWebClient.post().uri("/api/ai/review/wrong-note-feedback")
                    .bodyValue(requestBody).retrieve().bodyToMono(Map.class)
                    .block(Duration.ofSeconds(reviewTimeoutSeconds));
        } catch (Exception e) {
            log.warn("[REVIEW_NOTE] ai07 unavailable quizId={} cause={} -> 폴백 생성",
                    quizId, e.getClass().getSimpleName() + ": " + e.getMessage());
        }

        Object errorCode = response != null ? response.get("error_code") : null;
        boolean aiEnriched = (errorCode == null && response != null);

        // ai07 의 per-문제 해설/개념(있으면)으로 보강. PDF 레이아웃은 항상 우리 구조로 렌더(품질 일관).
        String overallFeedback = aiEnriched ? firstNonBlank(
                asStr(response.get("overall_feedback")), asStr(response.get("overallFeedback")),
                asStr(response.get("feedback")), asStr(response.get("summary"))) : null;
        if (overallFeedback == null || overallFeedback.isBlank()) {
            overallFeedback = "아래 문제들을 다시 확인하고, 정답과 해설을 비교하며 복습하세요."
                    + (unansweredOnly > 0 ? " 미응답 문제는 시간 내에 풀이를 시도하는 연습이 필요합니다." : "");
        }
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
                .build();
        note = reviewNoteRepository.save(note);

        log.info("[REVIEW_NOTE] OK userId={} reviewNoteId={} archiveMaterialId={} wrong={} unanswered={} aiEnriched={} elapsedMs={}",
                userId, note.getReviewNoteId(), archive.getMaterialId(), wrongOnly, unansweredOnly, aiEnriched, System.currentTimeMillis() - t0);

        return toDTO(note, true);
    }

    private String asStr(Object o) { return o == null ? null : o.toString(); }

    private String firstNonBlank(String... vals) {
        if (vals == null) return null;
        for (String v : vals) if (v != null && !v.isBlank()) return v;
        return null;
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
        out.put("url", presign(note));
        out.put("fileName", note.getTitle() + ".pdf");
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
        out.put("reviewNoteId", id);
        out.put("sourceMaterialId", note.getSourceMaterialId());
        out.put("questions", questions);
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
    // 유사문제: POST /api/review-notes/{id}/variant-question
    //   body { wrongQuestionId, difficulty: easy|normal|hard, count }
    //   ai07 variant 엔드포인트가 살아있으면 AI 변형, 없으면(404 등) 원본 오답을 재출제로 폴백.
    // ---------------------------------------------------------------------
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
        Map aiResp = null;
        try {
            aiResp = fastApiWebClient.post().uri("/api/ai/review/variant-question")
                    .bodyValue(req).retrieve().bodyToMono(Map.class)
                    .block(Duration.ofSeconds(reviewTimeoutSeconds));
        } catch (Exception e) {
            log.warn("[REVIEW_NOTE] variant ai07 unavailable id={} cause={} -> 폴백", id, e.getMessage());
        }

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("reviewNoteId", id);
        out.put("difficulty", difficulty);
        if (aiResp != null && aiResp.get("error_code") == null && aiResp.get("questions") != null) {
            out.put("success", true);
            out.put("usedFallback", false);
            out.put("questions", aiResp.get("questions"));
            return out;
        }
        // 3) 폴백: 원본 오답 문제를 그대로 재출제 (AI 변형 불가 시에도 화면이 동작하도록)
        List<Map<String, Object>> questions = new ArrayList<>();
        if (base != null) {
            Map<String, Object> q = new LinkedHashMap<>();
            q.put("wrongQuestionId", wrongQuestionId);
            q.put("question", base.get("question"));
            q.put("choices", base.get("choices"));
            q.put("correctAnswer", base.get("correct_answer"));
            q.put("explanation", base.get("explanation"));
            questions.add(q);
        }
        out.put("success", true);
        out.put("usedFallback", true);
        out.put("questions", questions);
        return out;
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
        return ReviewNoteDTO.builder()
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
                .pdfUrl(withPresign ? presign(n) : null)
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
}
