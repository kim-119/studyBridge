package com.studybridge.api.service;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.dto.*;
import com.studybridge.api.entity.*;
import com.studybridge.api.repository.*;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import org.springframework.web.reactive.function.client.WebClient;

import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.LinkedHashMap;
import java.util.stream.Collectors;

// 자료보관함 AI 호출 hard timeout (무한 대기 방지). 전체 2분 예산 내(120~125초).

@Slf4j
@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class AiIntegrationService {

        private static final ObjectMapper AI_OBJECT_MAPPER = new ObjectMapper();

        private final MaterialRepository materialRepository;
        private final MaterialSummaryRepository summaryRepository;
        private final MaterialFeedbackRepository feedbackRepository;
        private final MaterialQuizRepository quizRepository;
        private final MaterialMemoRepository memoRepository;
        private final MaterialQuestionRepository questionRepository;
        private final RoadmapRepository roadmapRepository;
        private final RoadmapTaskRepository roadmapTaskRepository;
        private final WebClient fastApiWebClient;

        // 키워드 정의 호출 타임아웃 (env 제어, 하드코딩 금지)
        @org.springframework.beans.factory.annotation.Value("${ai.server.fastapi.keyword-define-timeout-seconds:60}")
        private long keywordDefineTimeoutSeconds;

        private Material getMaterialSafely(Long userId, Long materialId) {
                Material material = materialRepository.findById(materialId)
                                .orElseThrow(() -> new IllegalArgumentException("자료를 찾을 수 없습니다."));
                if (!material.getUserId().equals(userId)) {
                        throw new SecurityException("권한이 없습니다.");
                }
                return material;
        }

        private String getTextToAnalyze(Material material) {
                if (material == null) {
                        throw new IllegalArgumentException("자료 정보가 없습니다.");
                }
                String extractedText = material.getExtractedText();
                if (extractedText != null && !extractedText.isBlank()) {
                        return extractedText;
                }
                String learningContent = material.getLearningContent();
                if (learningContent != null && !learningContent.isBlank()) {
                        return learningContent;
                }
                return null;
        }

        // 메모 가져오기
        public MemoDTO getMemo(Long userId, Long materialId) {
                getMaterialSafely(userId, materialId);
                return memoRepository.findByMaterial_MaterialId(materialId)
                                .map(memo -> MemoDTO.builder()
                                                .memoId(memo.getMemoId())
                                                .materialId(materialId)
                                                .content(memo.getContent())
                                                .updatedAt(memo.getUpdatedAt())
                                                .build())
                                .orElse(MemoDTO.builder().materialId(materialId).content("").build());
        }

        // 메모 저장하기
        @Transactional
        public MemoDTO saveMemo(Long userId, Long materialId, String content) {
                Material material = getMaterialSafely(userId, materialId);
                MaterialMemo memo = memoRepository.findByMaterial_MaterialId(materialId)
                                .orElse(MaterialMemo.builder().material(material).build());

                memo.setContent(content);
                memo = memoRepository.save(memo);

                return MemoDTO.builder()
                                .memoId(memo.getMemoId())
                                .materialId(materialId)
                                .content(memo.getContent())
                                .updatedAt(memo.getUpdatedAt())
                                .build();
        }

        // 요약 가져오기 (없으면 FastAPI 호출하여 생성)
        @Transactional
        public SummaryDTO getSummary(Long userId, Long materialId) {
                Material material = getMaterialSafely(userId, materialId);
                return summaryRepository.findByMaterial_MaterialId(materialId)
                                .map(summary -> isSummaryUsable(summary) ? summaryDtoFromEntity(material, summary) : generateSummary(material))
                                .orElseGet(() -> generateSummary(material));
        }

        /** FastAPI 호출 예외를 사용자 친화 메시지로 변환한다 (timeout 구분). */
        private RuntimeException aiError(String feature, Exception e) {
                String msg = e.getMessage() == null ? "" : e.getMessage();
                boolean timeout = e instanceof IllegalStateException
                                || msg.toLowerCase().contains("timeout")
                                || (e.getCause() instanceof java.util.concurrent.TimeoutException);
                if (timeout) {
                        return new RuntimeException("AI 응답 시간이 초과되었습니다. 잠시 후 다시 시도해주세요.");
                }
                return new RuntimeException(feature + " 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.");
        }

        // FastAPI 응답 Map에서 AI 상태 필드를 안전하게 추출 (없으면 null/기본값)
        @SuppressWarnings("unchecked")
        private Map<String, Object> aiMap(Map response, String key) {
                if (response != null && response.get(key) instanceof Map) {
                        return (Map<String, Object>) response.get(key);
                }
                return null;
        }

        @SuppressWarnings("unchecked")
        private List<String> aiWarnings(Map response) {
                if (response != null && response.get("warnings") instanceof List) {
                        List<String> out = new java.util.ArrayList<>();
                        for (Object o : (List<Object>) response.get("warnings")) {
                                if (o != null) out.add(o.toString());
                        }
                        return out;
                }
                return null;
        }

        private Boolean aiBool(Map response, String key, Boolean dflt) {
                if (response != null && response.get(key) instanceof Boolean) {
                        return (Boolean) response.get(key);
                }
                return dflt;
        }

        private String aiStr(Map response, String key) {
                if (response != null && response.get(key) != null) {
                        return response.get(key).toString();
                }
                return null;
        }


        @SuppressWarnings("unchecked")
        private List<Map<String, Object>> aiMapList(Map response, String key) {
                if (response != null && response.get(key) instanceof List) {
                        List<Map<String, Object>> out = new java.util.ArrayList<>();
                        for (Object item : (List<Object>) response.get(key)) {
                                if (item instanceof Map) out.add((Map<String, Object>) item);
                        }
                        return out;
                }
                return null;
        }

        private List<String> aiStringList(Map response, String key) {
                if (response != null && response.get(key) instanceof List) {
                        List<String> out = new java.util.ArrayList<>();
                        for (Object item : (List<?>) response.get(key)) {
                                if (item != null && !item.toString().isBlank()) out.add(item.toString());
                        }
                        return out;
                }
                return null;
        }

        private String toJson(Object value, String fallback) {
                if (value == null) return fallback;
                if (value instanceof String) return (String) value;
                try { return AI_OBJECT_MAPPER.writeValueAsString(value); } catch (Exception e) { return fallback; }
        }

        private Map<String, Object> parseJsonObject(String raw) {
                if (raw == null || raw.isBlank()) return java.util.Collections.emptyMap();
                try { return AI_OBJECT_MAPPER.readValue(raw, new TypeReference<Map<String, Object>>() {}); }
                catch (Exception ignored) { return java.util.Collections.emptyMap(); }
        }

        private List<Map<String, Object>> parseJsonList(String raw) {
                if (raw == null || raw.isBlank()) return java.util.Collections.emptyList();
                try { return AI_OBJECT_MAPPER.readValue(raw, new TypeReference<List<Map<String, Object>>>() {}); }
                catch (Exception ignored) { return java.util.Collections.emptyList(); }
        }

        @SuppressWarnings("unchecked")
        private SummaryDTO summaryDtoFromEntity(Material material, MaterialSummary summary) {
                Map<String, Object> envelope = parseJsonObject(summary.getCoreContents());
                List<Map<String, Object>> sections = new java.util.ArrayList<>();
                if (envelope.get("sections") instanceof List) {
                        for (Object item : (List<Object>) envelope.get("sections")) {
                                if (item instanceof Map) sections.add((Map<String, Object>) item);
                        }
                } else {
                        sections.addAll(parseJsonList(summary.getCoreContents()));
                }
                List<String> keywords = new java.util.ArrayList<>();
                Object kwRaw = envelope.get("keywords") != null ? envelope.get("keywords") : envelope.get("key_points");
                if (kwRaw instanceof List) {
                        for (Object kw : (List<Object>) kwRaw) if (kw != null && !kw.toString().isBlank()) keywords.add(kw.toString());
                }
                String summaryText = envelope.get("summary") != null ? envelope.get("summary").toString() : summary.getOverview();
                String gptRaw = envelope.get("gpt_raw") != null ? envelope.get("gpt_raw").toString() : null;
                return SummaryDTO.builder()
                                .summaryId(summary.getSummaryId())
                                .materialId(material.getMaterialId())
                                .overview(summary.getOverview())
                                .coreContents(summary.getCoreContents())
                                .summary(summaryText)
                                .key_points(keywords)
                                .gpt_raw(gptRaw)
                                .keywords(keywords)
                                .sections(sections)
                                .learningPoints(stringListFromEnvelope(envelope, "learningPoints"))
                                .practicePoints(stringListFromEnvelope(envelope, "practicePoints"))
                                .studyQuestions(stringListFromEnvelope(envelope, "studyQuestions"))
                                .success(true)
                                .textStatus(textStatusFor(material, getTextToAnalyze(material)))
                                .build();
        }

        @SuppressWarnings("unchecked")
        private List<String> stringListFromEnvelope(Map<String, Object> envelope, String key) {
                Object raw = envelope.get(key);
                if (raw instanceof List) {
                        List<String> out = new java.util.ArrayList<>();
                        for (Object item : (List<Object>) raw) if (item != null && !item.toString().isBlank()) out.add(item.toString());
                        return out;
                }
                return java.util.Collections.emptyList();
        }

        @SuppressWarnings("unchecked")
        private boolean isSummaryUsable(MaterialSummary summary) {
                if (summary == null) return false;
                if (summary.getOverview() != null && !summary.getOverview().isBlank() && !"요약 생성 실패".equals(summary.getOverview())) return true;
                String core = summary.getCoreContents();
                if (core == null || core.isBlank()) return false;
                String trimmed = core.trim();
                if ("[]".equals(trimmed) || "{}".equals(trimmed)) return false;
                Map<String, Object> envelope = parseJsonObject(core);
                Object sections = envelope.get("sections");
                if (sections instanceof List) return !((List<Object>) sections).isEmpty();
                return !parseJsonList(core).isEmpty();
        }

        private String buildSummaryCoreContents(Map response) {
                Map<String, Object> envelope = new LinkedHashMap<>();
                Object sections = response != null ? response.get("sections") : null;
                if (sections == null && response != null) sections = response.get("coreContents");
                envelope.put("sections", sections != null ? sections : java.util.Collections.emptyList());
                envelope.put("keywords", aiStringList(response, "keywords") != null ? aiStringList(response, "keywords") : aiStringList(response, "key_points"));
                envelope.put("key_points", aiStringList(response, "key_points") != null ? aiStringList(response, "key_points") : aiStringList(response, "keywords"));
                envelope.put("summary", aiStr(response, "summary"));
                envelope.put("gpt_raw", aiStr(response, "gpt_raw"));
                envelope.put("learningPoints", aiStringList(response, "learningPoints"));
                envelope.put("practicePoints", aiStringList(response, "practicePoints"));
                envelope.put("studyQuestions", aiStringList(response, "studyQuestions"));
                return toJson(envelope, "[]");
        }


        private List<Map<String, Object>> parseQuizData(String quizData) {
                if (quizData == null || quizData.isBlank()) return java.util.Collections.emptyList();
                List<Map<String, Object>> direct = parseJsonList(quizData);
                if (!direct.isEmpty()) return direct;
                Map<String, Object> obj = parseJsonObject(quizData);
                Object quizzes = obj.get("quizzes") != null ? obj.get("quizzes") : obj.get("questions");
                if (quizzes instanceof List) {
                        List<Map<String, Object>> out = new java.util.ArrayList<>();
                        for (Object item : (List<?>) quizzes) if (item instanceof Map) out.add((Map<String, Object>) item);
                        return out;
                }
                return java.util.Collections.emptyList();
        }

        private Map<String, Object> roadmapDataFromSteps(String title, List<RoadmapDTO.RoadmapStepDTO> steps) {
                Map<String, Object> data = new LinkedHashMap<>();
                List<Map<String, Object>> weeks = new java.util.ArrayList<>();
                for (RoadmapDTO.RoadmapStepDTO step : steps) {
                        Map<String, Object> week = new LinkedHashMap<>();
                        week.put("weekNumber", step.getStepOrder());
                        week.put("stepOrder", step.getStepOrder());
                        week.put("title", step.getTitle());
                        week.put("goal", step.getDescription());
                        week.put("description", step.getDescription());
                        List<Map<String, Object>> tasks = new java.util.ArrayList<>();
                        if (step.getTasks() != null) {
                                for (RoadmapDTO.RoadmapTaskDTO task : step.getTasks()) {
                                        Map<String, Object> taskMap = new LinkedHashMap<>();
                                        taskMap.put("taskId", task.getTaskId());
                                        taskMap.put("taskOrder", task.getTaskOrder());
                                        taskMap.put("content", task.getContent());
                                        taskMap.put("isCompleted", task.getIsCompleted());
                                        tasks.add(taskMap);
                                }
                        }
                        week.put("tasks", tasks);
                        week.put("estimatedHours", 3);
                        weeks.add(week);
                }
                data.put("title", title);
                data.put("totalWeeks", 12);
                data.put("weeks", weeks);
                data.put("steps", weeks);
                return data;
        }


        private RoadmapDTO roadmapDtoFromEntity(Material material, Roadmap roadmap) {
                List<RoadmapDTO.RoadmapStepDTO> steps = roadmap.getSteps().stream()
                                .map(step -> RoadmapDTO.RoadmapStepDTO.builder()
                                                .stepId(step.getStepId())
                                                .stepOrder(step.getStepOrder())
                                                .title(step.getTitle())
                                                .description(step.getDescription())
                                                .tasks(step.getTasks().stream()
                                                                .map(task -> RoadmapDTO.RoadmapTaskDTO.builder()
                                                                                .taskId(task.getTaskId())
                                                                                .taskOrder(task.getTaskOrder())
                                                                                .content(task.getContent())
                                                                                .isCompleted(task.getIsCompleted())
                                                                                .build())
                                                                .collect(Collectors.toList()))
                                                .build())
                                .collect(Collectors.toList());
                return RoadmapDTO.builder()
                                .roadmapId(roadmap.getRoadmapId())
                                .materialId(material.getMaterialId())
                                .title(roadmap.getTitle())
                                .steps(steps)
                                .roadmapData(roadmapDataFromSteps(roadmap.getTitle(), steps))
                                .totalWeeks(12)
                                .success(true)
                                .textStatus(textStatusFor(material, getTextToAnalyze(material)))
                                .build();
        }

        private Long aiMetaLong(Map response, String key) {
                Map<String, Object> metadata = aiMap(response, "metadata");
                if (metadata == null || metadata.get(key) == null) return null;
                Object v = metadata.get(key);
                if (v instanceof Number) return ((Number) v).longValue();
                try { return Long.parseLong(v.toString()); } catch (Exception ignored) { return null; }
        }

        private String aiMetaStr(Map response, String key) {
                Map<String, Object> metadata = aiMap(response, "metadata");
                if (metadata == null || metadata.get(key) == null) return null;
                return metadata.get(key).toString();
        }

        private Boolean aiMetaBool(Map response, String key) {
                Map<String, Object> metadata = aiMap(response, "metadata");
                if (metadata == null || metadata.get(key) == null) return null;
                Object v = metadata.get(key);
                if (v instanceof Boolean) return (Boolean) v;
                return Boolean.parseBoolean(v.toString());
        }

        private boolean isAiFailure(Map response) {
                return response != null && Boolean.FALSE.equals(response.get("success"));
        }

        private boolean isTimeout(Exception e) {
                String msg = e.getMessage() == null ? "" : e.getMessage().toLowerCase();
                return e instanceof IllegalStateException
                                || msg.contains("timeout")
                                || msg.contains("timed out")
                                || (e.getCause() instanceof java.util.concurrent.TimeoutException);
        }

        private Map<String, Object> textStatusFor(Material material, String textToAnalyze) {
                Map<String, Object> status = new LinkedHashMap<>();
                int length = textToAnalyze == null ? 0 : textToAnalyze.length();
                status.put("hasText", length > 0);
                status.put("textLength", length);
                status.put("chunkCount", 0);
                status.put("status", length > 0 ? (length < 300 ? "TOO_SHORT" : "READY") : "EMPTY");
                status.put("materialId", material != null ? material.getMaterialId() : null);
                return status;
        }

        private Integer aiInt(Object value, int dflt) {
                if (value instanceof Number) return ((Number) value).intValue();
                if (value != null) {
                        try { return Integer.parseInt(value.toString()); } catch (Exception ignored) { }
                }
                return dflt;
        }

        private String userMessageFor(String errorCode, String fallback) {
                if ("PDF_OCR_REQUIRED".equals(errorCode)) return "이미지 기반 PDF라 텍스트 추출이 필요합니다. OCR 설정을 켠 뒤 다시 시도해주세요.";
                if ("PDF_TEXT_EMPTY".equals(errorCode)) return "PDF에서 추출된 텍스트가 없습니다. 다시 분석을 시도해주세요.";
                if ("AI_TIMEOUT".equals(errorCode)) return "AI 응답 시간이 초과되었습니다. 잠시 후 다시 시도해주세요.";
                if ("OLLAMA_UNAVAILABLE".equals(errorCode)) return "로컬 AI 모델 연결에 실패했습니다.";
                if ("OPENAI_UNAVAILABLE".equals(errorCode)) return "GPT 모델 연결에 실패했습니다.";
                if (fallback != null && !fallback.isBlank()) return fallback;
                return "AI 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.";
        }

        private SummaryDTO summaryFailure(Material material, String errorCode, String message, Boolean retryable, Map response) {
                String text = getTextToAnalyze(material);
                return SummaryDTO.builder()
                                .materialId(material.getMaterialId())
                                .overview("")
                                .coreContents("[]")
                                .success(false)
                                .errorCode(errorCode)
                                .message(userMessageFor(errorCode, message))
                                .retryable(retryable != null ? retryable : true)
                                .textStatus(aiMap(response, "textStatus") != null ? aiMap(response, "textStatus") : textStatusFor(material, text))
                                .warnings(aiWarnings(response))
                                .metadata(aiMap(response, "metadata"))
                                .provider(aiMetaStr(response, "provider"))
                                .model(aiMetaStr(response, "model"))
                                .elapsedMs(aiMetaLong(response, "elapsedMs"))
                                .usedFallback(aiMetaBool(response, "usedFallback"))
                                .cacheHit(aiMetaBool(response, "cacheHit"))
                                .build();
        }

        private QuizDTO.Response quizFailure(Material material, QuizDTO.Request request, String errorCode, String message, Boolean retryable, Map response) {
                String text = getTextToAnalyze(material);
                return QuizDTO.Response.builder()
                                .materialId(material.getMaterialId())
                                .difficulty(request != null ? request.getDifficulty() : null)
                                .questionCount(request != null ? request.getQuestionCount() : null)
                                .pageRange(request != null ? request.getPageRange() : null)
                                .quizData("[]")
                                .quizzes(java.util.Collections.emptyList())
                                .success(false)
                                .errorCode(errorCode)
                                .message(userMessageFor(errorCode, message))
                                .retryable(retryable != null ? retryable : true)
                                .textStatus(aiMap(response, "textStatus") != null ? aiMap(response, "textStatus") : textStatusFor(material, text))
                                .warnings(aiWarnings(response))
                                .metadata(aiMap(response, "metadata"))
                                .provider(aiMetaStr(response, "provider"))
                                .model(aiMetaStr(response, "model"))
                                .elapsedMs(aiMetaLong(response, "elapsedMs"))
                                .usedFallback(aiMetaBool(response, "usedFallback"))
                                .cacheHit(aiMetaBool(response, "cacheHit"))
                                .build();
        }

        private QuestionDTO.Response questionFailure(Material material, String userQuestion, String errorCode, String message, Boolean retryable, Map response) {
                String text = getTextToAnalyze(material);
                return QuestionDTO.Response.builder()
                                .materialId(material.getMaterialId())
                                .userQuestion(userQuestion)
                                .aiAnswer(userMessageFor(errorCode, message))
                                .success(false)
                                .errorCode(errorCode)
                                .message(userMessageFor(errorCode, message))
                                .retryable(retryable != null ? retryable : true)
                                .textStatus(aiMap(response, "textStatus") != null ? aiMap(response, "textStatus") : textStatusFor(material, text))
                                .warnings(aiWarnings(response))
                                .metadata(aiMap(response, "metadata"))
                                .provider(aiMetaStr(response, "provider"))
                                .model(aiMetaStr(response, "model"))
                                .elapsedMs(aiMetaLong(response, "elapsedMs"))
                                .usedFallback(aiMetaBool(response, "usedFallback"))
                                .cacheHit(aiMetaBool(response, "cacheHit"))
                                .build();
        }

        private RoadmapDTO roadmapFailure(Material material, String errorCode, String message, Boolean retryable, Map response) {
                String text = getTextToAnalyze(material);
                return RoadmapDTO.builder()
                                .materialId(material.getMaterialId())
                                .title("로드맵 미생성")
                                .steps(java.util.Collections.emptyList())
                                .roadmapData(java.util.Collections.emptyMap())
                                .totalWeeks(12)
                                .success(false)
                                .errorCode(errorCode)
                                .message(userMessageFor(errorCode, message))
                                .retryable(retryable != null ? retryable : true)
                                .textStatus(aiMap(response, "textStatus") != null ? aiMap(response, "textStatus") : textStatusFor(material, text))
                                .warnings(aiWarnings(response))
                                .metadata(aiMap(response, "metadata"))
                                .provider(aiMetaStr(response, "provider"))
                                .model(aiMetaStr(response, "model"))
                                .elapsedMs(aiMetaLong(response, "elapsedMs"))
                                .usedFallback(aiMetaBool(response, "usedFallback"))
                                .cacheHit(aiMetaBool(response, "cacheHit"))
                                .build();
        }

        private SummaryDTO generateSummary(Material material) {
                String textToAnalyze = getTextToAnalyze(material);
                if (textToAnalyze == null || textToAnalyze.isBlank()) {
                        return summaryFailure(material, "PDF_TEXT_EMPTY", "PDF에서 추출된 텍스트가 없습니다. 다시 분석을 시도해주세요.", true, null);
                }

                Map<String, Object> requestBody = Map.of(
                                "material_id", material.getMaterialId(),
                                "document_title", material.getTitle(),
                                "text", textToAnalyze);
                Map response;
                try {
                        response = fastApiWebClient.post().uri("/api/ai/summary")
                                        .bodyValue(requestBody).retrieve().bodyToMono(Map.class).block(Duration.ofSeconds(125));
                } catch (Exception e) {
                        return summaryFailure(material, isTimeout(e) ? "AI_TIMEOUT" : "UNKNOWN_ERROR", null, true, null);
                }

                if (isAiFailure(response)) {
                        return summaryFailure(material, aiStr(response, "errorCode"), aiStr(response, "message"), aiBool(response, "retryable", true), response);
                }

                String overview = response != null && response.get("overview") != null && !response.get("overview").toString().isBlank()
                                ? response.get("overview").toString()
                                : (aiStr(response, "summary") != null ? aiStr(response, "summary") : "");
                String coreContents = buildSummaryCoreContents(response);
                MaterialSummary summary = summaryRepository.findByMaterial_MaterialId(material.getMaterialId())
                                .orElseGet(() -> MaterialSummary.builder().material(material).build());
                summary.setOverview(overview);
                summary.setCoreContents(coreContents);
                summary = summaryRepository.save(summary);

                return SummaryDTO.builder()
                                .summaryId(summary.getSummaryId())
                                .materialId(material.getMaterialId())
                                .overview(summary.getOverview())
                                .coreContents(summary.getCoreContents())
                                .summary(aiStr(response, "summary") != null ? aiStr(response, "summary") : overview)
                                .key_points(aiStringList(response, "key_points"))
                                .gpt_raw(aiStr(response, "gpt_raw"))
                                .keywords(aiStringList(response, "keywords") != null ? aiStringList(response, "keywords") : aiStringList(response, "key_points"))
                                .sections(aiMapList(response, "sections"))
                                .learningPoints(aiStringList(response, "learningPoints"))
                                .practicePoints(aiStringList(response, "practicePoints"))
                                .studyQuestions(aiStringList(response, "studyQuestions"))
                                .success(aiBool(response, "success", true))
                                .errorCode(aiStr(response, "errorCode"))
                                .message(aiStr(response, "message"))
                                .retryable(aiBool(response, "retryable", null))
                                .textStatus(aiMap(response, "textStatus"))
                                .warnings(aiWarnings(response))
                                .metadata(aiMap(response, "metadata"))
                                .provider(aiMetaStr(response, "provider"))
                                .model(aiMetaStr(response, "model"))
                                .elapsedMs(aiMetaLong(response, "elapsedMs"))
                                .usedFallback(aiMetaBool(response, "usedFallback"))
                                .cacheHit(aiMetaBool(response, "cacheHit"))
                                .build();
        }

        // 피드백 가져오기 (없으면 FastAPI 호출하여 생성)
        @Transactional
        public FeedbackDTO getFeedback(Long userId, Long materialId) {
                Material material = getMaterialSafely(userId, materialId);
                return feedbackRepository.findByMaterial_MaterialId(materialId)
                                .map(feedback -> FeedbackDTO.builder()
                                                .feedbackId(feedback.getFeedbackId())
                                                .materialId(materialId)
                                                .feedbackData(feedback.getFeedbackData())
                                                .createdAt(feedback.getCreatedAt())
                                                .build())
                                .orElseGet(() -> generateFeedback(material));
        }

        private FeedbackDTO generateFeedback(Material material) {
                String textToAnalyze = getTextToAnalyze(material);
                if (textToAnalyze == null || textToAnalyze.isBlank()) {
                        throw new IllegalArgumentException("학습 내용 또는 추출된 텍스트가 없어 피드백을 생성할 수 없습니다.");
                }

                Map<String, Object> requestBody = Map.of("content", textToAnalyze);
                Map response;
                try {
                        response = fastApiWebClient.post().uri("/api/ai/feedback")
                                        .bodyValue(requestBody).retrieve().bodyToMono(Map.class).block(Duration.ofSeconds(125));
                } catch (Exception e) {
                        throw aiError("피드백", e);
                }

                MaterialFeedback feedback = MaterialFeedback.builder()
                                .material(material)
                                .feedbackData(response != null && response.containsKey("feedbackData")
                                                ? response.get("feedbackData").toString()
                                                : "피드백 생성 실패")
                                .build();
                feedback = feedbackRepository.save(feedback);

                return FeedbackDTO.builder()
                                .feedbackId(feedback.getFeedbackId())
                                .materialId(material.getMaterialId())
                                .feedbackData(feedback.getFeedbackData())
                                .createdAt(feedback.getCreatedAt())
                                .build();
        }

        // 퀴즈 목록 조회
        public List<QuizDTO.Response> getQuizzes(Long userId, Long materialId) {
                Material material = getMaterialSafely(userId, materialId);
                return quizRepository.findByMaterial_MaterialIdOrderByCreatedAtDesc(materialId)
                                .stream()
                                .map(quiz -> QuizDTO.Response.builder()
                                                .quizId(quiz.getQuizId())
                                                .materialId(materialId)
                                                .difficulty(quiz.getDifficulty())
                                                .questionCount(quiz.getQuestionCount())
                                                .pageRange(quiz.getPageRange())
                                                .quizData(quiz.getQuizData())
                                                .quizzes(parseQuizData(quiz.getQuizData()))
                                                .createdAt(quiz.getCreatedAt())
                                                .success(true)
                                                .textStatus(textStatusFor(material, getTextToAnalyze(material)))
                                                .build())
                                .collect(Collectors.toList());
        }

        // 퀴즈 생성 요청
        @Transactional
        public QuizDTO.Response generateQuiz(Long userId, Long materialId, QuizDTO.Request request) {
                Material material = getMaterialSafely(userId, materialId);

                String textToAnalyze = getTextToAnalyze(material);
                if (textToAnalyze == null || textToAnalyze.isBlank()) {
                        return quizFailure(material, request, "PDF_TEXT_EMPTY", "PDF에서 추출된 텍스트가 없습니다. 다시 분석을 시도해주세요.", true, null);
                }

                Map<String, Object> requestBody = Map.of(
                                "material_id", material.getMaterialId(),
                                "text", textToAnalyze,
                                "difficulty", request.getDifficulty(),
                                "questionCount", request.getQuestionCount());

                Map response;
                try {
                        response = fastApiWebClient.post()
                                        .uri("/api/ai/quiz")
                                        .bodyValue(requestBody)
                                        .retrieve()
                                        .bodyToMono(Map.class)
                                        .block(Duration.ofSeconds(125));
                } catch (Exception e) {
                        return quizFailure(material, request, isTimeout(e) ? "AI_TIMEOUT" : "UNKNOWN_ERROR", null, true, null);
                }

                if (isAiFailure(response)) {
                        return quizFailure(material, request, aiStr(response, "errorCode"), aiStr(response, "message"), aiBool(response, "retryable", true), response);
                }

                String generatedQuizJson = "[]";
                if (response != null && response.containsKey("quizData")) {
                        generatedQuizJson = response.get("quizData").toString();
                }

                MaterialQuiz quiz = MaterialQuiz.builder()
                                .material(material)
                                .difficulty(request.getDifficulty())
                                .questionCount(request.getQuestionCount())
                                .pageRange(request.getPageRange())
                                .quizData(generatedQuizJson)
                                .build();
                quiz = quizRepository.save(quiz);

                return QuizDTO.Response.builder()
                                .quizId(quiz.getQuizId())
                                .materialId(materialId)
                                .difficulty(quiz.getDifficulty())
                                .questionCount(quiz.getQuestionCount())
                                .pageRange(quiz.getPageRange())
                                .quizData(quiz.getQuizData())
                                .quizzes(parseQuizData(quiz.getQuizData()))
                                .createdAt(quiz.getCreatedAt())
                                .success(aiBool(response, "success", true))
                                .errorCode(aiStr(response, "errorCode"))
                                .message(aiStr(response, "message"))
                                .retryable(aiBool(response, "retryable", null))
                                .textStatus(aiMap(response, "textStatus"))
                                .warnings(aiWarnings(response))
                                .metadata(aiMap(response, "metadata"))
                                .provider(aiMetaStr(response, "provider"))
                                .model(aiMetaStr(response, "model"))
                                .elapsedMs(aiMetaLong(response, "elapsedMs"))
                                .usedFallback(aiMetaBool(response, "usedFallback"))
                                .cacheHit(aiMetaBool(response, "cacheHit"))
                                .build();
        }

        // AI에게 질문하기 (자료보관함 PDF 기반)
        @Transactional
        public QuestionDTO.Response askQuestion(Long userId, Long materialId, QuestionDTO.Request request) {
                Material material = getMaterialSafely(userId, materialId);

                String textToAnalyze = getTextToAnalyze(material);
                if (textToAnalyze == null || textToAnalyze.isBlank()) {
                        return questionFailure(material, request.getUserQuestion(), "PDF_TEXT_EMPTY", "PDF에서 추출된 텍스트가 없습니다. 다시 분석을 시도해주세요.", true, null);
                }

                Map<String, Object> requestBody = Map.of(
                                "material_id", material.getMaterialId(),
                                "text", textToAnalyze,
                                "question", request.getUserQuestion());

                Map response;
                try {
                        response = fastApiWebClient.post()
                                        .uri("/api/ai/question")
                                        .bodyValue(requestBody)
                                        .retrieve()
                                        .bodyToMono(Map.class)
                                        .block(Duration.ofSeconds(125));
                } catch (Exception e) {
                        return questionFailure(material, request.getUserQuestion(), isTimeout(e) ? "AI_TIMEOUT" : "UNKNOWN_ERROR", null, true, null);
                }

                if (isAiFailure(response)) {
                        return questionFailure(material, request.getUserQuestion(), aiStr(response, "errorCode"), aiStr(response, "message"), aiBool(response, "retryable", true), response);
                }

                String aiAnswer = "답변을 가져오지 못했습니다.";
                if (response != null && response.containsKey("answer")) {
                        aiAnswer = response.get("answer").toString();
                }

                MaterialQuestion question = MaterialQuestion.builder()
                                .material(material)
                                .userQuestion(request.getUserQuestion())
                                .aiAnswer(aiAnswer)
                                .build();
                question = questionRepository.save(question);

                return QuestionDTO.Response.builder()
                                .questionId(question.getQuestionId())
                                .materialId(materialId)
                                .userQuestion(question.getUserQuestion())
                                .aiAnswer(question.getAiAnswer())
                                .createdAt(question.getCreatedAt())
                                .success(aiBool(response, "success", true))
                                .errorCode(aiStr(response, "errorCode"))
                                .message(aiStr(response, "message"))
                                .retryable(aiBool(response, "retryable", null))
                                .textStatus(aiMap(response, "textStatus"))
                                .warnings(aiWarnings(response))
                                .metadata(aiMap(response, "metadata"))
                                .provider(aiMetaStr(response, "provider"))
                                .model(aiMetaStr(response, "model"))
                                .elapsedMs(aiMetaLong(response, "elapsedMs"))
                                .usedFallback(aiMetaBool(response, "usedFallback"))
                                .cacheHit(aiMetaBool(response, "cacheHit"))
                                .build();
        }

        // 로드맵 조회
        @Transactional
        public RoadmapDTO getRoadmap(Long userId, Long materialId) {
                Material material = getMaterialSafely(userId, materialId);

                return roadmapRepository.findByMaterial_MaterialId(materialId)
                                .map(roadmap -> roadmapDtoFromEntity(material, roadmap))
                                .orElseGet(() -> generateRoadmap(material));
        }

        // 로드맵 생성
        private RoadmapDTO generateRoadmap(Material material) {
                String textToAnalyze = getTextToAnalyze(material);
                if (textToAnalyze == null || textToAnalyze.isBlank()) {
                        return roadmapFailure(material, "PDF_TEXT_EMPTY", "PDF에서 추출된 텍스트가 없습니다. 다시 분석을 시도해주세요.", true, null);
                }

                String userGoal = "학습 목표 달성";
                if (material.getTitle() != null && !material.getTitle().isBlank()) {
                        userGoal = material.getTitle() + " 학습 및 핵심 목표 달성";
                }

                Map<String, Object> requestBody = Map.of(
                        "material_id", material.getMaterialId(),
                        "pdf_text", textToAnalyze,
                        "user_goal", userGoal
                );

                Map response;
                try {
                        response = fastApiWebClient.post().uri("/api/ai/roadmap")
                                        .bodyValue(requestBody).retrieve().bodyToMono(Map.class).block(Duration.ofSeconds(125));
                } catch (Exception e) {
                        return roadmapFailure(material, isTimeout(e) ? "AI_TIMEOUT" : "UNKNOWN_ERROR", null, true, null);
                }

                if (isAiFailure(response)) {
                        return roadmapFailure(material, aiStr(response, "errorCode"), aiStr(response, "message"), aiBool(response, "retryable", true), response);
                }

                Map<String, Object> roadmapMap = null;
                if (response != null && response.containsKey("roadmap")) {
                        roadmapMap = (Map<String, Object>) response.get("roadmap");
                }

                String roadmapTitle = "AI 생성 학습 로드맵";
                if (roadmapMap != null && roadmapMap.containsKey("title")) {
                        roadmapTitle = roadmapMap.get("title").toString();
                }

                Roadmap roadmap = Roadmap.builder()
                                .material(material)
                                .userId(material.getUserId())
                                .title(roadmapTitle)
                                .build();

                if (roadmapMap != null && roadmapMap.containsKey("steps")) {
                        java.util.List<Map<String, Object>> stepMaps = (java.util.List<Map<String, Object>>) roadmapMap
                                        .get("steps");
                        for (Map<String, Object> stepMap : stepMaps) {
                                RoadmapStep step = RoadmapStep.builder()
                                                .roadmap(roadmap)
                                                .stepOrder(aiInt(stepMap.get("stepOrder"), 1))
                                                .title(stepMap.containsKey("title") ? stepMap.get("title").toString()
                                                                : "주차 제목 없음")
                                                .description(stepMap.containsKey("description")
                                                                ? stepMap.get("description").toString()
                                                                : "")
                                                .build();

                                if (stepMap.containsKey("tasks")) {
                                        java.util.List<Map<String, Object>> taskMaps = (java.util.List<Map<String, Object>>) stepMap
                                                        .get("tasks");
                                        for (Map<String, Object> taskMap : taskMaps) {
                                                RoadmapTask task = RoadmapTask.builder()
                                                                .step(step)
                                                                .taskOrder(aiInt(taskMap.get("taskOrder"), 1))
                                                                .content(taskMap.containsKey("content")
                                                                                ? taskMap.get("content").toString()
                                                                                : "할 일 내용 없음")
                                                                .build();
                                                step.getTasks().add(task);
                                        }
                                }
                                roadmap.getSteps().add(step);
                        }
                }

                try {
                        roadmap = roadmapRepository.save(roadmap);
                } catch (Exception e) {
                        // 엔티티 저장 실패(예: 컬럼 길이 초과 등)가 500으로 전파되지 않도록 사용자 메시지가 있는 실패 응답으로 변환한다.
                        log.error("[roadmap:fail] code=ROADMAP_SAVE_FAILED materialId={} message={}", material.getMaterialId(), e.getMessage(), e);
                        return roadmapFailure(material, "ROADMAP_GENERATION_FAILED", "주차별 로드맵 저장 중 오류가 발생했습니다. 다시 시도해주세요.", true, null);
                }

                return RoadmapDTO.builder()
                                .roadmapId(roadmap.getRoadmapId())
                                .materialId(material.getMaterialId())
                                .title(roadmap.getTitle())
                                .roadmapData(roadmapMap)
                                .totalWeeks(12)
                                .steps(roadmap.getSteps().stream()
                                                .map(step -> RoadmapDTO.RoadmapStepDTO.builder()
                                                                .stepId(step.getStepId())
                                                                .stepOrder(step.getStepOrder())
                                                                .title(step.getTitle())
                                                                .description(step.getDescription())
                                                                .tasks(step.getTasks().stream()
                                                                                .map(task -> RoadmapDTO.RoadmapTaskDTO
                                                                                                .builder()
                                                                                                .taskId(task.getTaskId())
                                                                                                .taskOrder(task.getTaskOrder())
                                                                                                .content(task.getContent())
                                                                                                .isCompleted(task
                                                                                                                .getIsCompleted())
                                                                                                .build())
                                                                                .collect(Collectors.toList()))
                                                                .build())
                                                .collect(Collectors.toList()))
                                .success(aiBool(response, "success", true))
                                .errorCode(aiStr(response, "errorCode"))
                                .message(aiStr(response, "message"))
                                .retryable(aiBool(response, "retryable", null))
                                .textStatus(aiMap(response, "textStatus"))
                                .warnings(aiWarnings(response))
                                .metadata(aiMap(response, "metadata"))
                                .provider(aiMetaStr(response, "provider"))
                                .model(aiMetaStr(response, "model"))
                                .elapsedMs(aiMetaLong(response, "elapsedMs"))
                                .usedFallback(aiMetaBool(response, "usedFallback"))
                                .cacheHit(aiMetaBool(response, "cacheHit"))
                                .build();
        }

        // 로드맵 태스크 완료 상태 토글
        @Transactional
        public RoadmapDTO.RoadmapTaskDTO toggleRoadmapTask(Long userId, Long materialId, Long taskId) {
                getMaterialSafely(userId, materialId);

                RoadmapTask task = roadmapTaskRepository.findById(taskId)
                                .orElseThrow(() -> new IllegalArgumentException("해당 할 일을 찾을 수 없습니다."));

                // 플래너 로드맵(material=null)은 이 자료-스코프 토글 대상이 아니다 → null 가드로 NPE 방지
                Material taskMaterial = task.getStep().getRoadmap().getMaterial();
                if (taskMaterial == null || !taskMaterial.getMaterialId().equals(materialId)) {
                        throw new SecurityException("잘못된 접근입니다.");
                }

                task.setIsCompleted(!task.getIsCompleted());
                roadmapTaskRepository.save(task);

                return RoadmapDTO.RoadmapTaskDTO.builder()
                                .taskId(task.getTaskId())
                                .taskOrder(task.getTaskOrder())
                                .content(task.getContent())
                                .isCompleted(task.getIsCompleted())
                                .build();
        }

        // 핵심 키워드 개념 정의 (FastAPI /api/ai/keyword/define 프록시)
        @SuppressWarnings("unchecked")
        public KeywordDefineDTO.Response defineKeyword(Long userId, Long materialId, KeywordDefineDTO.Request request) {
                Material material = getMaterialSafely(userId, materialId);
                if (request == null || request.getKeyword() == null || request.getKeyword().isBlank()) {
                        throw new IllegalArgumentException("키워드가 비어 있습니다.");
                }

                Map<String, Object> requestBody = new LinkedHashMap<>();
                requestBody.put("keyword", request.getKeyword());
                requestBody.put("source", request.getSource() != null ? request.getSource() : "auto");
                requestBody.put("level", request.getLevel() != null ? request.getLevel() : "undergraduate");
                // 문서 맥락은 요청에 없으면 자료 텍스트 앞부분으로 보강
                String context = request.getContext();
                if (context == null || context.isBlank()) {
                        String text = getTextToAnalyze(material);
                        if (text != null && !text.isBlank()) context = text.substring(0, Math.min(text.length(), 1500));
                }
                if (context != null && !context.isBlank()) requestBody.put("context", context);

                Map response;
                try {
                        response = fastApiWebClient.post().uri("/api/ai/keyword/define")
                                        .bodyValue(requestBody).retrieve().bodyToMono(Map.class)
                                        .block(Duration.ofSeconds(keywordDefineTimeoutSeconds));
                } catch (Exception e) {
                        throw aiError("키워드 정의", e);
                }

                if (response == null || Boolean.FALSE.equals(response.get("success"))) {
                        return KeywordDefineDTO.Response.builder()
                                        .success(false)
                                        .errorCode(aiStr(response, "errorCode"))
                                        .message(aiStr(response, "message") != null ? aiStr(response, "message") : "개념 정의 생성에 실패했습니다.")
                                        .build();
                }

                return KeywordDefineDTO.Response.builder()
                                .success(true)
                                .name(aiStr(response, "name"))
                                .shortDefinition(aiStr(response, "shortDefinition"))
                                .detailedDefinition(aiStr(response, "detailedDefinition"))
                                .importance(aiStr(response, "importance"))
                                .examples(aiStringList(response, "examples"))
                                .relatedConcepts(aiStringList(response, "relatedConcepts"))
                                .sourceUsed(aiStr(response, "sourceUsed"))
                                .wikiUrl(aiStr(response, "wikiUrl"))
                                .build();
        }
}
