package com.studybridge.api.service;

import com.studybridge.api.dto.*;
import com.studybridge.api.entity.*;
import com.studybridge.api.repository.*;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import org.springframework.web.reactive.function.client.WebClient;

import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

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
                if (material.getMaterialType() == MaterialType.STUDY_LOG) {
                        return material.getLearningContent();
                } else {
                        return material.getExtractedText();
                }
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
                                                .build())
                                .orElseGet(() -> generateSummary(material));
        }

        private SummaryDTO generateSummary(Material material) {
<<<<<<< HEAD
                if (material.getExtractedText() == null || material.getExtractedText().isBlank()) {
                        throw new IllegalArgumentException("텍스트가 아직 추출되지 않아 요약을 생성할 수 없습니다.");
                }

                Map<String, Object> requestBody = Map.of("text", material.getExtractedText());
=======
                String textToAnalyze = getTextToAnalyze(material);
                if (textToAnalyze == null || textToAnalyze.isBlank()) {
                        throw new IllegalArgumentException("학습 일지 또는 추출된 텍스트 내용이 비어 있어 요약을 생성할 수 없습니다.");
                }

                Map<String, Object> requestBody = Map.of("text", textToAnalyze);
>>>>>>> 45414b3 (update fastapi)
                Map response;
                try {
                        response = fastApiWebClient.post().uri("/api/ai/summary")
                                        .bodyValue(requestBody).retrieve().bodyToMono(Map.class).block();
                } catch (Exception e) {
                        throw new RuntimeException("AI 서버에서 요약 생성 중 오류가 발생했습니다: " + e.getMessage());
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
<<<<<<< HEAD
                if (material.getLearningContent() == null || material.getLearningContent().isBlank()) {
                        throw new IllegalArgumentException("학습 내용이 없어 피드백을 생성할 수 없습니다.");
                }

                Map<String, Object> requestBody = Map.of("content", material.getLearningContent());
=======
                String textToAnalyze = getTextToAnalyze(material);
                if (textToAnalyze == null || textToAnalyze.isBlank()) {
                        throw new IllegalArgumentException("학습 내용 또는 추출된 텍스트가 없어 피드백을 생성할 수 없습니다.");
                }

                Map<String, Object> requestBody = Map.of("content", textToAnalyze);
>>>>>>> 45414b3 (update fastapi)
                Map response;
                try {
                        response = fastApiWebClient.post().uri("/api/ai/feedback")
                                        .bodyValue(requestBody).retrieve().bodyToMono(Map.class).block();
                } catch (Exception e) {
                        throw new RuntimeException("AI 서버에서 피드백 생성 중 오류가 발생했습니다: " + e.getMessage());
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

<<<<<<< HEAD
                if (material.getExtractedText() == null || material.getExtractedText().isBlank()) {
                        throw new IllegalArgumentException("텍스트가 아직 추출되지 않아 퀴즈를 생성할 수 없습니다.");
=======
                String textToAnalyze = getTextToAnalyze(material);
                if (textToAnalyze == null || textToAnalyze.isBlank()) {
                        throw new IllegalArgumentException("자료의 텍스트가 비어 있어 퀴즈를 생성할 수 없습니다.");
>>>>>>> 45414b3 (update fastapi)
                }

                Map<String, Object> requestBody = Map.of(
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
                                        .block(); // 동기식 대기
                } catch (Exception e) {
                        throw new RuntimeException("AI 서버에서 퀴즈 생성 중 오류가 발생했습니다: " + e.getMessage());
                }

                String generatedQuizJson = "[]";
                if (response != null && response.containsKey("quizData")) {
                        // ObjectMapper 등을 통해 문자열로 저장하거나, FastAPI가 String 형태로 줬다고 가정
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
                                .build();
        }

        // AI에게 질문하기
        @Transactional
        public QuestionDTO.Response askQuestion(Long userId, Long materialId, QuestionDTO.Request request) {
                Material material = getMaterialSafely(userId, materialId);

<<<<<<< HEAD
                if (material.getExtractedText() == null || material.getExtractedText().isBlank()) {
                        throw new IllegalArgumentException("자료의 텍스트가 없어 질문할 수 없습니다.");
=======
                String textToAnalyze = getTextToAnalyze(material);
                if (textToAnalyze == null || textToAnalyze.isBlank()) {
                        throw new IllegalArgumentException("자료의 텍스트가 비어 있어 질문할 수 없습니다.");
>>>>>>> 45414b3 (update fastapi)
                }

                Map<String, Object> requestBody = Map.of(
                                "text", textToAnalyze,
                                "question", request.getUserQuestion());

                Map response;
                try {
                        response = fastApiWebClient.post()
                                        .uri("/api/ai/question")
                                        .bodyValue(requestBody)
                                        .retrieve()
                                        .bodyToMono(Map.class)
                                        .block(); // 동기식 대기
                } catch (Exception e) {
                        throw new RuntimeException("AI 서버와 통신 중 오류가 발생했습니다: " + e.getMessage());
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
                                                .build())
                                .orElseGet(() -> generateRoadmap(material));
        }

        // 로드맵 생성
        private RoadmapDTO generateRoadmap(Material material) {
<<<<<<< HEAD
                if (material.getExtractedText() == null || material.getExtractedText().isBlank()) {
                        throw new IllegalArgumentException("텍스트가 아직 추출되지 않아 로드맵을 생성할 수 없습니다.");
=======
                String textToAnalyze = getTextToAnalyze(material);
                if (textToAnalyze == null || textToAnalyze.isBlank()) {
                        throw new IllegalArgumentException("자료의 텍스트가 비어 있어 로드맵을 생성할 수 없습니다.");
                }

                String userGoal = "학습 목표 달성";
                if (material.getTitle() != null && !material.getTitle().isBlank()) {
                        userGoal = material.getTitle() + " 학습 및 핵심 목표 달성";
>>>>>>> 45414b3 (update fastapi)
                }

                Map<String, Object> requestBody = Map.of(
                        "material_id", material.getMaterialId(),
                        "pdf_text", textToAnalyze,
                        "user_goal", userGoal
                );

                Map response;
                try {
                        response = fastApiWebClient.post().uri("/api/ai/roadmap")
                                        .bodyValue(requestBody).retrieve().bodyToMono(Map.class).block();
                } catch (Exception e) {
                        throw new RuntimeException("AI 서버에서 로드맵 생성 중 오류가 발생했습니다: " + e.getMessage());
                }

                // roadmap 오브젝트 파싱
                Map<String, Object> roadmapMap = null;
                if (response != null && response.containsKey("roadmap")) {
                        roadmapMap = (Map<String, Object>) response.get("roadmap");
                }

                String roadmapTitle = "AI 생성 학습 로드맵";
                if (roadmapMap != null && roadmapMap.containsKey("title")) {
                        roadmapTitle = roadmapMap.get("title").toString();
                }

                // 엔티티 생성
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
                                                .stepOrder(stepMap.containsKey("stepOrder")
                                                                ? (Integer) stepMap.get("stepOrder")
                                                                : 1)
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
                                                                .taskOrder(taskMap.containsKey("taskOrder")
                                                                                ? (Integer) taskMap.get("taskOrder")
                                                                                : 1)
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

                // 저장된 엔티티를 DTO로 변환하여 반환
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
                                .build();
        }

        // 로드맵 태스크 완료 상태 토글
        @Transactional
        public RoadmapDTO.RoadmapTaskDTO toggleRoadmapTask(Long userId, Long materialId, Long taskId) {
                // 권한 체크
                getMaterialSafely(userId, materialId);
                
                RoadmapTask task = roadmapTaskRepository.findById(taskId)
                                .orElseThrow(() -> new IllegalArgumentException("해당 할 일을 찾을 수 없습니다."));

                // 해당 Task가 요청된 Material의 Roadmap에 속하는지 검증
                if (!task.getStep().getRoadmap().getMaterial().getMaterialId().equals(materialId)) {
                        throw new SecurityException("잘못된 접근입니다.");
                }

                // 토글 수행
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
