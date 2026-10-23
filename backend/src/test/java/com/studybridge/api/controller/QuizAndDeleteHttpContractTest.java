package com.studybridge.api.controller;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.studybridge.api.dto.MindmapSemanticGraphDTO;
import com.studybridge.api.dto.QuizDTO;
import com.studybridge.api.entity.User;
import com.studybridge.api.exception.GlobalExceptionHandler;
import com.studybridge.api.security.domain.CustomUserDetails;
import com.studybridge.api.service.AiIntegrationService;
import com.studybridge.api.service.GroupStudyMaterialService;
import com.studybridge.api.service.MaterialQuizService;
import com.studybridge.api.service.MaterialService;
import com.studybridge.api.service.MindmapSemanticGraphService;
import com.studybridge.api.service.StudyNoteAnalysisService;
import java.util.List;
import java.util.NoSuchElementException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.core.MethodParameter;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.bind.support.WebDataBinderFactory;
import org.springframework.web.context.request.NativeWebRequest;
import org.springframework.web.method.support.HandlerMethodArgumentResolver;
import org.springframework.web.method.support.ModelAndViewContainer;

/**
 * HTTP 계약(4.5): 새 삭제/채점/마인드맵 엔드포인트가 GlobalExceptionHandler 를 통해 401 외 403/404/409/400 을 의미대로 낸다.
 *  · 초기 퀴즈 payload(GET /quiz) 에 정답 키가 없다(Q3/G6).
 *  · 마인드맵 FAILED 는 HTTP 200 + status=FAILED 로 내려간다(브라우저가 명시 표시).
 */
class QuizAndDeleteHttpContractTest {

    private static final long USER = 55L;

    private MockMvc mvc;
    private GroupStudyMaterialService groupService;
    private MaterialQuizService quizService;
    private AiIntegrationService aiService;
    private MindmapSemanticGraphService mindmapService;

    /** @AuthenticationPrincipal CustomUserDetails → 고정 사용자(55). */
    static final class PrincipalResolver implements HandlerMethodArgumentResolver {
        @Override
        public boolean supportsParameter(MethodParameter p) { return p.getParameterType().equals(CustomUserDetails.class); }
        @Override
        public Object resolveArgument(MethodParameter p, ModelAndViewContainer m, NativeWebRequest r, WebDataBinderFactory f) {
            return new CustomUserDetails(User.builder().id(USER).email("u@x").password("p").build());
        }
    }

    @BeforeEach
    void setUp() {
        groupService = Mockito.mock(GroupStudyMaterialService.class);
        quizService = Mockito.mock(MaterialQuizService.class);
        aiService = Mockito.mock(AiIntegrationService.class);
        mindmapService = Mockito.mock(MindmapSemanticGraphService.class);
        mvc = MockMvcBuilders.standaloneSetup(
                        new GroupStudyMaterialController(groupService),
                        new MaterialController(Mockito.mock(MaterialService.class), aiService,
                                Mockito.mock(StudyNoteAnalysisService.class), quizService),
                        new MindmapSemanticGraphController(mindmapService))
                .setControllerAdvice(new GlobalExceptionHandler())
                .setCustomArgumentResolvers(new PrincipalResolver())
                .build();
    }

    @Test
    void d2_member_delete_group_material_is_403_json() throws Exception {
        Mockito.doThrow(new SecurityException("방장만 삭제할 수 있습니다.")).when(groupService).deleteMaterial(USER, 10L, 100L);
        mvc.perform(delete("/api/groups/10/materials/100"))
                .andExpect(status().isForbidden())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$.status").value(403))
                .andExpect(jsonPath("$.message").value(org.hamcrest.Matchers.containsString("방장")));
    }

    @Test
    void d5_cross_group_id_is_404_and_d1_owner_is_204() throws Exception {
        Mockito.doThrow(new NoSuchElementException("이 그룹스터디에 속한 자료가 아닙니다.")).when(groupService).deleteMaterial(USER, 10L, 999L);
        mvc.perform(delete("/api/groups/10/materials/999")).andExpect(status().isNotFound());
        mvc.perform(delete("/api/groups/10/materials/100")).andExpect(status().isNoContent());
        Mockito.verify(groupService).deleteMaterial(USER, 10L, 100L);
    }

    @Test
    void d4_member_quiz_delete_403_and_active_session_409() throws Exception {
        Mockito.doThrow(new SecurityException("방장만 삭제할 수 있습니다.")).when(groupService).deleteQuiz(USER, 10L, 500L);
        mvc.perform(delete("/api/groups/10/quizzes/500")).andExpect(status().isForbidden());
        Mockito.doThrow(new IllegalStateException("진행 중인 퀴즈 세션이 있어 삭제할 수 없습니다.")).when(groupService).deleteQuiz(USER, 10L, 501L);
        mvc.perform(delete("/api/groups/10/quizzes/501"))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.status").value(409));
        mvc.perform(delete("/api/groups/10/quizzes/502")).andExpect(status().isNoContent());
    }

    @Test
    void q3_initial_quiz_payload_has_no_answer_key() throws Exception {
        List<QuizDTO.PublicQuestion> pub = MaterialQuizService.toPublicQuestions(72L,
                "[{\"question\":\"Q1\",\"options\":[\"A\",\"B\"],\"answerIndex\":1,\"explanation\":\"secret\"}]");
        Mockito.when(aiService.getQuizzes(USER, 900L)).thenReturn(List.of(
                QuizDTO.Response.builder().quizId(72L).materialId(900L).questions(pub).success(true).build()));
        mvc.perform(get("/api/materials/900/quiz"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].questions[0].questionId").value("q72-1"))
                .andExpect(jsonPath("$[0].questions[0].options[1].optionId").value("o2"))
                .andExpect(content().string(org.hamcrest.Matchers.not(org.hamcrest.Matchers.containsString("answerIndex"))))
                .andExpect(content().string(org.hamcrest.Matchers.not(org.hamcrest.Matchers.containsString("correctOptionId"))))
                .andExpect(content().string(org.hamcrest.Matchers.not(org.hamcrest.Matchers.containsString("secret"))))
                .andExpect(content().string(org.hamcrest.Matchers.not(org.hamcrest.Matchers.containsString("quizData"))));
    }

    @Test
    void q2_q4_submit_contract_ignores_client_score_and_rejects_bad_question_400() throws Exception {
        Mockito.when(quizService.submit(eq(USER), eq(900L), eq(72L), any())).thenAnswer(inv -> {
            QuizDTO.SubmitRequest req = inv.getArgument(3);
            // 클라이언트가 score/isCorrect 를 끼워 넣어도 DTO 에 필드가 없어 무시된다(바인딩 오류 없이 답안만 도착).
            if (req.getAnswers().size() != 1 || !"q72-1".equals(req.getAnswers().get(0).getQuestionId())) throw new AssertionError();
            return QuizDTO.ResultResponse.builder().quizId(72L).score(0).correctCount(0).totalQuestions(1).answeredCount(1).attempt(1).persisted(true).build();
        });
        mvc.perform(post("/api/materials/900/quiz/72/submit").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"score\":100,\"correctCount\":5,\"answers\":[{\"questionId\":\"q72-1\",\"selectedOptionIds\":[\"o1\"],\"isCorrect\":true}]}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.score").value(0));

        Mockito.when(quizService.submit(eq(USER), eq(900L), eq(73L), any()))
                .thenThrow(new IllegalArgumentException("이 퀴즈에 속하지 않는 문항입니다: q72-1"));
        mvc.perform(post("/api/materials/900/quiz/73/submit").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"answers\":[{\"questionId\":\"q72-1\",\"selectedOptionIds\":[\"o1\"]}]}"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.status").value(400));
    }

    @Test
    void score_404_when_none_and_quiz_delete_owner_204_other_403() throws Exception {
        Mockito.when(quizService.latestResult(USER, 900L, 72L)).thenThrow(new NoSuchElementException("아직 제출한 답안이 없습니다."));
        mvc.perform(get("/api/materials/900/quiz/72/score")).andExpect(status().isNotFound());
        mvc.perform(delete("/api/materials/900/quiz/72")).andExpect(status().isNoContent());
        Mockito.doThrow(new SecurityException("해당 퀴즈에 대한 권한이 없습니다.")).when(quizService).delete(USER, 901L, 73L);
        mvc.perform(delete("/api/materials/901/quiz/73")).andExpect(status().isForbidden());
    }

    @Test
    void mindmap_failed_uses_real_http_status_and_foreign_room_is_403() throws Exception {
        // AI07 422 NO_VALID_CONCEPTS → Spring 422 + upstreamCode
        Mockito.when(mindmapService.semanticGraph(eq(USER), any())).thenThrow(
                com.studybridge.api.exception.AiUpstreamException.contract(422, "NO_VALID_CONCEPTS", "AI 가 이 답변에서 유효한 개념을 찾지 못했습니다.", null));
        mvc.perform(post("/api/mindmap/semantic-graph").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"roomId\":231,\"question\":\"JDBC가 뭐야?\",\"answers\":[{\"messageId\":1,\"content\":\"JDBC는 ...\"}]}"))
                .andExpect(status().isUnprocessableEntity())
                .andExpect(jsonPath("$.status").value(422))
                .andExpect(jsonPath("$.upstreamCode").value("NO_VALID_CONCEPTS"));

        // AI07 504 TIMEOUT → 504
        Mockito.when(mindmapService.semanticGraph(eq(USER), any())).thenThrow(new com.studybridge.api.exception.AiUpstreamException(
                org.springframework.http.HttpStatus.GATEWAY_TIMEOUT, "AI_UPSTREAM_TIMEOUT", "timeout", null, true, 504, "TIMEOUT"));
        mvc.perform(post("/api/mindmap/semantic-graph").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"roomId\":231,\"question\":\"q\",\"answers\":[{\"content\":\"a\"}]}"))
                .andExpect(status().isGatewayTimeout())
                .andExpect(jsonPath("$.code").value("AI_UPSTREAM_TIMEOUT"))
                .andExpect(jsonPath("$.upstreamCode").value("TIMEOUT"));

        // 200 OK/DEGRADED 는 200 본문
        Mockito.when(mindmapService.semanticGraph(eq(USER), any())).thenReturn(MindmapSemanticGraphDTO.Response.builder()
                .status("DEGRADED").degraded(true).degradedReason("LLM_TIMEOUT_DETERMINISTIC_FALLBACK").build());
        mvc.perform(post("/api/mindmap/semantic-graph").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"roomId\":231,\"question\":\"q\",\"answers\":[{\"content\":\"a\"}]}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("DEGRADED"))
                .andExpect(jsonPath("$.degradedReason").value("LLM_TIMEOUT_DETERMINISTIC_FALLBACK"));

        Mockito.when(mindmapService.semanticGraph(eq(USER), any())).thenThrow(new SecurityException("해당 채팅방에 접근할 권한이 없습니다."));
        mvc.perform(post("/api/mindmap/semantic-graph").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"roomId\":999,\"question\":\"q\",\"answers\":[]}"))
                .andExpect(status().isForbidden());
        Mockito.verify(mindmapService, Mockito.times(4)).semanticGraph(eq(USER), any());
        Mockito.verifyNoMoreInteractions(mindmapService);
        Mockito.verify(groupService, Mockito.never()).deleteQuiz(anyLong(), anyLong(), anyLong());
    }
}
