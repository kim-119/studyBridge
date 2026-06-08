package com.studybridge.api.service;

import com.studybridge.api.dto.*;
import com.studybridge.api.entity.*;
import com.studybridge.api.repository.*;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import org.springframework.web.reactive.function.client.WebClient;

import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.LinkedHashMap;
import java.util.stream.Collectors;

// 자료보관함 AI 호출 hard timeout (무한 대기 방지). 전체 2분 예산 내(120~125초).

@Service
@RequiredArgsConstructor
@Transactional(readOnly = true)
public class AiIntegrationService {

        private final MaterialRepository materialRepository;
        private final MaterialSummaryRepository summaryRepository;
        private final MaterialFeedbackRepository feedbackRepository;
        private final MaterialQuizRepository quizRepository;
        private final MaterialMemoRepository memoRepository;
        private final MaterialQuestionRepository questionRepository;
        private final RoadmapRepository roadmapRepository;
        private final RoadmapTaskRepository roadmapTaskRepository;
        private final WebClient fastApiWebClient;

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
                                .map(summary -> SummaryDTO.builder()
                                                .summaryId(summary.getSummaryId())
                                                .materialId(materialId)
                                                .overview(summary.getOverview())
                                                .coreContents(summary.getCoreContents())
                                                .success(true)
                                                .textStatus(textStatusFor(material, getTextToAnalyze(material)))
                                                .build())
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

                MaterialSummary summary = MaterialSummary.builder()
                                .material(material)
                                .overview(response != null && response.containsKey("overview")
                                                ? response.get("overview").toString()
                                                : "요약 생성 실패")
                                .coreContents(response != null && response.containsKey("coreContents")
                                                ? response.get("coreContents").toString()
                                                : "[]")
                                .build();
                summary = summaryRepository.save(summary);

                return SummaryDTO.builder()
                                .summaryId(summary.getSummaryId())
                                .materialId(material.getMaterialId())
                                .overview(summary.getOverview())
                                .coreContents(summary.getCoreContents())
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
                getMaterialSafely(userId, materialId);
                return quizRepository.findByMaterial_MaterialIdOrderByCreatedAtDesc(materialId)
                                .stream()
                                .map(quiz -> QuizDTO.Response.builder()
                                                .quizId(quiz.getQuizId())
                                                .materialId(materialId)
                                                .difficulty(quiz.getDifficulty())
                                                .questionCount(quiz.getQuestionCount())
                                                .pageRange(quiz.getPageRange())
                                                .quizData(quiz.getQuizData())
                                                .createdAt(quiz.getCreatedAt())
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
                                .map(roadmap -> RoadmapDTO.builder()
                                                .roadmapId(roadmap.getRoadmapId())
                                                .materialId(materialId)
                                                .title(roadmap.getTitle())
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
                                                                                                .collect(Collectors
                                                                                                                .toList()))
                                                                                .build())
                                                                .collect(Collectors.toList()))
                                                .success(true)
                                                .textStatus(textStatusFor(material, getTextToAnalyze(material)))
                                                .build())
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

                roadmap = roadmapRepository.save(roadmap);

                return RoadmapDTO.builder()
                                .roadmapId(roadmap.getRoadmapId())
                                .materialId(material.getMaterialId())
                                .title(roadmap.getTitle())
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

                if (!task.getStep().getRoadmap().getMaterial().getMaterialId().equals(materialId)) {
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
}
