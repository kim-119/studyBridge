package com.studybridge.api.service;

import com.studybridge.api.dto.GroupStudyStatsDTO;
import com.studybridge.api.dto.GroupStudyStatsDTO.QuizRankingMember;
import com.studybridge.api.dto.GroupStudyStatsDTO.Range;
import com.studybridge.api.dto.GroupStudyStatsDTO.StudyTimeMember;
import com.studybridge.api.entity.GroupStudy;
import com.studybridge.api.entity.GroupStudyMember;
import com.studybridge.api.entity.GroupStudyMemberStatus;
import com.studybridge.api.entity.GroupStudyQuizSessionStatus;
import com.studybridge.api.entity.GroupStudyRole;
import com.studybridge.api.entity.Timer;
import com.studybridge.api.entity.TimerEndReason;
import com.studybridge.api.entity.TimerStatus;
import com.studybridge.api.entity.User;
import com.studybridge.api.repository.GroupStudyAttendanceRepository;
import com.studybridge.api.repository.GroupStudyMemberRepository;
import com.studybridge.api.repository.GroupStudyQuizSessionAnswerRepository;
import com.studybridge.api.repository.GroupStudyRepository;
import com.studybridge.api.repository.TimerRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.time.Clock;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.NoSuchElementException;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicInteger;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyCollection;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * 그룹 학습시간 랭킹 / 퀴즈 랭킹 API 계약 테스트 (GroupStudyStatsService.getStudyTimeRanking / getQuizRanking).
 * 오늘 = 2026-09-30 16:00. 그룹 시작 2026-09-01. 멤버: 리더(1), 멤버(2), 신입(3, 닉네임·사진 null). 비멤버(9). 탈퇴자(4).
 * 저장소는 mock — RDS 집계 쿼리는 인메모리 답안 목록으로 같은 의미(GROUP BY)를 재현한다.
 */
class GroupStudyRankingStatsTest {

    private static final long GROUP = 10L;
    private static final long LEADER = 1L;
    private static final long MEMBER = 2L;
    private static final long NEWBIE = 3L;
    private static final long LEFT = 4L;      // 탈퇴한 사용자(JOINED 아님)
    private static final long OUTSIDER = 9L;
    private static final ZoneId SEOUL = ZoneId.of("Asia/Seoul");
    private static final LocalDateTime NOW = LocalDateTime.of(2026, 9, 30, 16, 0, 0);

    private GroupStudyStatsService service;
    private final List<Timer> timers = new ArrayList<>();
    private final AtomicInteger timerQueries = new AtomicInteger();
    private User leader, member, newbie, left;

    /** 채점 완료 답안 1건: sessionId, status, orderJson, userId, correct, points */
    private record Answer(long sessionId, GroupStudyQuizSessionStatus status, String orderJson, long userId, long questionId, boolean correct, int points) {}
    private final List<Answer> answers = new ArrayList<>();

    @BeforeEach
    void setUp() {
        leader = User.builder().id(LEADER).displayName("리더").photoUrl("leader.png").build();
        member = User.builder().id(MEMBER).displayName("멤버").photoUrl("https://cdn/m.png").build();
        newbie = User.builder().id(NEWBIE).displayName(null).photoUrl(null).build();
        left = User.builder().id(LEFT).displayName("탈퇴자").build();
        GroupStudy group = GroupStudy.builder().id(GROUP).leader(leader).startDate(LocalDate.of(2026, 9, 1)).targetStudyMinutes(240).build();

        GroupStudyRepository groups = mock(GroupStudyRepository.class);
        when(groups.findById(GROUP)).thenReturn(Optional.of(group));

        GroupStudyMemberRepository members = mock(GroupStudyMemberRepository.class);
        List<GroupStudyMember> joined = List.of(
                GroupStudyMember.builder().id(101L).groupStudy(group).user(leader).role(GroupStudyRole.LEADER).status(GroupStudyMemberStatus.JOINED).joinedAt(LocalDateTime.of(2026, 9, 1, 9, 0)).build(),
                GroupStudyMember.builder().id(102L).groupStudy(group).user(member).role(GroupStudyRole.MEMBER).status(GroupStudyMemberStatus.JOINED).joinedAt(LocalDateTime.of(2026, 9, 2, 9, 0)).nickname("한양대/3/멤버").build(),
                GroupStudyMember.builder().id(103L).groupStudy(group).user(newbie).role(GroupStudyRole.MEMBER).status(GroupStudyMemberStatus.JOINED).joinedAt(LocalDateTime.of(2026, 9, 29, 20, 0)).build());
        when(members.findWithUserByGroupStudyIdAndStatus(eq(GROUP), eq(GroupStudyMemberStatus.JOINED))).thenReturn(joined);

        TimerRepository timerRepo = mock(TimerRepository.class);
        when(timerRepo.findGroupSessionsOverlapping(eq(GROUP), anyCollection(), any(), any())).thenAnswer(inv -> {
            timerQueries.incrementAndGet();
            java.util.Collection<Long> userIds = inv.getArgument(1);
            LocalDateTime from = inv.getArgument(2);
            LocalDateTime to = inv.getArgument(3);
            return timers.stream()
                    .filter(t -> userIds.contains(t.getUser().getId()))
                    .filter(t -> t.getStatus() == TimerStatus.STARTED || t.getStatus() == TimerStatus.COMPLETED)
                    .filter(t -> t.getStartTime().isBefore(to) && (t.getEndTime() == null || t.getEndTime().isAfter(from)))
                    .toList();
        });

        GroupStudyQuizSessionAnswerRepository answerRepo = mock(GroupStudyQuizSessionAnswerRepository.class);
        when(answerRepo.aggregateBySessionAndUser(eq(GROUP))).thenAnswer(inv -> {
            Map<String, Object[]> rows = new LinkedHashMap<>();
            for (Answer a : answers) {
                Object[] row = rows.computeIfAbsent(a.sessionId + ":" + a.userId,
                        k -> new Object[]{a.sessionId, a.status, a.orderJson, a.userId, 0L, 0L, 0L});
                row[4] = (Long) row[4] + 1;
                row[5] = (Long) row[5] + (a.correct ? 1 : 0);
                row[6] = (Long) row[6] + a.points;
            }
            return new ArrayList<>(rows.values());
        });
        when(answerRepo.countGradedQuestionsBySession(eq(GROUP))).thenAnswer(inv -> {
            Map<Long, java.util.Set<Long>> q = new LinkedHashMap<>();
            for (Answer a : answers) q.computeIfAbsent(a.sessionId, k -> new java.util.HashSet<>()).add(a.questionId);
            List<Object[]> out = new ArrayList<>();
            q.forEach((sid, qs) -> out.add(new Object[]{sid, (long) qs.size()}));
            return out;
        });

        Clock clock = Clock.fixed(NOW.atZone(SEOUL).toInstant(), SEOUL);
        service = new GroupStudyStatsService(groups, members, timerRepo, mock(GroupStudyAttendanceRepository.class), answerRepo, clock);
    }

    private Timer session(User u, LocalDateTime start, LocalDateTime end, TimerEndReason reason) {
        Timer t = Timer.builder().id((long) (timers.size() + 1)).user(u).groupStudyId(GROUP).startTime(start).endTime(end)
                .status(TimerStatus.COMPLETED).endReason(reason)
                .durationSeconds(java.time.Duration.between(start, end).getSeconds()).lastHeartbeatAt(end).build();
        timers.add(t);
        return t;
    }

    private Timer session(User u, LocalDateTime start, LocalDateTime end) {
        return session(u, start, end, TimerEndReason.USER_STOP);
    }

    private GroupStudyStatsService.Period all() { return service.resolveRankingPeriod(null, null, null); }

    private StudyTimeMember row(GroupStudyStatsDTO.StudyTimeRanking r, long userId) {
        return r.getMembers().stream().filter(m -> m.getUserId() == userId).findFirst().orElseThrow();
    }

    private QuizRankingMember qrow(GroupStudyStatsDTO.QuizRanking r, long userId) {
        return r.getMembers().stream().filter(m -> m.getUserId() == userId).findFirst().orElseThrow();
    }

    // ═══════════════════════ STUDY TIME ═══════════════════════

    // 1. 정상 멤버 / 3. 여러 session 합산 / 5. 정상 종료 / 14. 정렬·rank 서버 계산
    @Test
    void studyTime_sumsMultipleSessions_andRanksOnServer() {
        session(member, LocalDateTime.of(2026, 9, 10, 9, 0), LocalDateTime.of(2026, 9, 10, 10, 0));   // 3600
        session(member, LocalDateTime.of(2026, 9, 30, 13, 0), LocalDateTime.of(2026, 9, 30, 14, 10, 20)); // 4220
        session(leader, LocalDateTime.of(2026, 9, 29, 23, 50), LocalDateTime.of(2026, 9, 30, 0, 20)); // 1800 (자정 넘김도 전체 기간에서는 한 덩어리)

        GroupStudyStatsDTO.StudyTimeRanking r = service.getStudyTimeRanking(MEMBER, GROUP, all());

        assertEquals(Range.ALL, r.getRange());
        assertNull(r.getPeriodStart());
        assertEquals(NOW, r.getGeneratedAt());
        assertEquals(3, r.getMemberCount());
        assertEquals(7820L + 1800L, r.getTotalStudySeconds());
        assertEquals(List.of(MEMBER, LEADER, NEWBIE), r.getMembers().stream().map(StudyTimeMember::getUserId).toList());
        assertEquals(List.of(1, 2, 3), r.getMembers().stream().map(StudyTimeMember::getRank).toList());
        StudyTimeMember me = row(r, MEMBER);
        assertEquals(7820L, me.getStudySeconds());
        assertEquals(2, me.getSessionCount());
        assertTrue(me.getIsMe());
        assertEquals("한양대/3/멤버", me.getNickname());
        assertEquals("https://cdn/m.png", me.getProfileImageUrl());
        assertEquals("MEMBER", me.getRole());
        assertFalse(me.getActiveNow());
        assertEquals(me, r.getMy());
        assertEquals("리더", row(r, LEADER).getNickname());
        assertEquals("LEADER", row(r, LEADER).getRole());
        assertFalse(row(r, LEADER).getIsMe());
        assertEquals(1, timerQueries.get(), "세션 조회는 그룹 단위 1회(N+1 없음)");
    }

    // 2. 학습 기록 없는 멤버 / 12. null profile
    @Test
    void studyTime_memberWithoutRecords_zeroContract_andNullProfile() {
        GroupStudyStatsDTO.StudyTimeRanking r = service.getStudyTimeRanking(LEADER, GROUP, all());
        StudyTimeMember n = row(r, NEWBIE);
        assertEquals(0L, n.getStudySeconds());
        assertEquals(0, n.getSessionCount());
        assertFalse(n.getActiveNow());
        assertNull(n.getNickname());
        assertNull(n.getProfileImageUrl());
        assertNotNull(n.getRank());
        assertEquals(0L, r.getTotalStudySeconds());
    }

    // 4. active session: 서버 시각 기준(마지막 heartbeat 까지, 미래 heartbeat 는 now 로 클램프), heartbeat 없는 진행 세션 제외
    @Test
    void studyTime_activeSession_countsUntilHeartbeat_clampedToNow() {
        timers.add(Timer.builder().id(50L).user(member).groupStudyId(GROUP).startTime(LocalDateTime.of(2026, 9, 30, 15, 0))
                .status(TimerStatus.STARTED).lastHeartbeatAt(LocalDateTime.of(2026, 9, 30, 15, 30)).build());
        timers.add(Timer.builder().id(51L).user(leader).groupStudyId(GROUP).startTime(LocalDateTime.of(2026, 9, 30, 15, 0))
                .status(TimerStatus.STARTED).lastHeartbeatAt(LocalDateTime.of(2026, 9, 30, 17, 0)).build()); // 시계 오차: 미래 heartbeat
        timers.add(Timer.builder().id(52L).user(newbie).groupStudyId(GROUP).startTime(LocalDateTime.of(2026, 6, 23, 21, 33))
                .status(TimerStatus.STARTED).lastHeartbeatAt(null).build()); // heartbeat 미지원 좀비

        GroupStudyStatsDTO.StudyTimeRanking r = service.getStudyTimeRanking(MEMBER, GROUP, all());

        assertEquals(1800L, row(r, MEMBER).getStudySeconds());
        assertTrue(row(r, MEMBER).getActiveNow());
        assertEquals(3600L, row(r, LEADER).getStudySeconds()); // 15:00 ~ now(16:00)
        assertEquals(0L, row(r, NEWBIE).getStudySeconds());
        assertFalse(row(r, NEWBIE).getActiveNow());
        assertEquals(0, row(r, NEWBIE).getSessionCount());
    }

    // 6. reaper 종료(HEARTBEAT_TIMEOUT) 는 마지막 heartbeat 까지의 정상 세션으로 합산 / STALE 취소(CANCELLED) 는 제외
    @Test
    void studyTime_reaperEndedSession_counted_cancelledExcluded() {
        session(member, LocalDateTime.of(2026, 9, 30, 9, 0), LocalDateTime.of(2026, 9, 30, 9, 45), TimerEndReason.HEARTBEAT_TIMEOUT);
        timers.add(Timer.builder().id(60L).user(member).groupStudyId(GROUP).startTime(LocalDateTime.of(2026, 9, 1, 9, 0))
                .status(TimerStatus.CANCELLED).endReason(TimerEndReason.STALE_NO_HEARTBEAT).build());

        GroupStudyStatsDTO.StudyTimeRanking r = service.getStudyTimeRanking(MEMBER, GROUP, all());
        assertEquals(2700L, row(r, MEMBER).getStudySeconds());
        assertEquals(1, row(r, MEMBER).getSessionCount());
    }

    // 7. 중복 종료 / 중복 session: 같은 세션 행이 두 번 와도 한 번만 합산, 클라이언트 durationSeconds 는 무시
    @Test
    void studyTime_duplicateRows_countedOnce_clientDurationIgnored() {
        Timer t = session(member, LocalDateTime.of(2026, 9, 30, 9, 0), LocalDateTime.of(2026, 9, 30, 10, 0));
        t.setDurationSeconds(999_999L); // 클라이언트/레거시가 보낸 값 — 신뢰하지 않음
        timers.add(t); // 두 번째 STOP 등으로 같은 세션이 다시 조회된 상황을 흉내

        GroupStudyStatsDTO.StudyTimeRanking r = service.getStudyTimeRanking(MEMBER, GROUP, all());
        assertEquals(3600L, row(r, MEMBER).getStudySeconds());
        assertEquals(1, row(r, MEMBER).getSessionCount());
    }

    // 8. 음수/시간 역전/null 방지
    @Test
    void studyTime_negativeOrReversedSessions_contributeZero() {
        session(member, LocalDateTime.of(2026, 9, 30, 10, 0), LocalDateTime.of(2026, 9, 30, 9, 0));  // endTime < startTime
        session(member, LocalDateTime.of(2026, 9, 30, 11, 0), LocalDateTime.of(2026, 9, 30, 11, 0)); // 0초
        timers.add(Timer.builder().id(70L).user(member).groupStudyId(GROUP).startTime(LocalDateTime.of(2026, 9, 30, 12, 0))
                .status(TimerStatus.COMPLETED).endTime(null).durationSeconds(-5L).build()); // endTime null 인 COMPLETED(손상 행)
        session(member, LocalDateTime.of(2026, 9, 30, 13, 0), LocalDateTime.of(2026, 9, 30, 13, 10)); // 600 정상

        GroupStudyStatsDTO.StudyTimeRanking r = service.getStudyTimeRanking(MEMBER, GROUP, all());
        assertEquals(600L, row(r, MEMBER).getStudySeconds());
        assertEquals(1, row(r, MEMBER).getSessionCount());
        assertTrue(r.getMembers().stream().allMatch(m -> m.getStudySeconds() >= 0));
    }

    // 9. 동점: competition rank(1,1,3) + 결정적 순서(닉네임 → userId)
    @Test
    void studyTime_ties_shareRank_deterministicOrder() {
        session(leader, LocalDateTime.of(2026, 9, 30, 9, 0), LocalDateTime.of(2026, 9, 30, 10, 0));
        session(member, LocalDateTime.of(2026, 9, 30, 9, 0), LocalDateTime.of(2026, 9, 30, 10, 0));

        GroupStudyStatsDTO.StudyTimeRanking r1 = service.getStudyTimeRanking(MEMBER, GROUP, all());
        GroupStudyStatsDTO.StudyTimeRanking r2 = service.getStudyTimeRanking(LEADER, GROUP, all());

        assertEquals(List.of(1, 1, 3), r1.getMembers().stream().map(StudyTimeMember::getRank).toList());
        // "리더" < "한양대/3/멤버" (가나다) → 리더 먼저
        assertEquals(List.of(LEADER, MEMBER, NEWBIE), r1.getMembers().stream().map(StudyTimeMember::getUserId).toList());
        assertEquals(r1.getMembers().stream().map(StudyTimeMember::getUserId).toList(),
                r2.getMembers().stream().map(StudyTimeMember::getUserId).toList(), "요청자가 달라도 순서는 같다");
    }

    // 10. 비멤버 403 / 11. 없는 group 404
    @Test
    void studyTime_authorization() {
        assertThrows(SecurityException.class, () -> service.getStudyTimeRanking(OUTSIDER, GROUP, all()));
        assertThrows(SecurityException.class, () -> service.getStudyTimeRanking(LEFT, GROUP, all()));
        assertThrows(SecurityException.class, () -> service.getStudyTimeRanking(null, GROUP, all()));
        assertThrows(NoSuchElementException.class, () -> service.getStudyTimeRanking(MEMBER, 999L, all()));
    }

    // 13. 탈퇴 사용자: 세션이 남아 있어도 랭킹에 나오지 않고 합계에도 들어가지 않는다
    @Test
    void studyTime_leftUser_excluded() {
        session(left, LocalDateTime.of(2026, 9, 30, 9, 0), LocalDateTime.of(2026, 9, 30, 12, 0));
        session(member, LocalDateTime.of(2026, 9, 30, 9, 0), LocalDateTime.of(2026, 9, 30, 9, 30));

        GroupStudyStatsDTO.StudyTimeRanking r = service.getStudyTimeRanking(MEMBER, GROUP, all());
        assertEquals(3, r.getMemberCount());
        assertTrue(r.getMembers().stream().noneMatch(m -> m.getUserId() == LEFT));
        assertEquals(1800L, r.getTotalStudySeconds());
    }

    // range=WEEK/DAY 도 지원(창 밖 세션 제외, 창 경계에서 잘림); ALL 은 출석부 API 에서는 400
    @Test
    void studyTime_rangeWindow_andAllRejectedElsewhere() {
        session(member, LocalDateTime.of(2026, 9, 20, 9, 0), LocalDateTime.of(2026, 9, 20, 10, 0)); // 지난주
        session(member, LocalDateTime.of(2026, 9, 27, 23, 30), LocalDateTime.of(2026, 9, 28, 0, 30)); // 주 경계(월 00:00) 30분만
        session(member, LocalDateTime.of(2026, 9, 30, 9, 0), LocalDateTime.of(2026, 9, 30, 9, 10));

        GroupStudyStatsService.Period week = service.resolveRankingPeriod("WEEK", LocalDate.of(2026, 9, 30), null);
        GroupStudyStatsDTO.StudyTimeRanking r = service.getStudyTimeRanking(MEMBER, GROUP, week);
        assertEquals(Range.WEEK, r.getRange());
        assertEquals(LocalDate.of(2026, 9, 28), r.getPeriodStart());
        assertEquals(LocalDate.of(2026, 10, 4), r.getPeriodEnd());
        assertEquals(1800L + 600L, row(r, MEMBER).getStudySeconds());
        assertEquals(2, row(r, MEMBER).getSessionCount());

        assertEquals(Range.ALL, service.resolveRankingPeriod("all", null, null).range());
        assertThrows(IllegalArgumentException.class, () -> service.resolvePeriod("ALL", null, null));
        assertThrows(IllegalArgumentException.class, () -> service.resolveRankingPeriod("YEAR", null, null));
    }

    // ═══════════════════════ QUIZ ═══════════════════════

    private void graded(long sessionId, GroupStudyQuizSessionStatus status, String order, long userId, long questionId, boolean correct, int points) {
        answers.add(new Answer(sessionId, status, order, userId, questionId, correct, points));
    }

    // 1. 정상 점수(기존 정책: points_awarded 합) / 5. 정답률 / 결과 rank·isMe
    @Test
    void quiz_scoreIsSumOfAwardedPoints_accuracyOverRevealedQuestions() {
        // 세션 1(완료, 3문제): 멤버 2문제 정답(10+7, 10+3), 1문제 오답(0)
        graded(1L, GroupStudyQuizSessionStatus.COMPLETED, "[11,12,13]", MEMBER, 11L, true, 17);
        graded(1L, GroupStudyQuizSessionStatus.COMPLETED, "[11,12,13]", MEMBER, 12L, true, 13);
        graded(1L, GroupStudyQuizSessionStatus.COMPLETED, "[11,12,13]", MEMBER, 13L, false, 0);
        // 리더는 1문제만 제출해 정답 → 미제출 2문제도 분모에 들어간다
        graded(1L, GroupStudyQuizSessionStatus.COMPLETED, "[11,12,13]", LEADER, 11L, true, 10);

        GroupStudyStatsDTO.QuizRanking r = service.getQuizRanking(MEMBER, GROUP);

        assertEquals(3, r.getMemberCount());
        assertEquals(1, r.getSessionCount());
        QuizRankingMember me = qrow(r, MEMBER);
        assertEquals(1, me.getRank());
        assertEquals(30, me.getScore());
        assertEquals(2, me.getCorrectCount());
        assertEquals(3, me.getTotalQuestions());
        assertEquals(66.7, me.getAccuracy());
        assertEquals(1, me.getQuizParticipationCount());
        assertTrue(me.getIsMe());
        assertEquals(me, r.getMy());
        QuizRankingMember l = qrow(r, LEADER);
        assertEquals(2, l.getRank());
        assertEquals(10, l.getScore());
        assertEquals(1, l.getCorrectCount());
        assertEquals(3, l.getTotalQuestions());
        assertEquals(33.3, l.getAccuracy());
    }

    // 2. 여러 퀴즈 누적 / 4. 일부 퀴즈만 참여 / 중단(ABORTED) 세션은 채점된 문제 수 기준
    @Test
    void quiz_accumulatesAcrossSessions_partialParticipation() {
        graded(1L, GroupStudyQuizSessionStatus.COMPLETED, "[1,2]", MEMBER, 1L, true, 10);
        graded(1L, GroupStudyQuizSessionStatus.COMPLETED, "[1,2]", MEMBER, 2L, true, 12);
        graded(1L, GroupStudyQuizSessionStatus.COMPLETED, "[1,2]", LEADER, 1L, false, 0);
        graded(2L, GroupStudyQuizSessionStatus.COMPLETED, "[3,4,5]", MEMBER, 3L, false, 0);
        graded(2L, GroupStudyQuizSessionStatus.COMPLETED, "[3,4,5]", MEMBER, 4L, true, 15);
        graded(3L, GroupStudyQuizSessionStatus.ABORTED, "[6,7,8,9]", LEADER, 6L, true, 10); // 1문제만 공개되고 중단
        graded(3L, GroupStudyQuizSessionStatus.ABORTED, "[6,7,8,9]", MEMBER, 6L, false, 0);

        GroupStudyStatsDTO.QuizRanking r = service.getQuizRanking(LEADER, GROUP);

        QuizRankingMember m = qrow(r, MEMBER);
        assertEquals(37, m.getScore());
        assertEquals(3, m.getCorrectCount());
        assertEquals(2 + 3 + 1, m.getTotalQuestions());
        assertEquals(3, m.getQuizParticipationCount());
        assertEquals(50.0, m.getAccuracy());
        QuizRankingMember l = qrow(r, LEADER);
        assertEquals(10, l.getScore());
        assertEquals(1, l.getCorrectCount());
        assertEquals(2 + 1, l.getTotalQuestions());
        assertEquals(2, l.getQuizParticipationCount());
        assertEquals(3, r.getSessionCount());
        assertEquals(List.of(MEMBER, LEADER, NEWBIE), r.getMembers().stream().map(QuizRankingMember::getUserId).toList());
    }

    // 3. 미참여 멤버는 0 계약으로 포함 / null profile
    @Test
    void quiz_nonParticipant_zeroContract() {
        graded(1L, GroupStudyQuizSessionStatus.COMPLETED, "[1]", MEMBER, 1L, true, 10);

        GroupStudyStatsDTO.QuizRanking r = service.getQuizRanking(NEWBIE, GROUP);
        QuizRankingMember n = qrow(r, NEWBIE);
        assertEquals(0, n.getScore());
        assertEquals(0, n.getCorrectCount());
        assertEquals(0, n.getTotalQuestions());
        assertEquals(0.0, n.getAccuracy());
        assertEquals(0, n.getQuizParticipationCount());
        assertNull(n.getNickname());
        assertNull(n.getProfileImageUrl());
        assertTrue(n.getIsMe());
        assertEquals(n, r.getMy());
        assertEquals(2, n.getRank()); // 리더(0점)와 동점 → 같은 등수 2
        assertEquals(2, qrow(r, LEADER).getRank());
    }

    // 6. 동점: score → accuracy → correctCount → 닉네임 → userId. 완전 동점은 같은 등수
    @Test
    void quiz_tieBreakers() {
        // 리더: 20점, 2/4 (50%) / 멤버: 20점, 2/2 (100%) → 멤버 1위
        graded(1L, GroupStudyQuizSessionStatus.COMPLETED, "[1,2,3,4]", LEADER, 1L, true, 10);
        graded(1L, GroupStudyQuizSessionStatus.COMPLETED, "[1,2,3,4]", LEADER, 2L, true, 10);
        graded(2L, GroupStudyQuizSessionStatus.COMPLETED, "[5,6]", MEMBER, 5L, true, 10);
        graded(2L, GroupStudyQuizSessionStatus.COMPLETED, "[5,6]", MEMBER, 6L, true, 10);

        GroupStudyStatsDTO.QuizRanking r = service.getQuizRanking(MEMBER, GROUP);
        assertEquals(List.of(MEMBER, LEADER, NEWBIE), r.getMembers().stream().map(QuizRankingMember::getUserId).toList());
        assertEquals(List.of(1, 2, 3), r.getMembers().stream().map(QuizRankingMember::getRank).toList());

        // 완전 동점(같은 score/accuracy/correct): 같은 등수, 순서는 닉네임 → 리더("리더") 가 "한양대/3/멤버" 앞
        answers.clear();
        graded(1L, GroupStudyQuizSessionStatus.COMPLETED, "[1]", LEADER, 1L, true, 10);
        graded(1L, GroupStudyQuizSessionStatus.COMPLETED, "[1]", MEMBER, 1L, true, 10);
        r = service.getQuizRanking(MEMBER, GROUP);
        assertEquals(List.of(LEADER, MEMBER, NEWBIE), r.getMembers().stream().map(QuizRankingMember::getUserId).toList());
        assertEquals(List.of(1, 1, 3), r.getMembers().stream().map(QuizRankingMember::getRank).toList());
    }

    // 7. 비멤버 403 / 없는 그룹 404 / 탈퇴자 답안은 집계 제외
    @Test
    void quiz_authorization_andLeftUserExcluded() {
        graded(1L, GroupStudyQuizSessionStatus.COMPLETED, "[1]", LEFT, 1L, true, 99);
        assertThrows(SecurityException.class, () -> service.getQuizRanking(OUTSIDER, GROUP));
        assertThrows(SecurityException.class, () -> service.getQuizRanking(LEFT, GROUP));
        assertThrows(NoSuchElementException.class, () -> service.getQuizRanking(MEMBER, 999L));

        GroupStudyStatsDTO.QuizRanking r = service.getQuizRanking(MEMBER, GROUP);
        assertTrue(r.getMembers().stream().noneMatch(m -> m.getUserId() == LEFT));
        assertTrue(r.getMembers().stream().allMatch(m -> m.getScore() == 0));
        assertEquals(1, r.getSessionCount());
    }

    @Test
    void countQuestions_parsesOrderJson() {
        assertEquals(3, GroupStudyStatsService.countQuestions("[11,12,13]"));
        assertEquals(1, GroupStudyStatsService.countQuestions("[ 7 ]"));
        assertEquals(0, GroupStudyStatsService.countQuestions("[]"));
        assertEquals(0, GroupStudyStatsService.countQuestions(null));
        assertEquals(0, GroupStudyStatsService.countQuestions("oops"));
    }
}
