package com.studybridge.api.controller;

import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.studybridge.api.dto.TimerDTO;
import com.studybridge.api.entity.TimerStatus;
import com.studybridge.api.entity.User;
import com.studybridge.api.exception.GlobalExceptionHandler;
import com.studybridge.api.security.domain.CustomUserDetails;
import com.studybridge.api.service.TimerService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.core.MethodParameter;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.bind.support.WebDataBinderFactory;
import org.springframework.web.context.request.NativeWebRequest;
import org.springframework.web.method.support.HandlerMethodArgumentResolver;
import org.springframework.web.method.support.ModelAndViewContainer;

/**
 * HTTP 계약: POST /api/timers/sync/{groupId}
 * ?heartbeat=true(웹) → 200 세션, heartbeat 없음(구 Android) → 연결만(활성 세션 없으면 204, 같은 그룹 세션이면 200), 비멤버 403.
 */
class TimerSyncHttpContractTest {

    static final long USER = 55L;
    MockMvc mvc;
    TimerService timerService;

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
        timerService = mock(TimerService.class);
        mvc = MockMvcBuilders.standaloneSetup(new TimerController(timerService))
                .setControllerAdvice(new GlobalExceptionHandler())
                .setCustomArgumentResolvers(new PrincipalResolver())
                .build();
    }

    @Test
    void legacySync_withoutSession_is204_noBody() throws Exception {
        when(timerService.syncGroupStudyTimer(USER, 25L, false)).thenReturn(null);
        mvc.perform(post("/api/timers/sync/25"))
                .andExpect(status().isNoContent())
                .andExpect(content().string(""));
        verify(timerService).syncGroupStudyTimer(eq(USER), eq(25L), eq(false));
    }

    @Test
    void sync_withSession_is200() throws Exception {
        TimerDTO.Response session = TimerDTO.Response.builder().id(9L).groupStudyId(25L).status(TimerStatus.STARTED).resumed(true).build();
        when(timerService.syncGroupStudyTimer(USER, 25L, true)).thenReturn(session);
        when(timerService.syncGroupStudyTimer(USER, 25L, false)).thenReturn(session);
        mvc.perform(post("/api/timers/sync/25").param("heartbeat", "true"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id").value(9))
                .andExpect(jsonPath("$.status").value("STARTED"));
        mvc.perform(post("/api/timers/sync/25"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.groupStudyId").value(25));
    }

    @Test
    void sync_nonMember_is403() throws Exception {
        when(timerService.syncGroupStudyTimer(eq(USER), anyLong(), eq(false))).thenThrow(new SecurityException("멤버만"));
        mvc.perform(post("/api/timers/sync/99"))
                .andExpect(status().isForbidden());
    }
}
