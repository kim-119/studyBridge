package com.studybridge.api.util;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.dto.AiMaterialQuizDTO;
import com.studybridge.api.dto.QuizDTO;
import com.studybridge.api.service.MaterialQuizService;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * AI07 quiz.v2 typed 계약(Q1~Q6): 역직렬화, success:false, PARTIAL, DEGRADED_FALLBACK 구조 판정, 정답 키 불일치 거절, 초기 payload 누출 0.
 */
class AiMaterialQuizContractTest {

    private static final ObjectMapper M = new ObjectMapper().findAndRegisterModules();

    private static final String SUCCESS_JSON = "{"
            + "\"success\":true,\"errorCode\":null,\"schemaVersion\":\"quiz.v2\",\"quizId\":\"quiz_abc\",\"status\":\"OK\","
            + "\"degraded\":false,\"degradedReason\":null,\"fallbackUsed\":false,\"fallbackQuestionCount\":0,\"partial\":false,"
            + "\"requestedCount\":2,\"generatedCount\":2,\"rejectedCount\":0,"
            + "\"answerKeyFields\":[\"correctAnswer\",\"answer\",\"answerIndex\",\"correctOptionIds\",\"explanation\",\"wrongExplanations\",\"sourceTrace\"],"
            + "\"quizData\":\"[...]\",\"warnings\":[],\"metadata\":{\"provider\":\"openai\",\"fallbackUsed\":false},"
            + "\"difficulty_applied\":\"hard\",\"source_trace\":{\"based_on\":\"pdf\"},"
            + "\"quizzes\":["
            + "{\"questionId\":\"q_1\",\"question\":\"JDBC 의 정의는?\",\"questionType\":\"multiple_choice\",\"answerType\":\"SINGLE_CHOICE\","
            + "\"options\":[\"A1\",\"B1\",\"C1\",\"D1\"],\"optionIds\":[\"A\",\"B\",\"C\",\"D\"],\"answer\":1,\"answerIndex\":1,\"correctAnswer\":1,\"correctOptionIds\":[\"B\"],"
            + "\"explanation\":\"secret-explanation\",\"wrongExplanations\":[\"w1\"],\"difficulty\":\"hard\",\"sourceTrace\":{\"page\":3},\"futureField\":true},"
            + "{\"questionId\":\"q_2\",\"question\":\"Connection 의 역할은?\",\"questionType\":\"multiple_choice\",\"answerType\":\"SINGLE_CHOICE\","
            + "\"options\":[\"A2\",\"B2\",\"C2\",\"D2\"],\"optionIds\":[\"A\",\"B\",\"C\",\"D\"],\"answer\":3,\"answerIndex\":3,\"correctAnswer\":3,\"correctOptionIds\":[\"D\"],"
            + "\"explanation\":\"e2\",\"wrongExplanations\":[],\"difficulty\":\"hard\",\"sourceTrace\":{}}"
            + "]}";

    private static AiMaterialQuizDTO.Question q(String id, int correct, String correctOptionId) {
        return AiMaterialQuizDTO.Question.builder().questionId(id).question("Q " + id).questionType("multiple_choice").answerType("SINGLE_CHOICE")
                .options(new ArrayList<>(List.of("a", "b", "c", "d"))).optionIds(new ArrayList<>(List.of("A", "B", "C", "D")))
                .answer(correct).answerIndex(correct).correctAnswer(correct)
                .correctOptionIds(new ArrayList<>(List.of(correctOptionId))).explanation("e").build();
    }

    @Test
    void q1_success_true_typed_deserialization_keeps_contract_fields() throws Exception {
        AiMaterialQuizDTO.Response r = M.readValue(SUCCESS_JSON, AiMaterialQuizDTO.Response.class);
        assertEquals(Boolean.TRUE, r.getSuccess());
        assertEquals("quiz.v2", r.getSchemaVersion());
        assertEquals("quiz_abc", r.getQuizId());
        assertEquals("OK", r.getStatus());
        assertEquals(2, r.getGeneratedCount());
        assertEquals(7, r.getAnswerKeyFields().size());
        assertEquals("hard", r.getDifficultyApplied());
        assertEquals("pdf", r.getSourceTrace().get("based_on"));
        AiMaterialQuizDTO.Question q1 = r.getQuizzes().get(0);
        assertEquals("q_1", q1.getQuestionId());
        assertEquals(List.of("A", "B", "C", "D"), q1.getOptionIds());
        assertEquals(1, q1.getCorrectAnswer());
        assertEquals(List.of("B"), q1.getCorrectOptionIds());
        assertEquals(List.of("w1"), q1.getWrongExplanations());
        assertEquals(3, q1.getSourceTrace().get("page"));
        assertNull(AiMaterialQuizContract.failureCode(r));
        assertFalse(AiMaterialQuizContract.isDegradedFallback(r));
        assertFalse(AiMaterialQuizContract.isPartial(r));
        assertEquals(2, AiMaterialQuizContract.validate(r.getQuizzes()).getAccepted().size());
    }

    @Test
    void q2_success_false_with_http_200_is_failure_not_quiz() throws Exception {
        AiMaterialQuizDTO.Response r = M.readValue("{\"success\":false,\"errorCode\":\"PDF_TEXT_INSUFFICIENT\",\"message\":\"m\",\"retryable\":false,\"status\":\"FAILED\","
                + "\"quizzes\":[{\"questionId\":\"q_1\",\"question\":\"x\",\"options\":[\"a\",\"b\",\"c\",\"d\"],\"optionIds\":[\"A\",\"B\",\"C\",\"D\"],\"correctAnswer\":0,\"correctOptionIds\":[\"A\"]}]}",
                AiMaterialQuizDTO.Response.class);
        assertEquals("PDF_TEXT_INSUFFICIENT", AiMaterialQuizContract.failureCode(r));
        // errorCode 없이 status=FAILED 만 와도 실패
        AiMaterialQuizDTO.Response r2 = AiMaterialQuizDTO.Response.builder().success(true).status("FAILED").build();
        assertEquals("QUIZ_CONTRACT_INVALID", AiMaterialQuizContract.failureCode(r2));
        for (String code : List.of("PDF_OCR_REQUIRED", "SYLLABUS_WEEKLY_CONTENT_REQUIRED", "AI_TIMEOUT", "AI_RESPONSE_PARSE_FAILED", "QUIZ_CONTRACT_INVALID")) {
            assertEquals(code, AiMaterialQuizContract.failureCode(AiMaterialQuizDTO.Response.builder().success(false).errorCode(code).build()));
        }
    }

    @Test
    void q3_partial_uses_generated_count_only() {
        AiMaterialQuizDTO.Response r = AiMaterialQuizDTO.Response.builder().success(true).status("PARTIAL").partial(true)
                .requestedCount(5).generatedCount(3).quizzes(new ArrayList<>(List.of(q("q_1", 0, "A"), q("q_2", 1, "B"), q("q_3", 2, "C")))).build();
        assertTrue(AiMaterialQuizContract.isPartial(r));
        assertEquals(3, AiMaterialQuizContract.validate(r.getQuizzes()).getAccepted().size());
        // status 없이 count 만으로도 PARTIAL
        assertTrue(AiMaterialQuizContract.isPartial(AiMaterialQuizDTO.Response.builder().requestedCount(5).generatedCount(4).build()));
        assertFalse(AiMaterialQuizContract.isPartial(AiMaterialQuizDTO.Response.builder().requestedCount(5).generatedCount(5).build()));
    }

    @Test
    void q4_degraded_fallback_is_structural_not_title_based() {
        assertTrue(AiMaterialQuizContract.isDegradedFallback(AiMaterialQuizDTO.Response.builder().status("DEGRADED_FALLBACK").build()));
        assertTrue(AiMaterialQuizContract.isDegradedFallback(AiMaterialQuizDTO.Response.builder().degraded(true).build()));
        assertTrue(AiMaterialQuizContract.isDegradedFallback(AiMaterialQuizDTO.Response.builder().fallbackUsed(true).build()));
        assertTrue(AiMaterialQuizContract.isDegradedFallback(AiMaterialQuizDTO.Response.builder().metadata(Map.of("fallbackUsed", true)).build()));
        assertFalse(AiMaterialQuizContract.isDegradedFallback(AiMaterialQuizDTO.Response.builder().status("OK").degraded(false).fallbackUsed(false).build()));
        // 제목/문항 문자열은 판정에 쓰이지 않는다
        AiMaterialQuizDTO.Response titled = AiMaterialQuizDTO.Response.builder().status("OK").degraded(false)
                .quizzes(new ArrayList<>(List.of(q("q_1", 0, "A")))).build();
        titled.getQuizzes().get(0).setQuestion("자료 기반 학습 퀴즈 (기본 안내형) 다음 중 효과적인 학습 방법으로 알려진 것은?");
        assertFalse(AiMaterialQuizContract.isDegradedFallback(titled));
    }

    @Test
    void q5_answer_key_inconsistency_rejected() {
        AiMaterialQuizDTO.Question mismatchIndex = q("q_1", 1, "B");
        mismatchIndex.setAnswerIndex(2);
        assertEquals("ANSWER_KEY_MISMATCH", AiMaterialQuizContract.reject(mismatchIndex));

        AiMaterialQuizDTO.Question mismatchAnswer = q("q_1", 1, "B");
        mismatchAnswer.setAnswer(0);
        assertEquals("ANSWER_KEY_MISMATCH", AiMaterialQuizContract.reject(mismatchAnswer));

        AiMaterialQuizDTO.Question mismatchOptionId = q("q_1", 1, "C");
        assertEquals("CORRECT_OPTION_IDS_MISMATCH", AiMaterialQuizContract.reject(mismatchOptionId));

        AiMaterialQuizDTO.Question range = q("q_1", 4, "A");
        assertEquals("CORRECT_ANSWER_RANGE", AiMaterialQuizContract.reject(range));

        AiMaterialQuizDTO.Question threeOptions = q("q_1", 1, "B");
        threeOptions.setOptions(new ArrayList<>(List.of("a", "b", "c")));
        assertEquals("OPTIONS_SIZE", AiMaterialQuizContract.reject(threeOptions));

        AiMaterialQuizDTO.Question badIds = q("q_1", 1, "B");
        badIds.setOptionIds(new ArrayList<>(List.of("A", "B", "B", "D")));
        assertEquals("OPTION_IDS_DUPLICATE", AiMaterialQuizContract.reject(badIds));

        AiMaterialQuizDTO.Question blankId = q("", 1, "B");
        assertEquals("QUESTION_ID_BLANK", AiMaterialQuizContract.reject(blankId));

        AiMaterialQuizDTO.Question noKey = q("q_1", 1, "B");
        noKey.setAnswer(null); noKey.setAnswerIndex(null); noKey.setCorrectAnswer(null); noKey.setCorrectOptionIds(new ArrayList<>());
        assertEquals("ANSWER_KEY_MISSING", AiMaterialQuizContract.reject(noKey));

        // 통과 문항: answer/answerIndex null 은 correctAnswer 로 정규화, correctOptionIds 누락은 보정
        AiMaterialQuizDTO.Question okPartialKeys = q("q_1", 2, "C");
        okPartialKeys.setAnswer(null); okPartialKeys.setAnswerIndex(null); okPartialKeys.setCorrectOptionIds(null);
        AiMaterialQuizContract.Result res = AiMaterialQuizContract.validate(new ArrayList<>(List.of(okPartialKeys, mismatchOptionId)));
        assertEquals(1, res.getAccepted().size());
        assertEquals(1, res.rejectedCount());
        assertEquals(2, res.getAccepted().get(0).getAnswer());
        assertEquals(List.of("C"), res.getAccepted().get(0).getCorrectOptionIds());
    }

    @Test
    void q6_public_payload_has_no_answer_key_fields_or_quiz_data() throws Exception {
        AiMaterialQuizDTO.Response r = M.readValue(SUCCESS_JSON, AiMaterialQuizDTO.Response.class);
        String internalJson = M.writeValueAsString(AiMaterialQuizContract.validate(r.getQuizzes()).getAccepted());
        List<QuizDTO.PublicQuestion> pub = MaterialQuizService.toPublicQuestions(72L, internalJson);
        assertEquals(2, pub.size());
        assertEquals("q_1", pub.get(0).getQuestionId(), "AI07 questionId 유지");
        assertEquals("B", pub.get(0).getOptions().get(1).getOptionId(), "AI07 optionIds 유지");
        assertEquals("SINGLE_CHOICE", pub.get(0).getAnswerType());
        QuizDTO.Response resp = QuizDTO.Response.builder().quizId(72L).materialId(1L).questions(pub).success(true)
                .status("OK").generatedCount(2).schemaVersion("quiz.v2").aiQuizId("quiz_abc").build();
        String json = M.writeValueAsString(resp);
        for (String leak : List.of("correctAnswer", "\"answer\"", "answerIndex", "correctOptionIds", "explanation", "wrongExplanations",
                "sourceTrace", "source_trace", "quizData", "secret-explanation", "\"quizzes\"")) {
            assertFalse(json.contains(leak), "initial payload leaks: " + leak + " in " + json);
        }
        assertTrue(json.contains("\"generatedCount\":2"));
    }
}
