package com.studybridge.api.controller;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.studybridge.api.dto.QuizDTO;
import com.studybridge.api.entity.User;
import com.studybridge.api.exception.GlobalExceptionHandler;
import com.studybridge.api.exception.QuizAccessException;
import com.studybridge.api.security.domain.CustomUserDetails;
import com.studybridge.api.service.AiIntegrationService;
import com.studybridge.api.service.MaterialQuizScoreService.RankingUnavailableException;
import com.studybridge.api.service.MaterialQuizService;
import com.studybridge.api.service.MaterialService;
import com.studybridge.api.service.MaterialShareService;
import com.studybridge.api.service.StudyNoteAnalysisService;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.core.MethodParameter;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.bind.support.WebDataBinderFactory;
import org.springframework.web.context.request.NativeWebRequest;
import org.springframework.web.method.support.HandlerMethodArgumentResolver;
import org.springframework.web.method.support.ModelAndViewContainer;

/**
 * HTTP 계약(Android frontend/docs/material-quiz-ranking-contract.md §5): GET /api/materials/{m}/quiz/{q}/ranking
 * 200 필드·isMe·식별자 미노출, 오류 {status, code, message} — 404 QUIZ_NOT_FOUND/MATERIAL_NOT_FOUND(code 포함), 403 FORBIDDEN,
 * 400 INVALID_LIMIT, 503 RANKING_UNAVAILABLE. 공유 API 오류 코드. 기존 submit 404/403 은 status·message 유지(+code).
 */
class MaterialQuizRankingHttpContractTest {

    static final long USER = 55L;
    MockMvc mvc;
    MaterialQuizService quizService;
    MaterialShareService shareService;

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
        quizService = mock(MaterialQuizService.class);
        shareService = mock(MaterialShareService.class);
        mvc = MockMvcBuilders.standaloneSetup(
                        new MaterialController(mock(MaterialService.class), mock(AiIntegrationService.class),
                                mock(StudyNoteAnalysisService.class), quizService,
                                mock(com.studybridge.api.service.MaterialFeedbackService.class)),
                        new MaterialShareController(shareService))
                .setControllerAdvice(new GlobalExceptionHandler())
                .setCustomArgumentResolvers(new PrincipalResolver())
                .build();
    }

    @Test
    void ranking_200_contractFields_noIdentifiers() throws Exception {
        QuizDTO.RankingEntry me = QuizDTO.RankingEntry.builder().rank(1).nickname("바다").score(100).correctCount(10).totalQuestions(10)
                .attemptCount(1).achievedAt(LocalDateTime.parse("2026-10-27T10:00:00")).isMe(true).build();
        QuizDTO.RankingEntry other = QuizDTO.RankingEntry.builder().rank(1).nickname("하늘").score(100).correctCount(10).totalQuestions(10)
                .attemptCount(2).achievedAt(LocalDateTime.parse("2026-10-27T09:00:00")).isMe(false).build();
        when(quizService.ranking(eq(USER), eq(10L), eq(100L), eq(50))).thenReturn(QuizDTO.RankingResponse.builder()
                .materialId(10L).quizId(100L).rankingPolicy("BEST_SCORE").totalQuestions(10).totalParticipants(2L)
                .generatedAt(LocalDateTime.parse("2026-10-28T12:00:00")).entries(List.of(other, me)).me(me).build());
        mvc.perform(get("/api/materials/10/quiz/100/ranking").param("limit", "50"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.materialId").value(10))
                .andExpect(jsonPath("$.quizId").value(100))
                .andExpect(jsonPath("$.rankingPolicy").value("BEST_SCORE"))
                .andExpect(jsonPath("$.totalParticipants").value(2))
                .andExpect(jsonPath("$.entries[0].rank").value(1))
                .andExpect(jsonPath("$.entries[1].rank").value(1))
                .andExpect(jsonPath("$.entries[1].isMe").value(true))
                .andExpect(jsonPath("$.entries[0].attemptCount").value(2))
                .andExpect(jsonPath("$.me.isMe").value(true))
                .andExpect(jsonPath("$.entries[0].userId").doesNotExist())
                .andExpect(jsonPath("$.entries[0].email").doesNotExist())
                .andExpect(jsonPath("$.entries[0].me").doesNotExist());
    }

    @Test
    void ranking_errors_carryCodes() throws Exception {
        when(quizService.ranking(eq(USER), eq(10L), eq(404L), any())).thenThrow(new QuizAccessException.NotFound("QUIZ_NOT_FOUND", "퀴즈를 찾을 수 없습니다."));
        when(quizService.ranking(eq(USER), eq(11L), eq(100L), any())).thenThrow(new QuizAccessException.NotFound("MATERIAL_NOT_FOUND", "자료를 찾을 수 없습니다."));
        when(quizService.ranking(eq(USER), eq(12L), eq(100L), any())).thenThrow(new QuizAccessException.Forbidden("FORBIDDEN", "권한 없음"));
        when(quizService.ranking(eq(USER), eq(10L), eq(100L), eq(0))).thenThrow(new QuizAccessException.BadRequest("INVALID_LIMIT", "limit"));
        when(quizService.ranking(eq(USER), eq(13L), eq(100L), any())).thenThrow(new RankingUnavailableException("down", new RuntimeException()));
        mvc.perform(get("/api/materials/10/quiz/404/ranking")).andExpect(status().isNotFound())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$.code").value("QUIZ_NOT_FOUND")).andExpect(jsonPath("$.status").value(404));
        mvc.perform(get("/api/materials/11/quiz/100/ranking")).andExpect(status().isNotFound()).andExpect(jsonPath("$.code").value("MATERIAL_NOT_FOUND"));
        mvc.perform(get("/api/materials/12/quiz/100/ranking")).andExpect(status().isForbidden()).andExpect(jsonPath("$.code").value("FORBIDDEN"));
        mvc.perform(get("/api/materials/10/quiz/100/ranking").param("limit", "0")).andExpect(status().isBadRequest()).andExpect(jsonPath("$.code").value("INVALID_LIMIT"));
        mvc.perform(get("/api/materials/13/quiz/100/ranking")).andExpect(status().isServiceUnavailable())
                .andExpect(jsonPath("$.code").value("RANKING_UNAVAILABLE"));
    }

    @Test
    void existingSubmit_errors_keepStatusAndMessage_plusCode() throws Exception {
        when(quizService.submit(eq(USER), eq(10L), eq(100L), any())).thenThrow(new QuizAccessException.Forbidden("FORBIDDEN", "해당 퀴즈에 대한 권한이 없습니다."));
        mvc.perform(post("/api/materials/10/quiz/100/submit").contentType(MediaType.APPLICATION_JSON).content("{\"answers\":[]}"))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.status").value(403))
                .andExpect(jsonPath("$.message").value("해당 퀴즈에 대한 권한이 없습니다."));
    }

    @Test
    void shareEndpoints_passOwnerAndGroup_errorsCoded() throws Exception {
        when(shareService.share(USER, 10L, 33L)).thenReturn(Map.of("materialId", 10, "groupId", 33, "created", true));
        mvc.perform(post("/api/materials/10/shares").contentType(MediaType.APPLICATION_JSON).content("{\"groupId\":33}"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.groupId").value(33));
        when(shareService.share(USER, 10L, 34L)).thenThrow(new QuizAccessException.Forbidden("FORBIDDEN", "내가 가입한 그룹에만 공유할 수 있습니다."));
        mvc.perform(post("/api/materials/10/shares").contentType(MediaType.APPLICATION_JSON).content("{\"groupId\":34}"))
                .andExpect(status().isForbidden()).andExpect(jsonPath("$.code").value("FORBIDDEN"));
        when(shareService.sharedToGroup(USER, 99L)).thenThrow(new QuizAccessException.Forbidden("FORBIDDEN", "그룹 멤버만 볼 수 있습니다."));
        mvc.perform(get("/api/groups/99/shared-materials")).andExpect(status().isForbidden());
        mvc.perform(delete("/api/materials/10/shares/33")).andExpect(status().isNoContent());
        when(quizService.sharedQuizzes(eq(USER), anyLong())).thenReturn(List.of());
        mvc.perform(get("/api/materials/10/shared-quizzes")).andExpect(status().isOk());
    }
}
