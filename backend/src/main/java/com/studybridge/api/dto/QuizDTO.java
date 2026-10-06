package com.studybridge.api.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * 자료보관함 자료 퀴즈 DTO.
 *
 * <p>내부(정답 포함) / 공개(정답 없음) / 제출 / 결과를 분리한다.
 * <ul>
 *   <li>내부: {@link com.studybridge.api.util.MaterialQuizContent.InternalQuestion} — 서버에서만 다룬다.</li>
 *   <li>공개: {@link Response}/{@link PublicQuestion} — 브라우저 초기 payload. 정답 키·원문 quizData 를 싣지 않는다.</li>
 *   <li>제출: {@link SubmitRequest} — 답안(questionId/selectedOptionId)만 받는다. score/isCorrect 는 받지 않는다.</li>
 *   <li>결과: {@link ResultResponse} — 서버 채점 결과(점수 + 문항별 정답/해설, 제출 이후에만).</li>
 * </ul>
 */
public class QuizDTO {

    @Getter
    @NoArgsConstructor
    @AllArgsConstructor
    public static class Request {
        private String difficulty; // 쉬움, 보통, 어려움
        private Integer questionCount; // 문항 수
        private String pageRange; // 전체 또는 특정 범위
    }

    /** 공개 보기(정답 표시 없음). */
    @Getter
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class PublicOption {
        private String optionId;   // o1, o2, ...
        private String text;
    }

    /** 공개 문항(정답 없음). index 는 0-based 저장 순서(오답노트 API 의 answers 키와 동일). */
    @Getter
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class PublicQuestion {
        private String questionId; // AI07 questionId(q_*) 또는 q{quizId}-{n}
        private Integer index;
        private String question;
        private String questionType; // multiple_choice
        private String answerType;   // SINGLE_CHOICE
        @Builder.Default
        private List<PublicOption> options = new ArrayList<>();
        private String difficulty;
        private Boolean gradable;  // false 면 정답 키 판독 불가(채점 분모 제외)
    }

    @Getter
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class Response {
        private Long quizId;
        private Long materialId;
        private String difficulty;
        private Integer questionCount;
        private Integer requestedCount;   // 사용자가 요청한 원본 문항 수 (보정 전)
        private Integer appliedCount;      // 5~20 보정 후 실제 적용 문항 수
        private String pageRange;
        @Builder.Default
        private List<PublicQuestion> questions = new ArrayList<>();
        private LocalDateTime createdAt;
        // 난이도 검증 (G/H): 요청/적용 난이도 + 정책 + 검증 결과 (ai07이 제공하면 전파, 없으면 null)
        private String difficultyRequested;   // easy | normal | hard
        private String difficultyApplied;     // ai07이 실제 적용한 난이도
        private String difficultyPolicy;      // 난이도 정책 설명
        private Map<String, Object> difficultyValidation; // { passed, reason }
        // sourceTrace(top-level/문항) 는 AI07 answerKeyFields 에 속하므로 공개 DTO 에 싣지 않는다.
        // AI07 quiz.v2 구조화 상태(additive). status: OK | PARTIAL | DEGRADED_FALLBACK | FAILED
        private String schemaVersion;
        private String aiQuizId;          // AI07 quizId(quiz_*) — 내부 quizId(Long) 와 별개
        private String status;
        private Boolean partial;
        private Integer generatedCount;   // 계약 검증 통과 문항 수(= 브라우저에 보이는 문항 수)
        private Integer aiRequestedCount;
        private Integer rejectedCount;
        private Boolean degraded;
        private String degradedReason;
        // AI 상태 전파 필드 (nullable, 하위호환 additive)
        private Boolean success;
        private String errorCode;
        private String message;
        private Boolean retryable;
        private Map<String, Object> textStatus;
        private List<String> warnings;
        private Map<String, Object> metadata;
        private String provider;
        private String model;
        private Long elapsedMs;
        private Boolean usedFallback;
        private Boolean cacheHit;
        // 이 사용자의 최근 서버 채점 결과(있으면). 목록 재진입 시 점수 표시용.
        private ResultResponse lastResult;
    }

    /** 제출: 답안만. 클라이언트가 보내는 score/correctCount/isCorrect 류 필드는 존재하지 않는다. */
    @Getter
    @Setter
    @NoArgsConstructor
    @AllArgsConstructor
    public static class SubmitRequest {
        private List<SubmittedAnswer> answers = new ArrayList<>();
    }

    @Getter
    @Setter
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class SubmittedAnswer {
        private String questionId;
        /** 계약: selectedOptionIds(SINGLE_CHOICE 는 1개). 비어 있으면 미응답. */
        private List<String> selectedOptionIds;
        /** 레거시 단일 값(있으면 selectedOptionIds 로 승격). */
        private String selectedOptionId;

        public List<String> effectiveOptionIds() {
            List<String> out = new ArrayList<>();
            if (selectedOptionIds != null) for (String s : selectedOptionIds) if (s != null && !s.isBlank()) out.add(s.trim());
            if (out.isEmpty() && selectedOptionId != null && !selectedOptionId.isBlank()) out.add(selectedOptionId.trim());
            return out;
        }
    }

    /** 서버 채점 결과. */
    @Getter
    @Setter
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class ResultResponse {
        private Long quizId;
        private Long materialId;
        private Long userId;
        private Integer score;           // round(correct / total * 100), total=0 → 0
        private Integer correctCount;
        private Integer totalQuestions;  // 채점 가능 문항 수
        private Integer answeredCount;
        private Integer attempt;         // 누적 제출 횟수(재응시 허용, 최신이 덮어씀)
        private LocalDateTime submittedAt;
        private Boolean persisted;       // Redis 저장 성공 여부(장애 시 false, 점수는 그대로 반환)
        @Builder.Default
        private List<QuestionResult> results = new ArrayList<>();
    }

    @Getter
    @Setter
    @Builder
    @NoArgsConstructor
    @AllArgsConstructor
    public static class QuestionResult {
        private String questionId;
        private Integer index;
        private Boolean answered;
        private Boolean correct;
        private Boolean gradable;
        @Builder.Default
        private List<String> selectedOptionIds = new ArrayList<>();
        @Builder.Default
        private List<String> correctOptionIds = new ArrayList<>(); // 제출 이후에만 공개
        private String explanation;                                 // 제출 이후에만 공개
    }
}
