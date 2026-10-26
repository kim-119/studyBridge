package com.studybridge.api.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.studybridge.api.ai.AiFailoverExecutor;
import com.studybridge.api.ai.AiUpstream;
import com.studybridge.api.ai.AiUpstreams;
import com.studybridge.api.dto.GroupStudyQuizDTO;
import com.studybridge.api.repository.GroupStudyMaterialRepository;
import com.studybridge.api.repository.GroupStudyMemberRepository;
import com.studybridge.api.repository.GroupStudyQuizQuestionRepository;
import com.studybridge.api.repository.GroupStudyQuizRepository;
import com.studybridge.api.repository.GroupStudyQuizSessionAnswerRepository;
import com.studybridge.api.repository.GroupStudyQuizSessionRepository;
import com.studybridge.api.repository.GroupStudyRepository;
import com.studybridge.api.repository.UserRepository;
import com.studybridge.api.service.support.FailoverStubServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.web.reactive.function.client.WebClient;

import java.io.IOException;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.mockito.Mockito.mock;

/** Group Study Quiz(/api/ai/quiz/generate) PRIMARY → SECONDARY failover (G1~G3). */
class GroupStudyQuizFailoverTest {

    private static final String OK = "{\"success\":true,\"schemaVersion\":\"group-quiz.v2\",\"status\":\"OK\",\"quizTitle\":\"JDBC 퀴즈\","
            + "\"questions\":[{\"questionId\":\"g1\",\"question\":\"JDBC 는?\",\"options\":[\"a\",\"b\",\"c\",\"d\"],\"optionIds\":[\"A\",\"B\",\"C\",\"D\"],\"correctAnswer\":1,\"correctOptionIds\":[\"B\"]}]}";

    private FailoverStubServer primary;
    private FailoverStubServer secondary;

    @BeforeEach
    void up() throws IOException {
        primary = new FailoverStubServer("/api/ai/quiz/generate");
        secondary = new FailoverStubServer("/api/ai/quiz/generate");
        secondary.body = OK;
    }

    @AfterEach
    void down() {
        primary.close();
        secondary.close();
    }

    private GroupStudyMaterialService service(WebClient p, WebClient s) {
        AiUpstreams ups = new AiUpstreams(List.of(new AiUpstream("primary", primary.baseUrl(), p), new AiUpstream("secondary", secondary.baseUrl(), s)));
        return new GroupStudyMaterialService(mock(GroupStudyMaterialRepository.class), mock(GroupStudyRepository.class),
                mock(GroupStudyMemberRepository.class), mock(GroupStudyQuizRepository.class), mock(GroupStudyQuizQuestionRepository.class),
                mock(GroupStudyQuizSessionRepository.class), mock(GroupStudyQuizSessionAnswerRepository.class), mock(UserRepository.class),
                mock(S3Service.class), new AiFailoverExecutor(ups), new ObjectMapper());
    }

    private static GroupStudyQuizDTO.AIQuizRequest payload() {
        return GroupStudyQuizDTO.AIQuizRequest.builder().materialId(1L).s3Key("group/a.pdf").fileName("a.pdf").numQuestions(5).build();
    }

    @Test
    void g1_primary_success_secondary_not_called() {
        primary.body = OK;
        GroupStudyQuizDTO.AIQuizResponse res = service(primary.client(5), secondary.client(5)).requestAiQuiz(payload(), 1L);
        assertNotNull(res);
        assertEquals("JDBC 퀴즈", res.getQuizTitle());
        assertNull(GroupStudyMaterialService.unusableAiQuizReason(res));
        assertEquals(1, primary.hits.get());
        assertEquals(0, secondary.hits.get());
    }

    @Test
    void g2_primary_network_failure_and_5xx_go_to_secondary() throws IOException {
        GroupStudyQuizDTO.AIQuizResponse res = service(FailoverStubServer.refusedClient(), secondary.client(5)).requestAiQuiz(payload(), 1L);
        assertNotNull(res);
        assertEquals(1, res.getQuestions().size());
        assertEquals(1, secondary.hits.get());

        primary.status = 500;
        primary.body = "{\"detail\":\"boom\"}";
        res = service(primary.client(5), secondary.client(5)).requestAiQuiz(payload(), 1L);
        assertNotNull(res);
        assertEquals(2, secondary.hits.get());
    }

    @Test
    void g2b_primary_400_validation_error_no_failover() {
        primary.status = 400;
        primary.body = "{\"detail\":\"s3Key required\"}";
        GroupStudyQuizDTO.AIQuizResponse res = service(primary.client(5), secondary.client(5)).requestAiQuiz(payload(), 1L);
        assertNull(res, "기존 계약: 실패는 null → 퀴즈 미저장");
        assertEquals(0, secondary.hits.get());
    }

    @Test
    void g3_both_fail_returns_null_like_before() throws IOException {
        GroupStudyQuizDTO.AIQuizResponse res = service(FailoverStubServer.refusedClient(), FailoverStubServer.refusedClient()).requestAiQuiz(payload(), 1L);
        assertNull(res);
        primary.status = 503;
        secondary.status = 502;
        res = service(primary.client(5), secondary.client(5)).requestAiQuiz(payload(), 1L);
        assertNull(res);
        assertEquals(1, primary.hits.get());
        assertEquals(1, secondary.hits.get());
    }
}
