package com.studybridge.api.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;
import java.util.List;

public class GroupStudySocketDTO {

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    public static class ChatPayload {
        private String senderId;
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

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class QuizSessionPayload {
        private Long sessionId;
        private Long quizId;
        private String quizTitle;
        private String phase;
        private Long questionId;
        private String questionText;
        private List<String> options;
        private Integer currentIndex;
        private Integer totalQuestions;
        private Integer timeLimitSeconds;
        private Integer remainingSeconds;
        private Integer correctAnswer;
        private Integer pointsAwarded;
        private Integer submittedCount;
        private Boolean userSubmitted;
        private Integer userSubmittedAnswer;
        private Integer userPointsAwarded;
        private Boolean userAnswerCorrect;
        private LocalDateTime questionStartedAt;
        private LocalDateTime questionEndsAt;
        private LocalDateTime revealAt;
        private LocalDateTime nextQuestionAt;
        private LocalDateTime completedAt;
        private List<ScoreboardEntry> scoreboard;
        private String message;
        // 품질 게이트(GET /api/groups/{groupId}/quiz/session 스냅샷 전용). 게이트 OFF·승인 퀴즈면 null → JSON 미출력(기존 payload 와 동일).
        // true = 미검증 저장 퀴즈라 AI 생성 필드(퀴즈 제목·문항·보기)를 고정 문구로 가렸다(정답 번호·점수·제출 기록은 유지).
        @com.fasterxml.jackson.annotation.JsonInclude(com.fasterxml.jackson.annotation.JsonInclude.Include.NON_NULL)
        private Boolean qualityRedacted;
    }

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class QuizTimerPayload {
        private Long sessionId;
        private Long questionId;
        private Integer currentIndex;
        private Integer remainingSeconds;
        private LocalDateTime questionEndsAt;
    }

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class QuizSubmissionAckPayload {
        private Long sessionId;
        private Long questionId;
        private Long userId;
        private Boolean accepted;
        private Boolean duplicate;
        private LocalDateTime submittedAt;
        private String message;
    }

    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class QuizErrorPayload {
        private Long quizId;
        private Long userId;
        private String message;
        private LocalDateTime occurredAt;
    }
}
