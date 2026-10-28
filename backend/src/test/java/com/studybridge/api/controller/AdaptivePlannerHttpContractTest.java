package com.studybridge.api.controller;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.studybridge.api.entity.User;
import com.studybridge.api.exception.GlobalExceptionHandler;
import com.studybridge.api.security.domain.CustomUserDetails;
import com.studybridge.api.service.adaptive.AdaptivePlannerApplyService;
import com.studybridge.api.service.adaptive.AdaptivePlannerException;
import com.studybridge.api.service.adaptive.AdaptivePlannerService;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.core.MethodParameter;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.bind.support.WebDataBinderFactory;
import org.springframework.web.context.request.NativeWebRequest;
import org.springframework.web.method.support.HandlerMethodArgumentResolver;
import org.springframework.web.method.support.ModelAndViewContainer;

/**
 * HTTP 계약: POST /api/planners/{id}/adaptive · /adaptive/apply — JWT 사용자 id 전달, 오류 본문 {error:{code,message,retryable}},
 * 429/503 Retry-After 헤더, 403/404/409 매핑. (인증 자체는 SecurityConfig anyRequest().authenticated() 가 막는다.)
 */
class AdaptivePlannerHttpContractTest {

    static final long USER = 55L;
    private MockMvc mvc;
    private AdaptivePlannerService service;
    private AdaptivePlannerApplyService applyService;

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
        service = mock(AdaptivePlannerService.class);
        applyService = mock(AdaptivePlannerApplyService.class);
        mvc = MockMvcBuilders.standaloneSetup(new AdaptivePlannerController(service, applyService))
                .setControllerAdvice(new GlobalExceptionHandler())
                .setCustomArgumentResolvers(new PrincipalResolver())
                .build();
    }

    @Test
    void recommend_passesJwtUserMinutesAndStep() throws Exception {
        when(service.recommend(eq(USER), eq(7L), eq(60), eq(false), eq(12L)))
                .thenReturn(Map.of("mode", "ROADMAP_COACH", "availableMinutes", 60));
        mvc.perform(post("/api/planners/7/adaptive").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"availableMinutes\":60,\"useLlm\":false,\"currentStepId\":12}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.mode").value("ROADMAP_COACH"));
    }

    @Test
    void recommend_emptyBody_defaultsAreDecidedByService() throws Exception {
        when(service.recommend(eq(USER), eq(7L), isNull(), isNull(), isNull())).thenReturn(Map.of("availableMinutes", 30));
        mvc.perform(post("/api/planners/7/adaptive")).andExpect(status().isOk()).andExpect(jsonPath("$.availableMinutes").value(30));
    }

    @Test
    void foreignPlanner_403_missing_404() throws Exception {
        when(service.recommend(eq(USER), eq(8L), any(), any(), any())).thenThrow(new SecurityException("x"));
        when(service.recommend(eq(USER), eq(9L), any(), any(), any())).thenThrow(new java.util.NoSuchElementException("x"));
        mvc.perform(post("/api/planners/8/adaptive").contentType(MediaType.APPLICATION_JSON).content("{}"))
                .andExpect(status().isForbidden()).andExpect(jsonPath("$.error.code").value("FORBIDDEN"));
        mvc.perform(post("/api/planners/9/adaptive").contentType(MediaType.APPLICATION_JSON).content("{}"))
                .andExpect(status().isNotFound()).andExpect(jsonPath("$.error.code").value("NOT_FOUND"));
    }

    @Test
    void busy429_carriesRetryAfterHeader_andRetryableBody() throws Exception {
        when(service.recommend(eq(USER), eq(7L), any(), any(), any())).thenThrow(new AdaptivePlannerException(HttpStatus.TOO_MANY_REQUESTS,
                "ADAPTIVE_BUSY", "요청이 많아 잠시 후 다시 시도해 주세요.", true, 4, Map.of("upstreamStatus", 429)));
        mvc.perform(post("/api/planners/7/adaptive").contentType(MediaType.APPLICATION_JSON).content("{\"availableMinutes\":30}"))
                .andExpect(status().isTooManyRequests())
                .andExpect(header().string("Retry-After", "4"))
                .andExpect(jsonPath("$.error.code").value("ADAPTIVE_BUSY"))
                .andExpect(jsonPath("$.error.retryable").value(true))
                .andExpect(jsonPath("$.error.retryAfterSeconds").value(4));
    }

    @Test
    void timeout504_isRetryable_withoutRetryAfterHeader() throws Exception {
        when(service.recommend(eq(USER), eq(7L), any(), any(), any())).thenThrow(new AdaptivePlannerException(HttpStatus.GATEWAY_TIMEOUT,
                "ADAPTIVE_TIMEOUT", "AI 응답 시간이 초과되었습니다.", true, null, null));
        mvc.perform(post("/api/planners/7/adaptive").contentType(MediaType.APPLICATION_JSON).content("{}"))
                .andExpect(status().isGatewayTimeout())
                .andExpect(header().doesNotExist("Retry-After"))
                .andExpect(jsonPath("$.error.retryable").value(true));
    }

    @Test
    void apply_passesTokenAndSelection_staleIs409() throws Exception {
        when(applyService.apply(eq(USER), eq(7L), eq("tok"), eq(List.of("S:7:2026-10-29"))))
                .thenReturn(Map.of("alreadyApplied", false, "refreshRequired", true));
        mvc.perform(post("/api/planners/7/adaptive/apply").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"proposalToken\":\"tok\",\"changeIds\":[\"S:7:2026-10-29\"]}"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.refreshRequired").value(true));

        when(applyService.apply(eq(USER), eq(7L), eq("old"), any())).thenThrow(new AdaptivePlannerException(HttpStatus.CONFLICT,
                "ADAPTIVE_STALE", "추천 이후 플래너가 바뀌어 이 제안을 반영할 수 없습니다."));
        mvc.perform(post("/api/planners/7/adaptive/apply").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"proposalToken\":\"old\",\"changeIds\":[\"S:7:2026-10-29\"]}"))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.error.code").value("ADAPTIVE_STALE"))
                .andExpect(jsonPath("$.error.retryable").value(false));
    }

    @Test
    void unexpectedError_is500_withoutLeakingDetails() throws Exception {
        when(service.recommend(eq(USER), eq(7L), any(), any(), any())).thenThrow(new IllegalStateException("db password=secret"));
        mvc.perform(post("/api/planners/7/adaptive").contentType(MediaType.APPLICATION_JSON).content("{}"))
                .andExpect(status().isInternalServerError())
                .andExpect(jsonPath("$.error.code").value("ADAPTIVE_INTERNAL_ERROR"))
                .andExpect(jsonPath("$.error.message").value("AI 학습 내비게이터 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."));
    }
}
