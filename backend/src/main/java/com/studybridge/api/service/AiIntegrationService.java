package com.studybridge.api.service;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.dto.*;
import com.studybridge.api.entity.*;
import com.studybridge.api.repository.*;
import com.studybridge.api.util.ConceptFallbackProvider;
import com.studybridge.api.util.LearningContentSanitizer;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import org.springframework.web.reactive.function.client.WebClient;

import java.time.Duration;
import java.util.ArrayList;
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
        private final IntentRouterService intentRouterService;
        private final LearningLoopService learningLoopService;

        // 키워드 정의 호출 타임아웃 (env 제어, 하드코딩 금지)
        @org.springframework.beans.factory.annotation.Value("${ai.server.fastapi.keyword-define-timeout-seconds:60}")
        private long keywordDefineTimeoutSeconds;

        // 자료보관함 12주x7일(84일) 로드맵 생성 호출 타임아웃 (env 제어, 하드코딩 금지)
        @org.springframework.beans.factory.annotation.Value("${ai.server.fastapi.roadmap-timeout-seconds:180}")
        private long roadmapTimeoutSeconds;

        // 84일 로드맵 고정 차원(12주 x 7일). 화면/검증 기준값과 동기화.
        private static final int ROADMAP_TOTAL_WEEKS = 12;
        private static final int ROADMAP_DAYS_PER_WEEK = 7;

        /**
         * 업로드 전 자료 유형 판별. ai07 /api/ai/material/classify 호출.
         * 파일명/메타데이터(+ai07 vector/rule/OCR) 기반. PDF_TEXT_EMPTY 보다 먼저 호출된다.
         * ai07 장애 시 저장을 막지 않도록 isMismatch=false 로 통과시킨다.
         * selectedTypeAi 는 ai07 vocab(STUDY_PDF/PLANNER/WRONG_NOTE/STUDY_LOG).
         */
        @SuppressWarnings("unchecked")
        public Map<String, Object> classifyBeforeSave(String fileName, String mimeType, String selectedTypeAi,
                        Integer pageCount, String title, java.util.List<String> keywords) {
                Map<String, Object> reqBody = new LinkedHashMap<>();
                reqBody.put("file_name", fileName != null ? fileName : "");
                reqBody.put("mime_type", mimeType != null ? mimeType : "");
                reqBody.put("selected_type", selectedTypeAi);
                reqBody.put("extracted_text", "");
                reqBody.put("ocr_text", "");
                reqBody.put("page_count", pageCount);
                reqBody.put("preview_text", "");
                Map<String, Object> meta = new LinkedHashMap<>();
                meta.put("title", title != null ? title : "");
                meta.put("keywords", keywords != null ? keywords : java.util.Collections.emptyList());
                reqBody.put("metadata", meta);

                try {
                        Map<String, Object> resp = fastApiWebClient.post().uri("/api/ai/material/classify")
                                        .bodyValue(reqBody)
                                        .retrieve()
                                        .bodyToMono(Map.class)
                                        .timeout(Duration.ofSeconds(20))
                                        .block();
                        if (resp == null) return classifyFallback(selectedTypeAi);
                        return toClassifyResponse(resp, selectedTypeAi);
                } catch (Exception e) {
                        log.warn("[classify-before-save] ai07 호출 실패 → 저장 통과(fallback): {}", e.getMessage());
                        return classifyFallback(selectedTypeAi);
                }
        }

        private Map<String, Object> toClassifyResponse(Map<String, Object> ai, String selectedTypeAi) {
                String recommended = asStr(ai.get("recommended_type"));
                if (recommended == null || recommended.isBlank()) recommended = selectedTypeAi;
                boolean isMismatch = Boolean.TRUE.equals(ai.get("is_mismatch"));
                double confidence = ai.get("confidence") instanceof Number ? ((Number) ai.get("confidence")).doubleValue() : 0.0;
                Map<String, Object> out = new LinkedHashMap<>();
                out.put("success", true);
                out.put("selectedType", selectedTypeAi);
                out.put("recommendedType", recommended);
                out.put("isMismatch", isMismatch);
                out.put("confidence", confidence);
                out.put("reason", asStr(ai.get("reason")));
                out.put("userMessage", asStr(ai.get("user_message")));
                out.put("allowedActions", ai.getOrDefault("allowed_actions", java.util.Collections.emptyList()));
                out.put("capabilityHint", ai.getOrDefault("capability_hint", java.util.Collections.emptyMap()));
                return out;
        }

        private Map<String, Object> classifyFallback(String selectedTypeAi) {
                Map<String, Object> out = new LinkedHashMap<>();
                out.put("success", true);
                out.put("selectedType", selectedTypeAi);
                out.put("recommendedType", selectedTypeAi);
                out.put("isMismatch", false);
                out.put("confidence", 0.0);
                out.put("reason", "유형 판별 서버를 사용할 수 없어 선택한 유형으로 진행합니다.");
                out.put("userMessage", "");
                out.put("allowedActions", java.util.List.of(
                                Map.of("label", "저장", "type", selectedTypeAi, "recommended", true),
                                Map.of("label", "취소", "type", "CANCEL", "recommended", false)));
                out.put("capabilityHint", java.util.Collections.emptyMap());
                return out;
        }

        private String asStr(Object o) { return o == null ? null : o.toString(); }

        private Material getMaterialSafely(Long userId, Long materialId) {
                Material material = materialRepository.findById(materialId)
                                .orElseThrow(() -> new IllegalArgumentException("자료를 찾을 수 없습니다."));
                if (!material.getUserId().equals(userId)) {
                        throw new SecurityException("권한이 없습니다.");
                }
                return material;
        }

        /**
         * PDF 텍스트 기반 AI 기능(요약/퀴즈/로드맵 등)은 PDF·문서 자료만 허용한다.
         * 플래너(PLANNER)는 구조화된 로드맵 데이터이므로 PDF 추출/분석 파이프라인으로 들어가면 안 된다.
         */
        private void assertPdfAnalyzable(Material material, String feature) {
                if (material != null && material.getMaterialType() == MaterialType.PLANNER) {
                        throw new IllegalArgumentException(
                                "플래너는 구조화된 로드맵 데이터입니다. PDF " + feature + " 기능은 사용할 수 없습니다.");
                }
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
                assertPdfAnalyzable(material, "요약");
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
                // 신(新) 84일 구조: roadmapJson이 있으면 weeks[].days[]를 그대로 복원해 반환한다.
                if (roadmap.getRoadmapJson() != null && !roadmap.getRoadmapJson().isBlank()) {
                        try {
                                Map<String, Object> data = AI_OBJECT_MAPPER.readValue(
                                                roadmap.getRoadmapJson(), new TypeReference<Map<String, Object>>() {});
                                return roadmapDtoFromJson(material, roadmap, data);
                        } catch (Exception e) {
                                log.warn("[roadmap] roadmapJson 파싱 실패 roadmapId={} → 레거시 경로로 처리", roadmap.getRoadmapId());
                        }
                }
                // 레거시(steps/tasks 24개) 구조: days 없음 → 프론트가 재생성 안내 + 버튼을 띄운다.
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
                                "text", textToAnalyze,
                                "s3_file_url", material.getS3FileUrl() != null ? material.getS3FileUrl() : "");
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

                // 학습 왕복 루프: 요약 생성 기록(다음 AI 질문의 컨텍스트 후보)
                learningLoopService.recordSafe(LearningLoopEvent.builder()
                                .userId(material.getUserId())
                                .eventType(LearningEventType.MATERIAL_SUMMARY_GENERATED)
                                .sourceType(LearningSourceType.MATERIAL)
                                .sourceId(material.getMaterialId())
                                .materialId(material.getMaterialId())
                                .aiOutputSummary(overview)
                                .userAction("SUMMARY_GENERATED")
                                .build());

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

        // L. 균형 잡힌 피드백 다시 생성 — 기존 피드백 삭제 후 balanced 모드로 재생성
        @Transactional
        public FeedbackDTO regenerateFeedback(Long userId, Long materialId) {
                Material material = getMaterialSafely(userId, materialId);
                feedbackRepository.findByMaterial_MaterialId(materialId).ifPresent(feedbackRepository::delete);
                feedbackRepository.flush();
                return generateFeedback(material);
        }

        private FeedbackDTO generateFeedback(Material material) {
                String textToAnalyze = getTextToAnalyze(material);
                if (textToAnalyze == null || textToAnalyze.isBlank()) {
                        throw new IllegalArgumentException("학습 내용 또는 추출된 텍스트가 없어 피드백을 생성할 수 없습니다.");
                }

                // J/K. 균형 잡힌 피드백 요청(장점/권장/우려 각 8개 이상 + 마크다운 제거). ai07이 지원하면 구조화 응답.
                Map<String, Object> requestBody = new LinkedHashMap<>();
                requestBody.put("content", textToAnalyze);
                requestBody.put("feedback_mode", "balanced");
                requestBody.put("min_strengths", 8);
                requestBody.put("min_recommendations", 8);
                requestBody.put("min_concerns", 8);
                requestBody.put("sanitize_markdown", true);
                Map response;
                try {
                        response = fastApiWebClient.post().uri("/api/ai/feedback")
                                        .bodyValue(requestBody).retrieve().bodyToMono(Map.class).block(Duration.ofSeconds(125));
                } catch (Exception e) {
                        throw aiError("피드백", e);
                }

                // J/K. ai07이 구조화 피드백(strengths/recommendations/concerns 등)을 주면 응답 전체를 JSON으로 보존,
                //      아니면 기존 문자열(feedbackData) 보존. 프론트가 두 형태를 모두 sanitize/파싱한다.
                String feedbackData;
                boolean structured = response != null && (response.containsKey("strengths")
                                || response.containsKey("recommendations") || response.containsKey("concerns")
                                || response.containsKey("feedback_balance") || response.containsKey("summary"));
                if (structured) {
                        feedbackData = toJson(response, "{}");
                } else if (response != null && response.containsKey("feedbackData")) {
                        feedbackData = response.get("feedbackData").toString();
                } else if (response != null && response.containsKey("feedback")) {
                        feedbackData = response.get("feedback").toString();
                } else {
                        feedbackData = "피드백 생성 실패";
                }
                MaterialFeedback feedback = MaterialFeedback.builder()
                                .material(material)
                                .feedbackData(feedbackData)
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
                assertPdfAnalyzable(material, "퀴즈/문제 생성");
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

                // A/B. 퀴즈는 PDF/DOCX 자료 본문 기준(로드맵 day 아님). 자료 본문 + 요약/핵심/세부 + 키워드로 PDF context 구성.
                MaterialSummary quizSummary = summaryRepository.findByMaterial_MaterialId(material.getMaterialId()).orElse(null);
                String documentText = textToAnalyze != null ? textToAnalyze : "";
                String summaryText = quizSummary != null ? quizSummary.getOverview() : null;
                String coreContentText = quizSummary != null ? quizSummary.getCoreContents() : null;
                String detailedContentText = documentText.length() > 4000 ? documentText.substring(0, 4000) : null;

                // C. PDF context 필수 검증 — documentText/summary/coreContentText/detailedContentText 중 하나 이상 필요.
                //    전부 없으면 로드맵으로 대체하지 않고 PDF_CONTEXT_REQUIRED 반환.
                boolean hasPdfContext = isNotBlank(documentText) || isNotBlank(summaryText) || isNotBlank(coreContentText) || isNotBlank(detailedContentText);
                if (!hasPdfContext) {
                        log.warn("[AI_QUIZ_PDF_BASED] materialId={} sourceMode=PDF_BASED result=PDF_CONTEXT_REQUIRED", material.getMaterialId());
                        return quizFailure(material, request, "PDF_CONTEXT_REQUIRED",
                                        "PDF 기반 퀴즈를 생성하려면 자료에서 추출된 텍스트나 요약이 필요합니다.", true, null);
                }

                // R. 문항 수 5~20 보정: null→10, <5→5, >20→20. (프론트와 동일 정책을 백엔드에서도 강제)
                Integer requestedCount = request.getQuestionCount();
                int appliedCount = clampQuizCount(requestedCount);

                // D/F. 난이도 매핑: 쉬움→easy, 보통→normal, 어려움→hard. (로드맵 난이도 beginner/intermediate/advanced와 절대 섞지 않음)
                String quizDifficulty = mapQuizDifficulty(request.getDifficulty());

                // B. ai07 요청 payload — source_mode=PDF_BASED. roadmap_context/ROADMAP_ONLY 미사용.
                java.util.List<String> quizKeywords = new java.util.ArrayList<>();
                if (material.getKeywords() != null && !material.getKeywords().isBlank()) {
                        for (String k : material.getKeywords().split(",")) { if (!k.trim().isBlank()) quizKeywords.add(k.trim()); }
                }
                Map<String, Object> requestBody = new LinkedHashMap<>();
                requestBody.put("material_id", material.getMaterialId());
                requestBody.put("material_title", material.getTitle());
                requestBody.put("source_mode", "PDF_BASED");
                requestBody.put("s3_file_url", material.getS3FileUrl() != null ? material.getS3FileUrl() : "");
                requestBody.put("difficulty", quizDifficulty);           // 영문 (easy|normal|hard)
                requestBody.put("difficulty_requested", quizDifficulty);
                requestBody.put("difficulty_label", request.getDifficulty()); // 원본 한글
                requestBody.put("count", appliedCount);
                requestBody.put("questionCount", appliedCount); // 하위호환
                requestBody.put("document_text", truncQuiz(documentText, 8000));
                requestBody.put("text", truncQuiz(documentText, 8000));       // 하위호환(기존 ai07 contract)
                if (isNotBlank(summaryText)) requestBody.put("summary", summaryText);
                if (isNotBlank(coreContentText)) requestBody.put("core_content_text", coreContentText);
                if (isNotBlank(detailedContentText)) requestBody.put("detailed_content_text", detailedContentText);
                requestBody.put("keywords", quizKeywords);

                // J. PDF 기반 퀴즈 로그 (원문/토큰/키/presigned 미포함)
                long quizT0 = System.currentTimeMillis();
                log.info("[AI_QUIZ_PDF_BASED] materialId={} difficulty={} sourceMode=PDF_BASED hasDocumentText={} hasSummary={} hasCoreContentText={} hasDetailedContentText={} count={}",
                                material.getMaterialId(), quizDifficulty, isNotBlank(documentText), isNotBlank(summaryText), isNotBlank(coreContentText), isNotBlank(detailedContentText), request.getQuestionCount());

                Map response;
                try {
                        response = fastApiWebClient.post()
                                        .uri("/api/ai/quiz")
                                        .bodyValue(requestBody)
                                        .retrieve()
                                        .bodyToMono(Map.class)
                                        .block(Duration.ofSeconds(125));
                } catch (Exception e) {
                        String __code = isTimeout(e) ? "AI_TIMEOUT" : "UNKNOWN_ERROR";
                        log.warn("[AI_QUIZ_PDF_BASED] result=FAIL materialId={} difficulty={} sourceMode=PDF_BASED error_code={} elapsedMs={}",
                                        material.getMaterialId(), quizDifficulty, __code, System.currentTimeMillis() - quizT0);
                        return quizFailure(material, request, __code, null, true, null);
                }

                if (isAiFailure(response)) {
                        log.warn("[AI_QUIZ_PDF_BASED] result=AI_FAIL materialId={} difficulty={} sourceMode=PDF_BASED statusCode=200 error_code={} reason={} elapsedMs={}",
                                        material.getMaterialId(), quizDifficulty, aiStr(response, "errorCode"), aiStr(aiMap(response, "difficulty_validation"), "reason"), System.currentTimeMillis() - quizT0);
                        return quizFailure(material, request, aiStr(response, "errorCode"), aiStr(response, "message"), aiBool(response, "retryable", true), response);
                }

                log.info("[AI_QUIZ_PDF_BASED] result=OK materialId={} difficulty={} sourceMode=PDF_BASED applied={} elapsedMs={}",
                                material.getMaterialId(), quizDifficulty, aiStr(response, "difficulty_applied"), System.currentTimeMillis() - quizT0);

                String generatedQuizJson = "[]";
                if (response != null && response.containsKey("quizData")) {
                        generatedQuizJson = response.get("quizData").toString();
                }

                MaterialQuiz quiz = MaterialQuiz.builder()
                                .material(material)
                                .difficulty(request.getDifficulty())
                                .questionCount(appliedCount)
                                .pageRange(request.getPageRange())
                                .quizData(generatedQuizJson)
                                .build();
                quiz = quizRepository.save(quiz);

                // 학습 왕복 루프: 퀴즈 생성 기록(출처 자료/난이도/범위)
                learningLoopService.recordSafe(LearningLoopEvent.builder()
                                .userId(material.getUserId())
                                .eventType(LearningEventType.MATERIAL_QUIZ_GENERATED)
                                .sourceType(LearningSourceType.QUIZ)
                                .sourceId(quiz.getQuizId())
                                .materialId(materialId)
                                .quizId(quiz.getQuizId())
                                .difficulty(quiz.getDifficulty())
                                .aiOutputSummary("퀴즈 " + appliedCount + "문항 생성 (범위 " +
                                                (quiz.getPageRange() == null ? "전체" : quiz.getPageRange()) + ")")
                                .userAction("QUIZ_GENERATED")
                                .build());

                return QuizDTO.Response.builder()
                                .quizId(quiz.getQuizId())
                                .materialId(materialId)
                                .difficulty(quiz.getDifficulty())
                                .questionCount(quiz.getQuestionCount())
                                .requestedCount(requestedCount)
                                .appliedCount(appliedCount)
                                .pageRange(quiz.getPageRange())
                                .quizData(quiz.getQuizData())
                                .quizzes(parseQuizData(quiz.getQuizData()))
                                .createdAt(quiz.getCreatedAt())
                                // G/H. 난이도 검증 전파 (ai07 제공 시), 없으면 요청값만 노출 → 프론트가 fallback 경고
                                .difficultyRequested(quizDifficulty)
                                .difficultyApplied(aiStr(response, "difficulty_applied"))
                                .difficultyPolicy(aiStr(response, "difficulty_policy"))
                                .difficultyValidation(aiMap(response, "difficulty_validation"))
                                .sourceTrace(aiMap(response, "source_trace"))
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

        // R. 퀴즈 문항 수 보정: null→10(기본), 5 미만→5, 20 초과→20.
        private int clampQuizCount(Integer count) {
                if (count == null) return 10;
                if (count < 5) return 5;
                if (count > 20) return 20;
                return count;
        }

        // F. 퀴즈 난이도 한글 라벨 → ai07 영문 contract (쉬움/보통/어려움 → easy/normal/hard)
        private String mapQuizDifficulty(String label) {
                if (label == null) return "normal";
                String v = label.trim().toLowerCase();
                if (v.equals("easy") || v.contains("쉬움") || v.contains("쉬운")) return "easy";
                if (v.equals("hard") || v.contains("어려움") || v.contains("어려운")) return "hard";
                return "normal"; // 보통/normal/medium 및 미상값 기본
        }

        private boolean isNotBlank(String s) { return s != null && !s.isBlank(); }

        private String truncQuiz(String s, int n) {
                if (s == null) return "";
                return s.length() > n ? s.substring(0, n) : s;
        }

        // AI에게 질문하기 (자료보관함 PDF 기반)
        @Transactional
        public QuestionDTO.Response askQuestion(Long userId, Long materialId, QuestionDTO.Request request) {
                Material material = getMaterialSafely(userId, materialId);

                // ── Intent Router 게이트 (surface=archive_chat) ───────────────────────────
                // terminal(DIRECT_REPLY/BLOCK/CLARIFY)이면 AI 호출 없이 라우터 메시지만 반환,
                // QUIZ/SUMMARY/ROADMAP이면 내부 파이프라인 직접 실행, WARN이면 경고 후 기존 답변 계속.
                IntentDTO.RouteResult route = intentRouterService.route(
                                request.getUserQuestion(), "archive_chat",
                                java.util.Map.of("materialId", materialId));
                if (route.isTerminal()) {
                        return routedQuestionResponse(material, request.getUserQuestion(), route.actionName(), route.userMessage(), null);
                }
                if (route.isPipeline()) {
                        return runArchivePipeline(userId, materialId, material, request, route);
                }
                String routeWarning = route.isWarn() ? route.userMessage() : null;

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
                                .routeAction(route.actionName())
                                .routeMessage(routeWarning)
                                .build();
        }

        // ── Intent Router: 자료보관함 라우팅 헬퍼 ────────────────────────────────────
        // terminal/파이프라인 결과를 QuestionDTO.Response로 감싼다. AI 에이전트는 호출하지 않으며 질문 이력도 저장하지 않는다.
        private QuestionDTO.Response routedQuestionResponse(Material material, String userQuestion,
                        String actionName, String message, Object pipeline) {
                return QuestionDTO.Response.builder()
                                .materialId(material != null ? material.getMaterialId() : null)
                                .userQuestion(userQuestion)
                                .aiAnswer(message)
                                .createdAt(java.time.LocalDateTime.now())
                                .success(true)
                                .routeAction(actionName)
                                .routeMessage(message)
                                .pipeline(pipeline)
                                .build();
        }

        // QUIZ/SUMMARY/ROADMAP 파이프라인을 Spring 내부에서 직접 실행. 자료보관함은 materialId를 유지한다.
        private QuestionDTO.Response runArchivePipeline(Long userId, Long materialId, Material material,
                        QuestionDTO.Request request, IntentDTO.RouteResult route) {
                switch (route.getAction()) {
                        case QUIZ_PIPELINE: {
                                if (materialId == null) {
                                        return routedQuestionResponse(material, request.getUserQuestion(), "CLARIFY",
                                                        "어떤 자료를 기준으로 문제를 만들까요?", null);
                                }
                                String difficulty = routeParamStr(route, "보통", "difficulty");
                                Integer count = routeParamInt(route, 10, "count", "questionCount", "question_count");
                                QuizDTO.Response quiz = generateQuiz(userId, materialId,
                                                new QuizDTO.Request(difficulty, count, "전체"));
                                return routedQuestionResponse(material, request.getUserQuestion(), "QUIZ_PIPELINE",
                                                "요청하신 문제를 생성했습니다.", quiz);
                        }
                        case SUMMARY_PIPELINE: {
                                SummaryDTO summary = getSummary(userId, materialId);
                                return routedQuestionResponse(material, request.getUserQuestion(), "SUMMARY_PIPELINE",
                                                "자료 요약을 정리했습니다.", summary);
                        }
                        case ROADMAP_PIPELINE: {
                                RoadmapDTO roadmap = getRoadmap(userId, materialId);
                                return routedQuestionResponse(material, request.getUserQuestion(), "ROADMAP_PIPELINE",
                                                "학습 로드맵을 불러왔습니다.", roadmap);
                        }
                        default:
                                return routedQuestionResponse(material, request.getUserQuestion(), route.actionName(),
                                                route.userMessage(), null);
                }
        }

        private String routeParamStr(IntentDTO.RouteResult route, String def, String... keys) {
                Map<String, Object> p = route.getParams();
                if (p != null) {
                        for (String k : keys) {
                                Object v = p.get(k);
                                if (v != null && !v.toString().isBlank()) return v.toString();
                        }
                }
                return def;
        }

        private Integer routeParamInt(IntentDTO.RouteResult route, int def, String... keys) {
                Map<String, Object> p = route.getParams();
                if (p != null) {
                        for (String k : keys) {
                                Object v = p.get(k);
                                if (v instanceof Number) return ((Number) v).intValue();
                                if (v != null) {
                                        try { return Integer.parseInt(v.toString().trim()); } catch (Exception ignored) {}
                                }
                        }
                }
                return def;
        }

        // 로드맵 조회
        @Transactional
        public RoadmapDTO getRoadmap(Long userId, Long materialId) {
                Material material = getMaterialSafely(userId, materialId);
                assertPdfAnalyzable(material, "주차별 로드맵");

                return roadmapRepository.findByMaterial_MaterialId(materialId)
                                .map(roadmap -> roadmapDtoFromEntity(material, roadmap))
                                .orElseGet(() -> generateRoadmap(material));
        }

        // 로드맵 재생성: 84일 구조로 새로 만든다. ai07 호출·검증 성공 시에만 기존(레거시 포함) 로드맵을 교체한다. (C/J)
        @Transactional
        public RoadmapDTO regenerateRoadmap(Long userId, Long materialId, String level) {
                Material material = getMaterialSafely(userId, materialId);
                // C/J. ai07 호출·검증이 성공한 뒤에만 기존 로드맵을 교체한다(실패 시 기존 로드맵 보존).
                return generateRoadmapInternal(material, normalizeRoadmapLevel(level), true);
        }

        // 난이도 정규화: 초보자/중급자/상급자 또는 영문 → beginner|intermediate|advanced (기본 intermediate)
        private String normalizeRoadmapLevel(String level) {
                if (level == null) return "intermediate";
                String v = level.trim().toLowerCase();
                if (v.equals("beginner") || v.contains("초보")) return "beginner";
                if (v.equals("advanced") || v.contains("상급") || v.contains("고급")) return "advanced";
                return "intermediate";
        }

        // 로드맵 생성 — ai07 /api/ai/roadmap/generate 호출로 12주 x 7일(84일) 구조를 만든다.
        // 응답 전체(weeks[].days[])를 roadmapJson 컬럼에 보존하고, roadmapData로 그대로 반환한다.
        private RoadmapDTO generateRoadmap(Material material) {
                return generateRoadmapInternal(material, "intermediate", false);
        }

        private RoadmapDTO generateRoadmapInternal(Material material, String level, boolean replaceExisting) {
                String textToAnalyze = getTextToAnalyze(material);
                if (textToAnalyze == null || textToAnalyze.isBlank()) {
                        return roadmapFailure(material, "PDF_TEXT_EMPTY", "문서에서 추출된 텍스트가 없습니다. 다시 분석을 시도해주세요.", true, null);
                }

                String userGoal = "학습 목표 달성";
                if (material.getTitle() != null && !material.getTitle().isBlank()) {
                        userGoal = material.getTitle() + " 학습 및 핵심 목표 달성";
                }

                // ai07이 요구하는 입력: title, summary, keywords[], user_goal, level + 84일 차원(weeks, days_per_week).
                String summaryText = textToAnalyze.length() > 6000 ? textToAnalyze.substring(0, 6000) : textToAnalyze;
                List<String> keywordList = new java.util.ArrayList<>();
                if (material.getKeywords() != null && !material.getKeywords().isBlank()) {
                        for (String k : material.getKeywords().split(",")) {
                                if (!k.trim().isBlank()) keywordList.add(k.trim());
                        }
                }

                Map<String, Object> requestBody = new LinkedHashMap<>();
                requestBody.put("title", material.getTitle() != null ? material.getTitle() : "학습 로드맵");
                requestBody.put("summary", summaryText);
                requestBody.put("keywords", keywordList);
                requestBody.put("user_goal", userGoal);
                // 난이도(B/C): level + difficulty 둘 다 전송해 ai07 contract 변형에 모두 대응. academic_level은 별도 유지.
                String roadmapLevel = normalizeRoadmapLevel(level);
                requestBody.put("level", roadmapLevel);
                requestBody.put("difficulty", roadmapLevel);
                requestBody.put("academic_level", "undergraduate");
                requestBody.put("weeks", ROADMAP_TOTAL_WEEKS);
                requestBody.put("days_per_week", ROADMAP_DAYS_PER_WEEK);

                long t0 = System.currentTimeMillis();
                Map response;
                try {
                        response = fastApiWebClient.post().uri("/api/ai/roadmap/generate")
                                        .bodyValue(requestBody).retrieve().bodyToMono(Map.class)
                                        .block(Duration.ofSeconds(roadmapTimeoutSeconds));
                } catch (Exception e) {
                        String __code = isTimeout(e) ? "AI_TIMEOUT" : "UNKNOWN_ERROR";
                        logRoadmapFailure(material.getMaterialId(), __code, e.getMessage(), null, null, System.currentTimeMillis() - t0);
                        return roadmapFailure(material, __code, null, true, null);
                }

                if (isAiFailure(response)) {
                        String __code = aiStr(response, "errorCode");
                        logRoadmapFailure(material.getMaterialId(), __code, aiStr(response, "message"), roadmapValidationReason(response), response, System.currentTimeMillis() - t0);
                        return roadmapFailure(material, __code, aiStr(response, "message"), aiBool(response, "retryable", true), response);
                }

                String __invalidReason = roadmapStructureInvalidReason(response);
                if (__invalidReason != null) {
                        logRoadmapFailure(material.getMaterialId(), "ROADMAP_VALIDATE_FAILED", "84일 구조 검증 실패", __invalidReason, response, System.currentTimeMillis() - t0);
                        return roadmapFailure(material, "ROADMAP_VALIDATE_FAILED", "84일(12주 × 7일) 로드맵 구조 검증에 실패했습니다. 다시 시도해주세요.", true, response);
                }

                String roadmapTitle = "AI 생성 학습 로드맵";
                if (response != null && response.get("title") != null) {
                        roadmapTitle = response.get("title").toString();
                }

                // 저장 직전 노이즈 정제: PDF 표지 날짜/교수명/코스 제목 등이 day title/objective/tasks/질문/산출물에
                // 섞여 있으면 제거하고, 비면 개념형 fallback으로 채운다. response Map을 in-place 수정.
                int[] noiseStats = sanitizeRoadmapNoise(response, material);

                // 84일 응답 전체를 JSON 문자열로 보존(컬럼: roadmap_json). days를 절대 버리지 않는다.
                String roadmapJson;
                try {
                        roadmapJson = AI_OBJECT_MAPPER.writeValueAsString(response);
                } catch (Exception e) {
                        log.error("[roadmap:fail] code=ROADMAP_JSON_SERIALIZE materialId={} msg={}", material.getMaterialId(), e.getMessage());
                        return roadmapFailure(material, "ROADMAP_GENERATION_FAILED", "로드맵 데이터 처리 중 오류가 발생했습니다. 다시 시도해주세요.", true, null);
                }
                if (replaceExisting) {
                        roadmapRepository.findByMaterial_MaterialId(material.getMaterialId()).ifPresent(roadmapRepository::delete);
                        roadmapRepository.flush();
                }

                Roadmap roadmap = Roadmap.builder()
                                .material(material)
                                .userId(material.getUserId())
                                .title(roadmapTitle)
                                .roadmapJson(roadmapJson)
                                .build();

                try {
                        roadmap = roadmapRepository.save(roadmap);
                } catch (Exception e) {
                        log.error("[roadmap:fail] code=ROADMAP_SAVE_FAILED materialId={} message={}", material.getMaterialId(), e.getMessage(), e);
                        return roadmapFailure(material, "ROADMAP_GENERATION_FAILED", "주차별 로드맵 저장 중 오류가 발생했습니다. 다시 시도해주세요.", true, null);
                }

                // 노이즈 검증 결과 로깅 (noiseCandidate/cleaned/rejected/fallback)
                boolean roadmapFallbackUsed = noiseStats[3] > 0;
                log.info("[roadmap:validation] materialId={} roadmapId={} noiseCandidates={} cleaned={} rejected={} fallbackUsed={} reason={}",
                                material.getMaterialId(), roadmap.getRoadmapId(),
                                noiseStats[0], noiseStats[1], noiseStats[2], roadmapFallbackUsed,
                                roadmapFallbackUsed ? "metadata_noise" : "none");

                return roadmapDtoFromJson(material, roadmap, response);
        }
        // C. ai07 로드맵 검증 사유 추출 (없으면 null)
        @SuppressWarnings("unchecked")
        private String roadmapValidationReason(Map response) {
                Map<String, Object> v = aiMap(response, "validation");
                if (v == null) v = aiMap(response, "difficulty_validation");
                Object reason = v != null ? v.get("reason") : null;
                return reason != null ? reason.toString() : null;
        }

        // C. 84일 로드맵 응답 구조 검증: weeks 12개 · 총 84일 · 각 day에 title/objective/tasks. 실패 사유 반환(정상 null).
        @SuppressWarnings("unchecked")
        private String roadmapStructureInvalidReason(Map response) {
                if (response == null) return "응답 없음";
                Object weeksRaw = response.get("weeks");
                if (!(weeksRaw instanceof List)) return "weeks 배열 없음";
                List<Object> weeks = (List<Object>) weeksRaw;
                if (weeks.size() != ROADMAP_TOTAL_WEEKS) return "weeks 길이=" + weeks.size() + " (기대 " + ROADMAP_TOTAL_WEEKS + ")";
                int totalDays = 0;
                for (Object wkRaw : weeks) {
                        if (!(wkRaw instanceof Map)) return "week 항목 형식 오류";
                        Object daysRaw = ((Map<String, Object>) wkRaw).get("days");
                        if (!(daysRaw instanceof List)) return "days 배열 없음";
                        for (Object dRaw : (List<Object>) daysRaw) {
                                totalDays++;
                                if (!(dRaw instanceof Map)) return "day 항목 형식 오류";
                                Map<String, Object> d = (Map<String, Object>) dRaw;
                                if (isBlankObj(d.get("title"))) return "day title 누락";
                                if (isBlankObj(d.get("objective"))) return "day objective 누락";
                                Object tasks = d.get("tasks");
                                if (!(tasks instanceof List) || ((List<?>) tasks).isEmpty()) return "day tasks 누락";
                        }
                }
                if (totalDays != ROADMAP_TOTAL_WEEKS * ROADMAP_DAYS_PER_WEEK) {
                        return "총 일수=" + totalDays + " (기대 " + (ROADMAP_TOTAL_WEEKS * ROADMAP_DAYS_PER_WEEK) + ")";
                }
                return null;
        }

        private boolean isBlankObj(Object v) {
                return v == null || v.toString().isBlank();
        }

        // ── 로드맵 노이즈 정제 (저장 직전, response Map in-place 수정) ───────────────────────────────
        // 반환 stats: [0]=noiseCandidate, [1]=cleaned, [2]=rejected, [3]=fallbackUsedFields
        @SuppressWarnings("unchecked")
        private int[] sanitizeRoadmapNoise(Map response, Material material) {
                int[] stats = new int[4];
                if (response == null) return stats;
                String courseTitle = (material != null) ? material.getTitle() : null;
                Object weeksRaw = response.get("weeks");
                if (!(weeksRaw instanceof List)) return stats;
                int dayCounter = 0;
                for (Object wkRaw : (List<Object>) weeksRaw) {
                        if (!(wkRaw instanceof Map)) continue;
                        Map<String, Object> wk = (Map<String, Object>) wkRaw;
                        Object daysRaw = wk.get("days");
                        if (!(daysRaw instanceof List)) continue;
                        for (Object dRaw : (List<Object>) daysRaw) {
                                if (!(dRaw instanceof Map)) continue;
                                Map<String, Object> d = (Map<String, Object>) dRaw;
                                ConceptFallbackProvider.Concept fb = ConceptFallbackProvider.forTopicAt(courseTitle, dayCounter++);

                                d.put("title", sanitizeRequiredField(d.get("title"), courseTitle, fb.title, stats));
                                d.put("objective", sanitizeRequiredField(d.get("objective"), courseTitle, fb.objective, stats));
                                d.put("core_concepts", sanitizeStrList(d.get("core_concepts"), courseTitle, fb.coreConcepts, stats));
                                d.put("tasks", sanitizeTaskList(d.get("tasks"), courseTitle, fb.tasks, stats));
                                d.put("review_questions", sanitizeStrList(d.get("review_questions"), courseTitle, fb.reviewQuestions, stats));
                                if (d.containsKey("deliverable")) {
                                        d.put("deliverable", sanitizeOptionalField(d.get("deliverable"), courseTitle, fb.deliverable, stats));
                                }
                                if (d.containsKey("checkpoint")) {
                                        d.put("checkpoint", sanitizeOptionalField(d.get("checkpoint"), courseTitle, "", stats));
                                }
                        }
                }
                return stats;
        }

        // 필수 필드(title/objective): 비거나 노이즈면 fallback 으로 대체.
        private String sanitizeRequiredField(Object raw, String courseTitle, String fallback, int[] stats) {
                String s = (raw == null) ? null : raw.toString();
                if (s == null || s.isBlank()) { stats[3]++; return fallback; }
                if (LearningContentSanitizer.isNoise(s, courseTitle)) {
                        stats[0]++; stats[2]++; stats[3]++; return fallback;
                }
                String c = LearningContentSanitizer.clean(s);
                if (!c.equals(s.trim())) stats[1]++;
                return c;
        }

        // 선택 필드(deliverable/checkpoint): 비면 그대로 비움. 노이즈면 정제 후에도 부적합 → fallback(빈문자 허용).
        private String sanitizeOptionalField(Object raw, String courseTitle, String fallback, int[] stats) {
                String s = (raw == null) ? null : raw.toString();
                if (s == null || s.isBlank()) return "";
                if (LearningContentSanitizer.isNoise(s, courseTitle)) {
                        stats[0]++; stats[2]++;
                        if (fallback != null && !fallback.isBlank()) stats[3]++;
                        return fallback == null ? "" : fallback;
                }
                String c = LearningContentSanitizer.clean(s);
                if (!c.equals(s.trim())) stats[1]++;
                return c;
        }

        // 문자열 리스트(core_concepts/review_questions): 정제+노이즈 제거, 전부 비면 fallback.
        private List<String> sanitizeStrList(Object raw, String courseTitle, List<String> fallback, int[] stats) {
                List<String> in = new ArrayList<>();
                if (raw instanceof List) {
                        for (Object o : (List<?>) raw) {
                                if (o == null) continue;
                                if (o instanceof Map) {
                                        Object t = ((Map<?, ?>) o).get("title");
                                        if (t == null) t = ((Map<?, ?>) o).get("content");
                                        if (t != null) in.add(t.toString());
                                } else {
                                        in.add(o.toString());
                                }
                        }
                }
                int before = in.size();
                List<String> out = LearningContentSanitizer.cleanList(in, courseTitle);
                int dropped = before - out.size();
                if (dropped > 0) { stats[0] += dropped; stats[2] += dropped; }
                if (out.isEmpty()) { stats[3]++; return new ArrayList<>(fallback); }
                return out;
        }

        // tasks: 문자열/객체({title,...}) 혼용. 요소 타입을 보존하며 정제, 노이즈는 드롭, 전부 비면 fallback(문자열).
        @SuppressWarnings("unchecked")
        private List<Object> sanitizeTaskList(Object raw, String courseTitle, List<String> fallback, int[] stats) {
                List<Object> out = new ArrayList<>();
                if (raw instanceof List) {
                        for (Object el : (List<Object>) raw) {
                                if (el instanceof Map) {
                                        Map<String, Object> m = (Map<String, Object>) el;
                                        Object t = m.get("title");
                                        if (t == null) t = m.get("content");
                                        if (t == null) t = m.get("description");
                                        String ts = (t == null) ? null : t.toString();
                                        if (ts == null || LearningContentSanitizer.isNoise(ts, courseTitle)) {
                                                if (ts != null) { stats[0]++; stats[2]++; }
                                                continue;
                                        }
                                        String c = LearningContentSanitizer.clean(ts);
                                        if (m.containsKey("title")) m.put("title", c);
                                        else if (m.containsKey("content")) m.put("content", c);
                                        else m.put("title", c);
                                        out.add(m);
                                } else if (el != null) {
                                        String s = el.toString();
                                        if (LearningContentSanitizer.isNoise(s, courseTitle)) { stats[0]++; stats[2]++; continue; }
                                        out.add(LearningContentSanitizer.clean(s));
                                }
                        }
                }
                if (out.isEmpty()) { stats[3]++; out.addAll(fallback); }
                return out;
        }

        // C. 로드맵 실패 상세 로그 (민감정보 제외: AWS key/token/presigned URL/문서 원문 전체 금지). body는 앞 1000자만.
        private void logRoadmapFailure(Long materialId, String errorCode, String message, String validationReason, Map response, long elapsedMs) {
                String body = "";
                try {
                        if (response != null) {
                                String json = AI_OBJECT_MAPPER.writeValueAsString(response);
                                body = json.length() > 1000 ? json.substring(0, 1000) : json;
                        }
                } catch (Exception ignored) { }
                log.error("[roadmap:fail] endpoint=/api/ai/roadmap/generate materialId={} errorCode={} message={} validationReason={} elapsedMs={} body={}",
                                materialId, errorCode, message, validationReason, elapsedMs, body);
        }



        // 84일 JSON 응답(map)을 그대로 roadmapData에 실어 DTO로 만든다.
        @SuppressWarnings("unchecked")
        private RoadmapDTO roadmapDtoFromJson(Material material, Roadmap roadmap, Map response) {
                Integer totalWeeks = aiInt(response.get("total_weeks"), ROADMAP_TOTAL_WEEKS);
                return RoadmapDTO.builder()
                                .roadmapId(roadmap.getRoadmapId())
                                .materialId(material.getMaterialId())
                                .title(roadmap.getTitle())
                                .roadmapData(response)
                                .totalWeeks(totalWeeks)
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

        // 자료보관함 84일 로드맵 — day 단위 완료 토글. roadmapJson 안의 weeks[w].days[d].completed 를 뒤집어 저장.
        @Transactional
        public RoadmapDTO toggleRoadmapDay(Long userId, Long materialId, int week, int dayIndex) {
                Material material = getMaterialSafely(userId, materialId);
                Roadmap roadmap = roadmapRepository.findByMaterial_MaterialId(materialId)
                                .orElseThrow(() -> new IllegalArgumentException("로드맵을 찾을 수 없습니다."));
                if (roadmap.getRoadmapJson() == null || roadmap.getRoadmapJson().isBlank()) {
                        throw new IllegalStateException("이 로드맵은 일자 토글을 지원하지 않는 이전 형식입니다. 다시 생성해주세요.");
                }
                Map<String, Object> data;
                try {
                        data = AI_OBJECT_MAPPER.readValue(roadmap.getRoadmapJson(), new TypeReference<Map<String, Object>>() {});
                } catch (Exception e) {
                        throw new IllegalStateException("로드맵 데이터를 읽을 수 없습니다.");
                }
                List<Map<String, Object>> weeks = (List<Map<String, Object>>) data.get("weeks");
                if (weeks != null) {
                        for (Map<String, Object> w : weeks) {
                                if (aiInt(w.get("week"), -1) == week) {
                                        List<Map<String, Object>> days = (List<Map<String, Object>>) w.get("days");
                                        if (days != null) {
                                                for (Map<String, Object> dy : days) {
                                                        if (aiInt(dy.get("day_index"), -1) == dayIndex) {
                                                                Object c = dy.get("completed");
                                                                dy.put("completed", !(c instanceof Boolean && (Boolean) c));
                                                        }
                                                }
                                        }
                                }
                        }
                }
                try {
                        roadmap.setRoadmapJson(AI_OBJECT_MAPPER.writeValueAsString(data));
                        roadmapRepository.save(roadmap);
                } catch (Exception e) {
                        throw new IllegalStateException("로드맵 저장에 실패했습니다.");
                }
                return roadmapDtoFromJson(material, roadmap, data);
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
                        // ai07 미배포(404)/연결불가 시 500 대신 화면 친화 fallback 으로 변환 (기존 UI가 success=false 를 안내 표시)
                        boolean unavailable = (e instanceof org.springframework.web.reactive.function.client.WebClientResponseException
                                        && ((org.springframework.web.reactive.function.client.WebClientResponseException) e).getStatusCode().value() == 404)
                                        || String.valueOf(e.getMessage()).toLowerCase().contains("not found")
                                        || (e.getCause() instanceof java.net.ConnectException);
                        return KeywordDefineDTO.Response.builder()
                                        .success(false)
                                        .errorCode(unavailable ? "AI_ROUTE_NOT_AVAILABLE" : "AI_ERROR")
                                        .message(unavailable
                                                        ? "AI 서버의 키워드 정의 기능이 아직 배포되지 않았습니다. 잠시 후 다시 시도해주세요."
                                                        : "키워드 정의 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.")
                                        .build();
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
