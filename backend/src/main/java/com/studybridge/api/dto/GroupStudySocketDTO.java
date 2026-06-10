package com.studybridge.api.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.List;

public class GroupStudySocketDTO {

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    public static class ChatPayload {
        private String senderName;
        private String content;
        private String timestamp;
    }

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    public static class QuizStartPayload {
        private Long quizId;
        private Long userId;
    }

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    public static class AnswerSubmitPayload {
        private Long userId;
        private Long questionId;
        private Integer submittedAnswer;
        private Integer timeTakenSeconds;
    }

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class QuestionBroadcastPayload {
        private Long quizId;
        private String quizTitle;
        private Long questionId;
        private String questionText;
        private List<String> options;
        private Integer currentIndex;
        private Integer totalQuestions;
        private Integer timeLimitSeconds;
    }

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class GradingPayload {
        private Long questionId;
        private Boolean isCorrect;
        private Integer pointsEarned;
        private Integer correctAnswer;
    }

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    public static class ScoreboardEntry {
        private Long userId;
        private String displayName;
        private Integer points;
    }
}
