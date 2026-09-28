package com.studybridge.api.util;

import com.studybridge.api.dto.AiMaterialQuizDTO;

import java.util.ArrayList;
import java.util.List;

/**
 * AI07 quiz.v2 응답의 Spring 측 방어 검증(외부 service boundary).
 * <pre>
 *   questionId not blank / question not blank
 *   options size == 4 / optionIds size == 4
 *   correctAnswer in 0..3
 *   answer == answerIndex == correctAnswer (null 인 필드는 correctAnswer 로 보정, 값이 있으면 일치해야 함)
 *   correctOptionIds == [optionIds[correctAnswer]]
 * </pre>
 * 불일치 문항은 거절(브라우저에 깨진 퀴즈를 보내지 않음). success=false 응답은 문항 검증 이전에 실패로 처리한다.
 */
public final class AiMaterialQuizContract {

    public static final int OPTION_COUNT = 4;

    private AiMaterialQuizContract() {}

    public static final class Result {
        private final List<AiMaterialQuizDTO.Question> accepted = new ArrayList<>();
        private final List<String> rejectedReasons = new ArrayList<>();

        public List<AiMaterialQuizDTO.Question> getAccepted() { return accepted; }
        public List<String> getRejectedReasons() { return rejectedReasons; }
        public int rejectedCount() { return rejectedReasons.size(); }
    }

    /** 구조화 상태 판정. success=false 또는 status=FAILED 면 실패 사유(errorCode) 반환, 아니면 null. */
    public static String failureCode(AiMaterialQuizDTO.Response r) {
        if (r == null) return "AI_RESPONSE_PARSE_FAILED";
        if (Boolean.FALSE.equals(r.getSuccess())) return r.getErrorCode() != null ? r.getErrorCode() : "UNKNOWN_ERROR";
        if (r.getStatus() != null && AiMaterialQuizDTO.STATUS_FAILED.equalsIgnoreCase(r.getStatus().trim())) {
            return r.getErrorCode() != null ? r.getErrorCode() : "QUIZ_CONTRACT_INVALID";
        }
        return null;
    }

    /** DEGRADED_FALLBACK 은 구조적으로만 판정한다(status/degraded/fallbackUsed/metadata.fallbackUsed). 제목 문자열 비교 없음. */
    public static boolean isDegradedFallback(AiMaterialQuizDTO.Response r) {
        if (r == null) return false;
        if (r.getStatus() != null && AiMaterialQuizDTO.STATUS_DEGRADED_FALLBACK.equalsIgnoreCase(r.getStatus().trim())) return true;
        if (Boolean.TRUE.equals(r.getDegraded())) return true;
        if (Boolean.TRUE.equals(r.getFallbackUsed())) return true;
        Object meta = r.getMetadata() == null ? null : r.getMetadata().get("fallbackUsed");
        return Boolean.TRUE.equals(meta) || "true".equalsIgnoreCase(String.valueOf(meta));
    }

    public static boolean isPartial(AiMaterialQuizDTO.Response r) {
        if (r == null) return false;
        if (Boolean.TRUE.equals(r.getPartial())) return true;
        if (r.getStatus() != null && AiMaterialQuizDTO.STATUS_PARTIAL.equalsIgnoreCase(r.getStatus().trim())) return true;
        return r.getRequestedCount() != null && r.getGeneratedCount() != null && r.getGeneratedCount() < r.getRequestedCount();
    }

    /** 문항별 검증. 통과 문항은 answer/answerIndex 가 correctAnswer 로 정규화되어 반환된다. */
    public static Result validate(List<AiMaterialQuizDTO.Question> questions) {
        Result out = new Result();
        if (questions == null) return out;
        int idx = 0;
        for (AiMaterialQuizDTO.Question q : questions) {
            idx++;
            String reason = reject(q);
            if (reason != null) {
                out.rejectedReasons.add("#" + idx + ":" + reason);
                continue;
            }
            q.setAnswer(q.getCorrectAnswer());
            q.setAnswerIndex(q.getCorrectAnswer());
            out.accepted.add(q);
        }
        return out;
    }

    /** null = 통과, 아니면 거절 사유 코드. */
    public static String reject(AiMaterialQuizDTO.Question q) {
        if (q == null) return "NULL_QUESTION";
        if (isBlank(q.getQuestionId())) return "QUESTION_ID_BLANK";
        if (isBlank(q.getQuestion())) return "QUESTION_BLANK";
        if (q.getOptions() == null || q.getOptions().size() != OPTION_COUNT) return "OPTIONS_SIZE";
        for (String o : q.getOptions()) if (isBlank(o)) return "OPTION_BLANK";
        if (q.getOptionIds() == null || q.getOptionIds().size() != OPTION_COUNT) return "OPTION_IDS_SIZE";
        for (String o : q.getOptionIds()) if (isBlank(o)) return "OPTION_ID_BLANK";
        if (q.getOptionIds().stream().distinct().count() != OPTION_COUNT) return "OPTION_IDS_DUPLICATE";

        Integer correct = q.getCorrectAnswer();
        if (correct == null) correct = q.getAnswerIndex();
        if (correct == null) correct = q.getAnswer();
        if (correct == null) return "ANSWER_KEY_MISSING";
        if (correct < 0 || correct >= OPTION_COUNT) return "CORRECT_ANSWER_RANGE";
        if (q.getCorrectAnswer() != null && !q.getCorrectAnswer().equals(correct)) return "ANSWER_KEY_MISMATCH";
        if (q.getAnswerIndex() != null && !q.getAnswerIndex().equals(correct)) return "ANSWER_KEY_MISMATCH";
        if (q.getAnswer() != null && !q.getAnswer().equals(correct)) return "ANSWER_KEY_MISMATCH";
        q.setCorrectAnswer(correct);

        String expected = q.getOptionIds().get(correct);
        if (q.getCorrectOptionIds() == null || q.getCorrectOptionIds().isEmpty()) {
            // 계약상 반드시 있어야 하지만, 없으면 optionIds 로 채운다(단일 정답).
            List<String> ids = new ArrayList<>();
            ids.add(expected);
            q.setCorrectOptionIds(ids);
        } else if (q.getCorrectOptionIds().size() != 1 || !expected.equals(q.getCorrectOptionIds().get(0))) {
            return "CORRECT_OPTION_IDS_MISMATCH";
        }
        return null;
    }

    private static boolean isBlank(String s) { return s == null || s.isBlank(); }
}
