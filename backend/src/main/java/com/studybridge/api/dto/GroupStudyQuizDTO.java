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
        // 품질 게이트(response-quality.v1, PDF_QUIZ). 게이트 OFF 면 null → JSON 미출력(기존 응답과 동일).
        // qualityRedacted=true: 미검증 저장 퀴즈라 AI 생성 제목을 고정 문구로 가렸다.
        @com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
        private String qualityStatus;
        @com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
        private Double qualityScore;
        @com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
        private Boolean verified;
        @com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
        private Boolean qualityRedacted;
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
        // 품질 게이트 재생성 시도(1..2)와 직전 거절 사유 코드. 게이트 OFF·최초 시도는 null → JSON 미출력(기존 payload 와 동일).
        // AI07 QuizGenerateRequest 는 extra="ignore" 라 모르는 필드는 무시한다(인계 C-RQ-3: 재생성 힌트 수용 요청).
        @com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
        private Integer regenerationAttempt;
        @com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
        private List<String> regenerationHints;
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
