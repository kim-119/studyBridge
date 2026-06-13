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

        // 1) 저장된 퀴즈 + 제출 답안으로 틀린 문제 추출 (프론트 parseQuizQuestions 규칙 미러링)
        List<ParsedQuestion> questions = parseQuizData(quiz.getQuizData());
        List<WrongItem> wrongItems = new ArrayList<>();
        List<Map<String, Object>> wrongQuestions = new ArrayList<>();
        for (int idx = 0; idx < questions.size(); idx++) {
            ParsedQuestion q = questions.get(idx);
            Integer selected = answerIndexFor(answers, idx);
            if (selected == null) continue;            // 미응답은 오답에서 제외
            if (selected.equals(q.correctIndex)) continue; // 정답은 제외
            wrongItems.add(new WrongItem(q.question, q.options, q.correctIndex, selected, q.explanation));
            Map<String, Object> wq = new LinkedHashMap<>();
            wq.put("question", q.question);
            wq.put("options", q.options);
            wq.put("choices", q.options);
            wq.put("correct_answer", optionAt(q.options, q.correctIndex));
            wq.put("user_answer", optionAt(q.options, selected));
            wq.put("explanation", q.explanation);
            wrongQuestions.add(wq);
        }

        if (wrongItems.isEmpty()) {
            throw new IllegalStateException("틀린 문제가 없어 오답노트를 만들 수 없습니다.");
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
        log.info("[REVIEW_NOTE] start userId={} quizId={} materialId={} wrongCount={}",
                userId, quizId, source.getMaterialId(), wrongItems.size());

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
        String aiPdfText = response != null && response.get("pdf_plain_text") != null
                ? response.get("pdf_plain_text").toString() : null;

        boolean aiEnriched = (errorCode == null && aiPdfText != null && !aiPdfText.isBlank());
        String pdfText;
        String retryJson;
        if (aiEnriched) {
            pdfText = aiPdfText;
            retryJson = extractRetryJson(response);
        } else {
            log.info("[REVIEW_NOTE] fallback build quizId={} wrongCount={}", quizId, wrongItems.size());
            pdfText = buildFallbackPlainText(source.getTitle(), quiz.getDifficulty(), wrongItems);
            retryJson = buildRetryJsonFromWrong(wrongItems);
        }

        // 3) PDF 생성 (NanumGothic). 파일명: "원본자료제목 오답노트.pdf"
        String noteTitle = safeTitle(source.getTitle()) + " 오답노트";
        String fileName = noteTitle + ".pdf";
        byte[] pdf = buildPdf(pdfText);

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
                .extractedText(pdfText)
                .extractionStatus(ExtractionStatus.SUCCESS)
                .build();
        archive = materialRepository.save(archive);

        // 6) review_note 메타 저장
        int wrongCount = response != null && response.get("wrong_count") instanceof Number
                ? ((Number) response.get("wrong_count")).intValue() : wrongItems.size();
        ReviewNote note = ReviewNote.builder()
                .userId(userId)
                .sourceMaterialId(source.getMaterialId())
                .sourceTitle(source.getTitle())
                .quizId(quizId)
                .archiveMaterialId(archive.getMaterialId())
                .title(noteTitle)
                .s3Key(s3Key)
                .wrongCount(wrongCount)
                .difficulty(mapDifficulty(quiz.getDifficulty()))
                .retryJson(retryJson)
                .build();
        note = reviewNoteRepository.save(note);

        log.info("[REVIEW_NOTE] OK userId={} reviewNoteId={} archiveMaterialId={} wrongCount={} aiEnriched={} elapsedMs={}",
                userId, note.getReviewNoteId(), archive.getMaterialId(), wrongCount, aiEnriched, System.currentTimeMillis() - t0);

        return toDTO(note, true);
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
        return ReviewNoteDTO.builder()
                .id(n.getReviewNoteId())
                .title(n.getTitle())
                .sourceName(n.getSourceTitle())
                .originalMaterialTitle(n.getSourceTitle())
                .sourceMaterialId(n.getSourceMaterialId())
                .quizId(n.getQuizId())
                .archiveMaterialId(n.getArchiveMaterialId())
                .wrongCount(n.getWrongCount())
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

    private String extractRetryJson(Map response) {
        try {
            ArrayNode out = MAPPER.createArrayNode();
            Object notes = response.get("wrong_notes");
            if (notes instanceof List) {
                for (Object o : (List<?>) notes) {
                    if (o instanceof Map && ((Map<?, ?>) o).get("retry_question") != null) {
                        out.add(MAPPER.valueToTree(((Map<?, ?>) o).get("retry_question")));
                    }
                }
            }
            return MAPPER.writeValueAsString(out);
        } catch (Exception e) {
            return "[]";
        }
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
                result.add(new ParsedQuestion(question, options, correct, explanation));
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

    // ---------------- 폴백(ai07 부재 시) 본문/재출제 ----------------
    private String buildFallbackPlainText(String title, String difficultyKo, List<WrongItem> wrongItems) {
        String t = (title == null || title.isBlank()) ? "학습자료" : title;
        String diff = (difficultyKo == null || difficultyKo.isBlank()) ? "보통" : difficultyKo;
        StringBuilder sb = new StringBuilder();
        sb.append(t).append(" 오답노트\n");
        sb.append("자료명: ").append(t).append("\n");
        sb.append("난이도: ").append(diff).append("\n");
        sb.append("틀린 문제 수: ").append(wrongItems.size()).append("\n\n");
        sb.append("전체 피드백: 아래 문제들을 다시 확인하고, 정답과 해설을 비교하며 복습하세요.\n\n");
        int i = 1;
        for (WrongItem w : wrongItems) {
            sb.append(i++).append(". 문제: ").append(nz(w.question)).append("\n");
            sb.append("내가 고른 답: ").append(optionAt(w.options, w.selectedIndex)).append("\n");
            sb.append("정답: ").append(optionAt(w.options, w.correctIndex)).append("\n");
            String exp = (w.explanation == null || w.explanation.isBlank()) ? "해설 정보가 없습니다. 자료를 다시 확인하세요." : w.explanation;
            sb.append("해설: ").append(exp).append("\n\n");
        }
        return sb.toString();
    }

    private String buildRetryJsonFromWrong(List<WrongItem> wrongItems) {
        try {
            ArrayNode out = MAPPER.createArrayNode();
            for (WrongItem w : wrongItems) {
                com.fasterxml.jackson.databind.node.ObjectNode n = MAPPER.createObjectNode();
                n.put("question", nz(w.question));
                ArrayNode ch = MAPPER.createArrayNode();
                if (w.options != null) for (String o : w.options) ch.add(o);
                n.set("choices", ch);
                n.put("correct_answer", optionAt(w.options, w.correctIndex));
                n.put("explanation", nz(w.explanation));
                out.add(n);
            }
            return MAPPER.writeValueAsString(out);
        } catch (Exception e) {
            return "[]";
        }
    }

    private String nz(String s) { return s == null ? "" : s; }

    // ---------------- PDF 생성 (OpenPDF + NanumGothic) ----------------
    private byte[] buildPdf(String plainText) {
        try (ByteArrayOutputStream baos = new ByteArrayOutputStream()) {
            Document doc = new Document(PageSize.A4, 40, 40, 48, 48);
            PdfWriter.getInstance(doc, baos);
            doc.open();
            BaseFont base = BaseFont.createFont("NanumGothic.ttf", BaseFont.IDENTITY_H,
                    BaseFont.EMBEDDED, BaseFont.CACHED, fontBytes(), null);

            String[] lines = (plainText == null ? "" : plainText).replace("\r", "").split("\n", -1);
            boolean first = true;
            for (String line : lines) {
                Font f;
                if (first) {
                    f = new Font(base, 18, Font.BOLD, new Color(21, 128, 61));
                    first = false;
                } else if (isHeadingLine(line)) {
                    f = new Font(base, 13, Font.BOLD, new Color(17, 24, 39));
                } else {
                    f = new Font(base, 11, Font.NORMAL, new Color(31, 41, 55));
                }
                Paragraph p = new Paragraph(line.isEmpty() ? " " : line, f);
                p.setSpacingAfter(line.isEmpty() ? 6f : 2f);
                p.setLeading(f.getSize() * 1.5f);
                doc.add(p);
            }
            doc.close();
            return baos.toByteArray();
        } catch (Exception e) {
            throw new RuntimeException("오답노트 PDF 생성에 실패했습니다.", e);
        }
    }

    private boolean isHeadingLine(String line) {
        if (line == null) return false;
        String t = line.trim();
        return t.matches("^\\d+\\.\\s*문제:.*")
                || t.startsWith("전체 피드백")
                || t.startsWith("추천 복습")
                || t.startsWith("자료명")
                || t.startsWith("틀린 문제 수");
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

    private static class WrongItem {
        final String question;
        final List<String> options;
        final Integer correctIndex;
        final Integer selectedIndex;
        final String explanation;
        WrongItem(String question, List<String> options, Integer correctIndex, Integer selectedIndex, String explanation) {
            this.question = question;
            this.options = options;
            this.correctIndex = correctIndex;
            this.selectedIndex = selectedIndex;
            this.explanation = explanation;
        }
    }

    private static class ParsedQuestion {
        final String question;
        final List<String> options;
        final Integer correctIndex;
        final String explanation;
        ParsedQuestion(String question, List<String> options, Integer correctIndex, String explanation) {
            this.question = question;
            this.options = options;
            this.correctIndex = correctIndex;
            this.explanation = explanation;
        }
    }
}
