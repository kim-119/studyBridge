package com.studybridge.api.controller;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.studybridge.api.dto.GroupStudyStatsDTO;
import com.studybridge.api.dto.GroupStudyStatsDTO.Range;
import com.studybridge.api.entity.User;
import com.studybridge.api.exception.GlobalExceptionHandler;
import com.studybridge.api.security.domain.CustomUserDetails;
import com.studybridge.api.service.GroupStudyStatsService;
import java.time.LocalDate;
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
 * HTTP 계약: GET /api/groups/{groupId}/stats/study-time, /stats/quiz-ranking 이 GlobalExceptionHandler 를 통해
 * 비멤버 403 / 없는 그룹 404 / 잘못된 range 400 을 JSON 으로 내고, 정상 응답에 서버 계산 rank·isMe 가 실린다.
 * (JWT 인증 자체는 SecurityConfig anyRequest().authenticated() — 여기서는 principal 을 고정 사용자로 주입한다.)
 */
class GroupStudyStatsHttpContractTest {

    private static final long USER = 55L;

    private MockMvc mvc;
    private GroupStudyStatsService statsService;

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
        // resolvePeriod/resolveRankingPeriod 는 실제 로직(고정 Clock), 집계 메서드만 stub — spy 사용.
        GroupStudyStatsService real = new GroupStudyStatsService(
                Mockito.mock(com.studybridge.api.repository.GroupStudyRepository.class),
                Mockito.mock(com.studybridge.api.repository.GroupStudyMemberRepository.class),
                Mockito.mock(com.studybridge.api.repository.TimerRepository.class),
                Mockito.mock(com.studybridge.api.repository.GroupStudyAttendanceRepository.class),
                Mockito.mock(com.studybridge.api.repository.GroupStudyQuizSessionAnswerRepository.class),
                java.time.Clock.fixed(java.time.Instant.parse("2026-09-30T07:00:00Z"), java.time.ZoneId.of("Asia/Seoul")));
        statsService = Mockito.spy(real);
        mvc = MockMvcBuilders.standaloneSetup(new GroupStudyStatsController(statsService))
                .setControllerAdvice(new GlobalExceptionHandler())
                .setCustomArgumentResolvers(new PrincipalResolver())
                .build();
    }

    @Test
    void studyTime_nonMember_403_json() throws Exception {
        Mockito.doThrow(new SecurityException("그룹 멤버만 그룹 통계를 조회할 수 있습니다."))
                .when(statsService).getStudyTimeRanking(eq(USER), eq(24L), any());
        mvc.perform(get("/api/groups/24/stats/study-time"))
                .andExpect(status().isForbidden())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON))
                .andExpect(jsonPath("$.status").value(403));
    }

    @Test
    void quizRanking_nonMember_403_and_missingGroup_404() throws Exception {
        Mockito.doThrow(new SecurityException("그룹 멤버만")).when(statsService).getQuizRanking(USER, 24L);
        Mockito.doThrow(new NoSuchElementException("Group study not found with ID: 999")).when(statsService).getQuizRanking(USER, 999L);
        mvc.perform(get("/api/groups/24/stats/quiz-ranking")).andExpect(status().isForbidden());
        mvc.perform(get("/api/groups/999/stats/quiz-ranking"))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.status").value(404));
    }

    @Test
    void studyTime_invalidRange_400_and_defaultIsAll() throws Exception {
        mvc.perform(get("/api/groups/32/stats/study-time").param("range", "YEAR"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.status").value(400));

        Mockito.doAnswer(inv -> {
            GroupStudyStatsService.Period p = inv.getArgument(2);
            return GroupStudyStatsDTO.StudyTimeRanking.builder().groupId(32L).range(p.range()).memberCount(2).totalStudySeconds(5400L)
                    .members(List.of(
                            GroupStudyStatsDTO.StudyTimeMember.builder().rank(1).userId(64L).nickname("SRE멤버E2E").studySeconds(3600L).sessionCount(2).isMe(false).activeNow(false).build(),
                            GroupStudyStatsDTO.StudyTimeMember.builder().rank(2).userId(USER).nickname("SRE오답").studySeconds(1800L).sessionCount(1).isMe(true).activeNow(true).build()))
                    .build();
        }).when(statsService).getStudyTimeRanking(eq(USER), eq(32L), any());
        mvc.perform(get("/api/groups/32/stats/study-time"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.range").value("ALL"))
                .andExpect(jsonPath("$.members[0].rank").value(1))
                .andExpect(jsonPath("$.members[0].userId").value(64))
                .andExpect(jsonPath("$.members[1].isMe").value(true))
                .andExpect(jsonPath("$.members[1].studySeconds").value(1800));
        mvc.perform(get("/api/groups/32/stats/study-time").param("range", "week").param("date", "2026-09-30"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.range").value("WEEK"));
    }

    @Test
    void quizRanking_ok_contract() throws Exception {
        Mockito.doReturn(
                GroupStudyStatsDTO.QuizRanking.builder().groupId(32L).memberCount(2).sessionCount(1)
                        .members(List.of(
                                GroupStudyStatsDTO.QuizRankingMember.builder().rank(1).userId(64L).score(23).correctCount(2).totalQuestions(3).accuracy(66.7).quizParticipationCount(1).isMe(false).build(),
                                GroupStudyStatsDTO.QuizRankingMember.builder().rank(2).userId(USER).score(0).correctCount(0).totalQuestions(0).accuracy(0.0).quizParticipationCount(0).isMe(true).build()))
                        .build()).when(statsService).getQuizRanking(USER, 32L);
        mvc.perform(get("/api/groups/32/stats/quiz-ranking"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.members[0].score").value(23))
                .andExpect(jsonPath("$.members[0].accuracy").value(66.7))
                .andExpect(jsonPath("$.members[1].quizParticipationCount").value(0))
                .andExpect(jsonPath("$.members[1].isMe").value(true));
    }

    @Test
    void existingAttendanceEndpoint_rejectsAll_400() throws Exception {
        mvc.perform(get("/api/groups/32/attendance").param("range", "ALL"))
                .andExpect(status().isBadRequest());
        Mockito.doReturn(
                GroupStudyStatsDTO.AttendanceBoard.builder().range(Range.WEEK).groupId(32L).periodStart(LocalDate.of(2026, 9, 28)).members(List.of()).build())
                .when(statsService).getAttendanceBoard(eq(USER), eq(32L), any());
        mvc.perform(get("/api/groups/32/attendance").param("range", "WEEK").param("date", "2026-09-30"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.range").value("WEEK"));
    }
}
