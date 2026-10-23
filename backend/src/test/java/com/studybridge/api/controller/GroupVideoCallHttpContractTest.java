package com.studybridge.api.controller;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.studybridge.api.entity.User;
import com.studybridge.api.exception.VideoCallException;
import com.studybridge.api.security.domain.CustomUserDetails;
import com.studybridge.api.service.GroupVideoCallService;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
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
 * HTTP 계약: 기존 클라이언트처럼 본문 없이 POST /video/token 해도 200 + token, 신규 클라이언트는 힌트 본문을 보낸다.
 * 비멤버는 JSON {status:403, code:NOT_GROUP_MEMBER}. (JWT 인증 자체는 SecurityConfig — principal 을 고정 주입)
 */
class GroupVideoCallHttpContractTest {

    private static final long USER = 8L;
    private MockMvc mvc;
    private GroupVideoCallService service;

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
        service = Mockito.mock(GroupVideoCallService.class);
        mvc = MockMvcBuilders.standaloneSetup(new GroupVideoCallController(service))
                .setCustomArgumentResolvers(new PrincipalResolver())
                .build();
    }

    @Test
    void token_withoutBody_legacyClient_ok() throws Exception {
        Mockito.when(service.issuePrimaryToken(eq(USER), eq(25L), isNull(), isNull()))
                .thenReturn(Map.of("token", "wss://x?token=tok", "connectionId", "con_A", "kind", "PRIMARY"));
        mvc.perform(post("/api/groups/25/video/token"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.token").value("wss://x?token=tok"))
                .andExpect(jsonPath("$.kind").value("PRIMARY"));
    }

    @Test
    void token_withHintBody_passesHints() throws Exception {
        Mockito.when(service.issuePrimaryToken(USER, 25L, "tab-abcdef12", "WEB"))
                .thenReturn(Map.of("token", "t", "connectionId", "con_B"));
        mvc.perform(post("/api/groups/25/video/token").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"clientInstanceId\":\"tab-abcdef12\",\"deviceType\":\"WEB\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.connectionId").value("con_B"));
    }

    @Test
    void nonMember_403_jsonWithStableCode() throws Exception {
        Mockito.when(service.issuePrimaryToken(anyLong(), anyLong(), any(), any()))
                .thenThrow(new VideoCallException(HttpStatus.FORBIDDEN, "NOT_GROUP_MEMBER", "그룹스터디 참여 멤버만 화상통화에 접속할 수 있습니다."));
        mvc.perform(post("/api/groups/99/video/token"))
                .andExpect(status().isForbidden())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$.status").value(403))
                .andExpect(jsonPath("$.code").value("NOT_GROUP_MEMBER"));
    }

    @Test
    void connections_returnsServerTruth() throws Exception {
        Mockito.when(service.listActiveConnections(USER, 25L)).thenReturn(Map.of(
                "activeUserCount", 2,
                "connections", List.of(Map.of("connectionId", "con_A", "kind", "PRIMARY", "userId", 8))));
        mvc.perform(get("/api/groups/25/video/connections"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.activeUserCount").value(2))
                .andExpect(jsonPath("$.connections[0].connectionId").value("con_A"));
    }
}
