package com.studybridge.api.dto;

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
        private Integer correctAnswer; // 0-based choice index
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
    }

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class AIQuizResponse {
        private String quizTitle;
        private List<AIQuestion> questions;
    }

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class AIQuestion {
        private String question;
        private List<String> options;
        private Integer correctAnswer;
        private Integer timeLimitSeconds;
    }
}
