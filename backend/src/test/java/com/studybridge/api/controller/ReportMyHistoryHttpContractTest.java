package com.studybridge.api.controller;

import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.studybridge.api.dto.ReportDTO;
import com.studybridge.api.entity.ReportReason;
import com.studybridge.api.entity.ReportStatus;
import com.studybridge.api.entity.User;
import com.studybridge.api.exception.GlobalExceptionHandler;
import com.studybridge.api.security.domain.CustomUserDetails;
import com.studybridge.api.service.ReportService;
import java.time.LocalDateTime;
import java.util.List;
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
 * HTTP 계약: GET /api/reports/me 는 principal 의 id 로만 서비스에 묻고(쿼리/본문 userId 무시), 신고자 본인용 필드만 JSON 으로 낸다.
 * (JWT 인증 자체는 SecurityConfig anyRequest().authenticated() — 여기서는 principal 을 고정 사용자로 주입한다.)
 */
class ReportMyHistoryHttpContractTest {

    private static final long ME = 55L;
    private static final long OTHER = 85L;

    private MockMvc mvc;
    private ReportService reportService;

    static final class PrincipalResolver implements HandlerMethodArgumentResolver {
        @Override
        public boolean supportsParameter(MethodParameter p) { return p.getParameterType().equals(CustomUserDetails.class); }
        @Override
        public Object resolveArgument(MethodParameter p, ModelAndViewContainer m, NativeWebRequest r, WebDataBinderFactory f) {
            return new CustomUserDetails(User.builder().id(ME).email("me@x").password("p").role("USER").build());
        }
    }

    @BeforeEach
    void setUp() {
        reportService = Mockito.mock(ReportService.class);
        mvc = MockMvcBuilders.standaloneSetup(new ReportController(reportService))
                .setControllerAdvice(new GlobalExceptionHandler())
                .setCustomArgumentResolvers(new PrincipalResolver())
                .build();
    }

    @Test
    void me_usesPrincipalIdOnly_andIgnoresClientUserIdParam() throws Exception {
        Mockito.when(reportService.getMyReports(eq(ME), eq("KNOWLEDGE"), eq(0), eq(20))).thenReturn(List.of(
                ReportDTO.MyReportResponse.builder()
                        .reportId(12L).source("KNOWLEDGE").targetType("POST").targetId(32L)
                        .targetSummary("하이").targetAvailable(true)
                        .reason(ReportReason.SPAM).details("광고").status(ReportStatus.PENDING)
                        .createdAt(LocalDateTime.of(2026, 10, 7, 12, 0)).build(),
                ReportDTO.MyReportResponse.builder()
                        .reportId(3L).source("GROUP").targetType("USER").targetId(null)
                        .targetSummary("탈퇴한 사용자").targetAvailable(false).groupId(32L).groupTitle("알고리즘 스터디")
                        .details("도배 및 스팸 - 반복 도배").status(null)
                        .createdAt(LocalDateTime.of(2026, 10, 6, 9, 0)).build()));

        // 타인 id 를 쿼리로 넘겨도 principal(55) 로만 조회된다.
        mvc.perform(get("/api/reports/me").param("userId", String.valueOf(OTHER)).accept(MediaType.APPLICATION_JSON))
                .andExpect(status().isOk())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$.length()").value(2))
                .andExpect(jsonPath("$[0].reportId").value(12))
                .andExpect(jsonPath("$[0].source").value("KNOWLEDGE"))
                .andExpect(jsonPath("$[0].targetType").value("POST"))
                .andExpect(jsonPath("$[0].targetId").value(32))
                .andExpect(jsonPath("$[0].targetSummary").value("하이"))
                .andExpect(jsonPath("$[0].targetAvailable").value(true))
                .andExpect(jsonPath("$[0].reason").value("SPAM"))
                .andExpect(jsonPath("$[0].status").value("PENDING"))
                .andExpect(jsonPath("$[0].createdAt").exists())
                .andExpect(jsonPath("$[1].source").value("GROUP"))
                .andExpect(jsonPath("$[1].groupTitle").value("알고리즘 스터디"))
                .andExpect(jsonPath("$[1].targetSummary").value("탈퇴한 사용자"))
                .andExpect(jsonPath("$[1].targetAvailable").value(false))
                // 신고자 본인용 응답에는 신고자/관리자 메모 필드가 없다.
                .andExpect(jsonPath("$[0].reporterId").doesNotExist())
                .andExpect(jsonPath("$[0].reporterNickname").doesNotExist())
                .andExpect(jsonPath("$[0].suspensionMemo").doesNotExist());

        Mockito.verify(reportService).getMyReports(ME, "KNOWLEDGE", 0, 20);
        Mockito.verify(reportService, Mockito.never()).getMyReports(OTHER, "KNOWLEDGE", 0, 20);
        Mockito.verify(reportService, Mockito.never()).listReports();
    }

    @Test
    void me_emptyListForUserWithoutReports() throws Exception {
        Mockito.when(reportService.getMyReports(anyLong(), eq("KNOWLEDGE"), eq(0), eq(20))).thenReturn(List.of());
        mvc.perform(get("/api/reports/me"))
                .andExpect(status().isOk())
                .andExpect(content().json("[]"));
    }
}
