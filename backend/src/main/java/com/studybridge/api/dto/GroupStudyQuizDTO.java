package com.studybridge.api.dto;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;
import java.util.List;

public class GroupStudyQuizDTO {

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class QuizResponse {
        private Long id;
        private Long groupStudyId;
        private String title;
        private Integer rewardPoints;
        private Long creatorId;
        private String creatorName;
        private LocalDateTime createdAt;
        private Integer questionCount;
        private List<QuestionResponse> questions;
    }

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class QuestionResponse {
        private Long id;
        private String question;
        private List<String> options; // JSON Array deserialized to list of choices
        // 공개 DTO: 정답(correctAnswer)은 싣지 않는다. 정답은 세션 REVEALING/COMPLETED payload 에서만 공개된다.
        private Integer timeLimitSeconds;
    }

    // 퀴즈 생성자가 지정하는 생성 옵션 (문제 수 / 문제당 제한시간)
    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class QuizGenerateOptions {
        private Integer questionCount;
        private Integer timeLimitSeconds;
    }

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class AIQuizRequest {
        private Long materialId;
        private String s3Key;
        private String fileName;
        private Integer numQuestions; // FastAPI에 전달할 생성 문항 수 (null이면 기본값)
        // PDF 근거 강제: true 면 AI07 은 S3/PDF/검증 실패 시 일반 공부법 placeholder 대신 success=false 로 응답한다.
        @Builder.Default
        private Boolean strictGrounding = Boolean.TRUE;
    }

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class AIQuizResponse {
        private String quizTitle;
        private List<AIQuestion> questions;
        // ── AI07 QuizGenerateResponse 구조화 상태(실측 OpenAPI 0.6.0) ──
        private Boolean success;
        private String errorCode;
        private String message;
        private String warning;
        // ── quiz.v2 additive metadata(AI07 hardened 경로가 제공하면 수용, 없으면 null) ──
        private String schemaVersion;
        private String quizId;
        private String status;        // OK | DEGRADED | FAILED ...
        private Boolean degraded;
        private Boolean fallbackUsed;
        private List<String> answerKeyFields;
    }

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    @JsonIgnoreProperties(ignoreUnknown = true)
    public static class AIQuestion {
        private String question;
        private List<String> options;
        private Integer correctAnswer;
        private Integer timeLimitSeconds;
        private String explanation;
        private String questionType;
        // ── quiz.v2 additive ──
        private String questionId;
        private String answerType;
        private List<String> optionIds;
        private List<String> correctOptionIds;
    }
}
