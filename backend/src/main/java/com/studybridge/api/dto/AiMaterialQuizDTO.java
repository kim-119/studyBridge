package com.studybridge.api.dto;

import com.fasterxml.jackson.annotation.JsonAlias;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * AI07 FINAL CONTRACT — {@code POST /api/ai/quiz}(자료 퀴즈, HTTP 항상 200, 성공 여부 = success) typed 응답.
 * Spring ↔ AI07 전용(내부). 정답 키(answer/answerIndex/correctAnswer/correctOptionIds/explanation/wrongExplanations/sourceTrace)
 * 를 포함하므로 브라우저에 그대로 내려주면 안 된다 — 공개 DTO 는 {@link QuizDTO}.
 */
public class AiMaterialQuizDTO {

    public static final String SCHEMA_VERSION = "quiz.v2";
    public static final String STATUS_OK = "OK";
    public static final String STATUS_PARTIAL = "PARTIAL";
    public static final String STATUS_DEGRADED_FALLBACK = "DEGRADED_FALLBACK";
    public static final String STATUS_FAILED = "FAILED";

    @Getter
    @Setter
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class Response {
        private Boolean success;
        private String errorCode;
        private String message;
        private Boolean retryable;
        private String schemaVersion;
        private String quizId;
        private String status;                 // OK | PARTIAL | DEGRADED_FALLBACK | FAILED
        private Boolean degraded;
        private String degradedReason;
        private Boolean fallbackUsed;
        private Integer fallbackQuestionCount;
        private Boolean partial;
        private Integer requestedCount;
        private Integer generatedCount;
        private Integer rejectedCount;
        @Builder.Default
        private List<String> answerKeyFields = new ArrayList<>();
        private String quizData;               // 정답 포함 원문 JSON — 내부 보관용, 브라우저 금지
        @Builder.Default
        private List<Question> quizzes = new ArrayList<>();
        @Builder.Default
        private List<String> warnings = new ArrayList<>();
        @Builder.Default
        private Map<String, Object> metadata = new LinkedHashMap<>();
        // 난이도 정책/검증 (기존 Spring 이 읽던 snake_case 키 유지)
        @JsonAlias({"difficulty_applied"})
        private String difficultyApplied;
        @JsonAlias({"difficulty_requested"})
        private String difficultyRequested;
        @JsonAlias({"difficulty_policy"})
        private String difficultyPolicy;
        @JsonAlias({"difficulty_validation"})
        private Map<String, Object> difficultyValidation;
        @JsonAlias({"source_trace"})
        private Map<String, Object> sourceTrace;  // top-level 출제 근거 — 브라우저 초기 payload 에서 제거 대상
        @JsonAlias({"text_status"})
        private Map<String, Object> textStatus;
    }

    /** 문항. answer == answerIndex == correctAnswer(0-based), correctOptionIds[0] == optionIds[correctAnswer]. */
    @Getter
    @Setter
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class Question {
        private String questionId;
        private String question;
        private String questionType;           // multiple_choice
        private String answerType;             // SINGLE_CHOICE
        @Builder.Default
        private List<String> options = new ArrayList<>();
        @Builder.Default
        private List<String> optionIds = new ArrayList<>(); // ["A","B","C","D"]
        private Integer answer;
        private Integer answerIndex;
        private Integer correctAnswer;
        @Builder.Default
        private List<String> correctOptionIds = new ArrayList<>();
        private String explanation;
        @Builder.Default
        private List<String> wrongExplanations = new ArrayList<>();
        private String difficulty;
        private Map<String, Object> sourceTrace;
        private Integer page;
    }
}
