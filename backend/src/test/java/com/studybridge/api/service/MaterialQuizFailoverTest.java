package com.studybridge.api.service;

import com.studybridge.api.ai.AiFailoverExecutor;
import com.studybridge.api.ai.AiUpstream;
import com.studybridge.api.ai.AiUpstreams;
import com.studybridge.api.dto.AiMaterialQuizDTO;
import com.studybridge.api.dto.QuizDTO;
import com.studybridge.api.entity.Material;
import com.studybridge.api.entity.MaterialQuiz;
import com.studybridge.api.repository.MaterialFeedbackRepository;
import com.studybridge.api.repository.MaterialMemoRepository;
import com.studybridge.api.repository.MaterialQuestionRepository;
import com.studybridge.api.repository.MaterialQuizRepository;
import com.studybridge.api.repository.MaterialRepository;
import com.studybridge.api.repository.MaterialSummaryRepository;
import com.studybridge.api.repository.RoadmapRepository;
import com.studybridge.api.repository.RoadmapTaskRepository;
import com.studybridge.api.service.support.FailoverStubServer;
import com.studybridge.api.util.AiMaterialQuizContract;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentMatchers;
import org.mockito.Mockito;
import org.springframework.web.reactive.function.client.WebClient;

import java.io.IOException;
import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;

/**
 * Material Quiz(/api/ai/quiz) PRIMARY → SECONDARY failover (Q1~Q6). AiIntegrationService.generateQuiz 를 실제 TCP 스텁으로 검증.
 */
class MaterialQuizFailoverTest {

    private static final long USER = 55L;
    private static final long MATERIAL = 345L;

    private static final String SUCCESS_BODY = "{\"success\":true,\"schemaVersion\":\"quiz.v2\",\"quizId\":\"q-1\",\"status\":\"OK\",\"requestedCount\":1,\"generatedCount\":1,"
            + "\"difficultyApplied\":\"normal\",\"quizzes\":[{\"questionId\":\"q1\",\"question\":\"JDBC 는?\",\"questionType\":\"multiple_choice\",\"answerType\":\"SINGLE_CHOICE\","
            + "\"options\":[\"A안\",\"B안\",\"C안\",\"D안\"],\"optionIds\":[\"A\",\"B\",\"C\",\"D\"],\"correctAnswer\":0,\"answer\":0,\"answerIndex\":0,\"correctOptionIds\":[\"A\"],\"explanation\":\"e\"}],"
            + "\"metadata\":{\"provider\":\"ollama\"}}";
    private static final String BROKEN_CONTRACT_BODY = SUCCESS_BODY.replace("\"correctAnswer\":0,\"answer\":0,\"answerIndex\":0", "\"correctAnswer\":0,\"answer\":2,\"answerIndex\":0");

    private static String fail(String code, boolean retryable) {
        return "{\"success\":false,\"errorCode\":\"" + code + "\",\"message\":\"m\",\"retryable\":" + retryable + ",\"schemaVersion\":\"quiz.v2\",\"status\":\"FAILED\",\"quizzes\":[]}";
    }

    private FailoverStubServer primary;
    private FailoverStubServer secondary;
    private MaterialQuizRepository quizRepository;

    @BeforeEach
    void up() throws IOException {
        primary = new FailoverStubServer("/api/ai/quiz");
        secondary = new FailoverStubServer("/api/ai/quiz");
        secondary.body = SUCCESS_BODY;
    }

    @AfterEach
    void down() {
        primary.close();
        secondary.close();
    }

    private AiIntegrationService service(WebClient p, WebClient s) {
        MaterialRepository materials = mock(MaterialRepository.class);
        Material material = Material.builder().materialId(MATERIAL).userId(USER).title("JDBC 강의")
                .extractedText("JDBC 는 자바 데이터베이스 연결 API 이다. ".repeat(20)).keywords("JDBC,DriverManager").build();
        Mockito.when(materials.findById(MATERIAL)).thenReturn(Optional.of(material));
        MaterialSummaryRepository summaries = mock(MaterialSummaryRepository.class);
        Mockito.when(summaries.findByMaterial_MaterialId(MATERIAL)).thenReturn(Optional.empty());
        quizRepository = mock(MaterialQuizRepository.class);
        Mockito.when(quizRepository.save(ArgumentMatchers.any(MaterialQuiz.class))).thenAnswer(inv -> {
            MaterialQuiz q = inv.getArgument(0);
            return MaterialQuiz.builder().quizId(77L).material(q.getMaterial()).difficulty(q.getDifficulty())
                    .questionCount(q.getQuestionCount()).pageRange(q.getPageRange()).quizData(q.getQuizData()).build();
        });
        AiUpstreams ups = new AiUpstreams(List.of(new AiUpstream("primary", primary.baseUrl(), p), new AiUpstream("secondary", secondary.baseUrl(), s)));
        return new AiIntegrationService(materials, summaries, mock(MaterialFeedbackRepository.class), quizRepository,
                mock(MaterialMemoRepository.class), mock(MaterialQuestionRepository.class), mock(RoadmapRepository.class),
                mock(RoadmapTaskRepository.class), p, mock(IntentRouterService.class), mock(LearningLoopService.class),
                mock(MaterialQuizService.class), new AiFailoverExecutor(ups));
    }

    private static QuizDTO.Request req() {
        return new QuizDTO.Request("보통", 5, null);
    }

    @Test
    void q1_primary_success_secondary_not_called() {
        primary.body = SUCCESS_BODY;
        QuizDTO.Response res = service(primary.client(5), secondary.client(5)).generateQuiz(USER, MATERIAL, req());
        assertTrue(Boolean.TRUE.equals(res.getSuccess()), String.valueOf(res.getErrorCode()));
        assertEquals(1, res.getQuestions().size());
        assertEquals(1, primary.hits.get());
        assertEquals(0, secondary.hits.get());
    }

    @Test
    void q2_primary_network_error_secondary_success() throws IOException {
        QuizDTO.Response res = service(FailoverStubServer.refusedClient(), secondary.client(5)).generateQuiz(USER, MATERIAL, req());
        assertTrue(Boolean.TRUE.equals(res.getSuccess()), String.valueOf(res.getErrorCode()));
        assertEquals(77L, res.getQuizId());
        assertEquals(1, secondary.hits.get());
        Mockito.verify(quizRepository).save(ArgumentMatchers.any(MaterialQuiz.class));
    }

    @Test
    void q2b_primary_500_and_404_secondary_success() {
        primary.status = 500;
        primary.body = "{\"detail\":\"Internal Server Error\"}";
        QuizDTO.Response res = service(primary.client(5), secondary.client(5)).generateQuiz(USER, MATERIAL, req());
        assertTrue(Boolean.TRUE.equals(res.getSuccess()));
        assertEquals(1, secondary.hits.get());

        primary.status = 404;
        primary.body = "{\"detail\":\"Not Found\"}";
        res = service(primary.client(5), secondary.client(5)).generateQuiz(USER, MATERIAL, req());
        assertTrue(Boolean.TRUE.equals(res.getSuccess()));
        assertEquals(2, secondary.hits.get());
    }

    @Test
    void q3_domain_failure_pdf_text_insufficient_no_failover() {
        primary.body = fail("PDF_TEXT_INSUFFICIENT", true); // retryable=true 로 와도 domain 실패는 failover 금지
        QuizDTO.Response res = service(primary.client(5), secondary.client(5)).generateQuiz(USER, MATERIAL, req());
        assertFalse(Boolean.TRUE.equals(res.getSuccess()));
        assertEquals("PDF_TEXT_INSUFFICIENT", res.getErrorCode());
        assertEquals(AiMaterialQuizDTO.STATUS_FAILED, res.getStatus());
        assertEquals(0, secondary.hits.get());

        for (String code : List.of("PDF_OCR_REQUIRED", "SYLLABUS_WEEKLY_CONTENT_REQUIRED", "QUIZ_CONTRACT_INVALID")) {
            primary.body = fail(code, true);
            res = service(primary.client(5), secondary.client(5)).generateQuiz(USER, MATERIAL, req());
            assertEquals(code, res.getErrorCode());
        }
        assertEquals(0, secondary.hits.get());
        // retryable=false 인 일시 코드도 failover 하지 않는다
        primary.body = fail("AI_TIMEOUT", false);
        res = service(primary.client(5), secondary.client(5)).generateQuiz(USER, MATERIAL, req());
        assertEquals("AI_TIMEOUT", res.getErrorCode());
        assertEquals(0, secondary.hits.get());
    }

    @Test
    void q4_transient_retryable_ai_timeout_fails_over_to_secondary() {
        primary.body = fail("AI_TIMEOUT", true);
        QuizDTO.Response res = service(primary.client(5), secondary.client(5)).generateQuiz(USER, MATERIAL, req());
        assertTrue(Boolean.TRUE.equals(res.getSuccess()), String.valueOf(res.getErrorCode()));
        assertEquals(1, primary.hits.get());
        assertEquals(1, secondary.hits.get());

        primary.body = fail("AI_RESPONSE_PARSE_FAILED", true);
        res = service(primary.client(5), secondary.client(5)).generateQuiz(USER, MATERIAL, req());
        assertTrue(Boolean.TRUE.equals(res.getSuccess()));
        assertEquals(2, secondary.hits.get());
    }

    @Test
    void q5_secondary_response_passes_same_contract_validator() {
        primary.status = 502;
        secondary.body = BROKEN_CONTRACT_BODY; // answer != correctAnswer → Spring 검증이 거절해야 한다
        QuizDTO.Response res = service(primary.client(5), secondary.client(5)).generateQuiz(USER, MATERIAL, req());
        assertFalse(Boolean.TRUE.equals(res.getSuccess()));
        assertEquals("QUIZ_CONTRACT_INVALID", res.getErrorCode());
        assertEquals(1, secondary.hits.get());
        Mockito.verify(quizRepository, Mockito.never()).save(ArgumentMatchers.any());
        // 정상 secondary 본문은 통과
        assertNull(AiMaterialQuizContract.transientFailureCode(new AiMaterialQuizDTO.Response()));
    }

    @Test
    void q6_both_upstreams_fail_returns_existing_quiz_failure() throws IOException {
        // 전송 실패 × 2 → 기존 UNKNOWN_ERROR/AI_TIMEOUT 실패 응답(HTTP 예외 없음)
        QuizDTO.Response res = service(FailoverStubServer.refusedClient(), FailoverStubServer.refusedClient()).generateQuiz(USER, MATERIAL, req());
        assertFalse(Boolean.TRUE.equals(res.getSuccess()));
        assertEquals("UNKNOWN_ERROR", res.getErrorCode());
        assertTrue(Boolean.TRUE.equals(res.getRetryable()));

        // primary 일시 실패 + secondary 5xx → primary 의 구조화 실패(AI_TIMEOUT) 그대로 반환
        primary.body = fail("AI_TIMEOUT", true);
        secondary.status = 503;
        res = service(primary.client(5), secondary.client(5)).generateQuiz(USER, MATERIAL, req());
        assertEquals("AI_TIMEOUT", res.getErrorCode());
        assertEquals(1, secondary.hits.get());
        Mockito.verify(quizRepository, Mockito.never()).save(ArgumentMatchers.any());
    }

    @Test
    void transient_failure_code_policy() {
        AiMaterialQuizDTO.Response r = new AiMaterialQuizDTO.Response();
        r.setSuccess(false); r.setErrorCode("AI_TIMEOUT"); r.setRetryable(true);
        assertEquals("AI_TIMEOUT", AiMaterialQuizContract.transientFailureCode(r));
        r.setRetryable(false);
        assertNull(AiMaterialQuizContract.transientFailureCode(r));
        r.setRetryable(true); r.setErrorCode("PDF_TEXT_INSUFFICIENT");
        assertNull(AiMaterialQuizContract.transientFailureCode(r));
        r.setErrorCode("SOME_NEW_DOMAIN_CODE");
        assertNull(AiMaterialQuizContract.transientFailureCode(r), "알 수 없는 코드는 보수적으로 failover 하지 않는다");
        assertEquals("EMPTY_UPSTREAM_RESPONSE", AiMaterialQuizContract.transientFailureCode(null));
        AiMaterialQuizDTO.Response ok = new AiMaterialQuizDTO.Response();
        ok.setSuccess(true);
        assertNull(AiMaterialQuizContract.transientFailureCode(ok));
    }
}
