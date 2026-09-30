package com.studybridge.api.service;

import com.studybridge.api.dto.GroupStudyStatsDTO;
import com.studybridge.api.dto.GroupStudyStatsDTO.DaySummary;
import com.studybridge.api.dto.GroupStudyStatsDTO.Range;
import com.studybridge.api.entity.GroupStudy;
import com.studybridge.api.entity.GroupStudyAttendance;
import com.studybridge.api.entity.GroupStudyMember;
import com.studybridge.api.entity.GroupStudyMemberStatus;
import com.studybridge.api.entity.GroupStudyRole;
import com.studybridge.api.entity.Timer;
import com.studybridge.api.entity.TimerStatus;
import com.studybridge.api.entity.User;
import com.studybridge.api.repository.GroupStudyAttendanceRepository;
import com.studybridge.api.repository.GroupStudyMemberRepository;
import com.studybridge.api.repository.GroupStudyRepository;
import com.studybridge.api.repository.TimerRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.time.Clock;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.List;
import java.util.NoSuchElementException;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyCollection;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * 출석부/개인 통계 API 계약 테스트 (T9~T23 중 통계·권한·랭킹·자정 분할).
 * 오늘 = 2026-09-30(수). WEEK = 09-28(월)~10-04(일). 그룹 시작 2026-09-01, 목표 4시간(14400초).
 */
class GroupStudyStatsServiceTest {

    private static final long GROUP = 10L;
    private static final long LEADER = 1L;   // 오래전 가입
    private static final long MEMBER = 2L;   // 오래전 가입
    private static final long NEWBIE = 3L;   // 어제(09-29) 가입
    private static final long OUTSIDER = 9L; // 비멤버
    private static final ZoneId SEOUL = ZoneId.of("Asia/Seoul");
    private static final LocalDateTime NOW = LocalDateTime.of(2026, 9, 30, 16, 0, 0);

    private GroupStudyStatsService service;
    private final List<Timer> timers = new ArrayList<>();
    private final List<GroupStudyAttendance> attendance = new ArrayList<>();
    private GroupStudy group;
    private User leader, member, newbie;

    @BeforeEach
    void setUp() {
        leader = User.builder().id(LEADER).displayName("리더").build();
        member = User.builder().id(MEMBER).displayName("멤버").build();
        newbie = User.builder().id(NEWBIE).displayName("신입").build();
        group = GroupStudy.builder().id(GROUP).leader(leader).startDate(LocalDate.of(2026, 9, 1)).targetStudyMinutes(240).build();

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
            LocalDateTime from = inv.getArgument(2);
            LocalDateTime to = inv.getArgument(3);
            return timers.stream().filter(t -> t.getStartTime().isBefore(to) && (t.getEndTime() == null || t.getEndTime().isAfter(from))).toList();
        });
        GroupStudyAttendanceRepository attRepo = mock(GroupStudyAttendanceRepository.class);
        when(attRepo.findByGroupStudyIdAndDateBetween(eq(GROUP), any(), any())).thenAnswer(inv -> {
            LocalDate from = inv.getArgument(1);
            LocalDate to = inv.getArgument(2);
            return attendance.stream().filter(a -> !a.getDate().isBefore(from) && !a.getDate().isAfter(to)).toList();
        });

        Clock clock = Clock.fixed(NOW.atZone(SEOUL).toInstant(), SEOUL);
        service = new GroupStudyStatsService(groups, members, timerRepo, attRepo, clock);
    }

    private void session(User u, LocalDateTime start, LocalDateTime end) {
        timers.add(Timer.builder().id((long) (timers.size() + 1)).user(u).groupStudyId(GROUP).startTime(start).endTime(end)
                .status(TimerStatus.COMPLETED).durationSeconds(java.time.Duration.between(start, end).getSeconds()).lastHeartbeatAt(end).build());
    }

    private GroupStudyStatsService.Period day(LocalDate d) { return service.resolvePeriod("DAY", d, null); }

    // T13~T16 DAY: total / maxFocus / firstStartedAt / lastEndedAt / sessionCount / achievementRate
    @Test
    void t13_t16_dayStats() {
        session(member, LocalDateTime.of(2026, 9, 30, 9, 21, 4), LocalDateTime.of(2026, 9, 30, 10, 41, 24)); // 4820s
        session(member, LocalDateTime.of(2026, 9, 30, 11, 0, 0), LocalDateTime.of(2026, 9, 30, 12, 0, 0));   // 3600s
        session(member, LocalDateTime.of(2026, 9, 30, 13, 0, 0), LocalDateTime.of(2026, 9, 30, 14, 10, 20)); // 4220s
        session(member, LocalDateTime.of(2026, 9, 30, 15, 33, 14), LocalDateTime.of(2026, 9, 30, 15, 33, 14)); // 0s(무시)

        GroupStudyStatsDTO.MyStudyStats s = service.getMyStats(MEMBER, GROUP, day(LocalDate.of(2026, 9, 30)));
        assertEquals(Range.DAY, s.getRange());
        assertEquals(LocalDate.of(2026, 9, 30), s.getDate());
        assertEquals(12640L, s.getTotalStudySeconds());
        assertEquals(4820L, s.getMaxFocusSeconds());
        assertEquals(LocalTime.of(9, 21, 4), s.getFirstStartedAt());
        assertEquals(LocalTime.of(14, 10, 20), s.getLastEndedAt());
        assertEquals(3, s.getSessionCount());
        assertEquals(14400L, s.getTargetStudySeconds());
        assertEquals(87.78, s.getAchievementRate());
        assertEquals(1, s.getDays().size());
        assertTrue(s.getDays().get(0).getAttended());
    }

    // DAY: 진행 중 세션은 마지막 heartbeat 까지만 포함, heartbeat 없는 진행 중 세션은 제외
    @Test
    void dayStats_runningSession_countsUntilLastHeartbeat() {
        timers.add(Timer.builder().id(50L).user(member).groupStudyId(GROUP).startTime(LocalDateTime.of(2026, 9, 30, 15, 0))
                .status(TimerStatus.STARTED).lastHeartbeatAt(LocalDateTime.of(2026, 9, 30, 15, 30)).build());
        timers.add(Timer.builder().id(51L).user(leader).groupStudyId(GROUP).startTime(LocalDateTime.of(2026, 6, 23, 21, 33))
                .status(TimerStatus.STARTED).lastHeartbeatAt(null).build()); // 98일 좀비
        assertEquals(1800L, service.getMyStats(MEMBER, GROUP, day(LocalDate.of(2026, 9, 30))).getTotalStudySeconds());
        assertEquals(0L, service.getMyStats(LEADER, GROUP, day(LocalDate.of(2026, 9, 30))).getTotalStudySeconds());
    }

    // T8/T19 자정 넘는 세션의 날짜별 split (23:50~00:20 → 9/29 10분 + 9/30 20분)
    @Test
    void midnightSplit_inDailySummaries() {
        session(member, LocalDateTime.of(2026, 9, 29, 23, 50), LocalDateTime.of(2026, 9, 30, 0, 20));
        GroupStudyStatsDTO.MyStudyStats week = service.getMyStats(MEMBER, GROUP, service.resolvePeriod("WEEK", LocalDate.of(2026, 9, 30), null));
        DaySummary d29 = week.getDays().stream().filter(d -> d.getDate().equals(LocalDate.of(2026, 9, 29))).findFirst().orElseThrow();
        DaySummary d30 = week.getDays().stream().filter(d -> d.getDate().equals(LocalDate.of(2026, 9, 30))).findFirst().orElseThrow();
        assertEquals(600L, d29.getTotalStudySeconds());
        assertEquals(LocalTime.of(23, 50), d29.getFirstStartedAt());
        assertEquals(LocalTime.MIDNIGHT, d29.getLastEndedAt());
        assertEquals(1200L, d30.getTotalStudySeconds());
        assertEquals(LocalTime.MIDNIGHT, d30.getFirstStartedAt());
        assertEquals(LocalTime.of(0, 20), d30.getLastEndedAt());
        assertEquals(1800L, week.getTotalStudySeconds());
        assertEquals(2, week.getAttendanceDays());
    }

    // T17 WEEK: 월~일 7일 셀, 합계/평균(대상일수 분모)/출석일/eligibleDays(미래 제외)
    @Test
    void t17_weekAggregate() {
        session(leader, LocalDateTime.of(2026, 9, 28, 10, 0), LocalDateTime.of(2026, 9, 28, 12, 0)); // 7200
        session(leader, LocalDateTime.of(2026, 9, 30, 9, 0), LocalDateTime.of(2026, 9, 30, 10, 0));  // 3600
        GroupStudyStatsDTO.MyStudyStats w = service.getMyStats(LEADER, GROUP, service.resolvePeriod("WEEK", LocalDate.of(2026, 9, 30), null));
        assertEquals(LocalDate.of(2026, 9, 28), w.getPeriodStart());
        assertEquals(LocalDate.of(2026, 10, 4), w.getPeriodEnd());
        assertEquals(7, w.getDays().size());
        assertEquals(10800L, w.getTotalStudySeconds());
        assertEquals(3, w.getEligibleDays()); // 28,29,30 (미래 제외)
        assertEquals(2, w.getAttendanceDays());
        assertEquals(66.7, w.getAttendanceRate());
        assertEquals(3600L, w.getAverageDailyStudySeconds()); // 10800 / 3
        assertEquals(25.0, w.getAchievementRate());          // 3600 / 14400
        assertEquals(7200L, w.getMaxFocusSeconds());
        assertNull(w.getFirstStartedAt());
        assertFalse(w.getDays().get(6).getAttended()); // 10-04 미래
    }

    // T18 MONTH: 달력 월 전체 셀, month=YYYY-MM 파라미터
    @Test
    void t18_monthAggregate_calendarCells() {
        session(member, LocalDateTime.of(2026, 9, 3, 10, 0), LocalDateTime.of(2026, 9, 3, 11, 0));
        session(member, LocalDateTime.of(2026, 9, 30, 10, 0), LocalDateTime.of(2026, 9, 30, 12, 0));
        GroupStudyStatsDTO.MyStudyStats m = service.getMyStats(MEMBER, GROUP, service.resolvePeriod("MONTH", null, "2026-09"));
        assertEquals(LocalDate.of(2026, 9, 1), m.getPeriodStart());
        assertEquals(LocalDate.of(2026, 9, 30), m.getPeriodEnd());
        assertEquals(30, m.getDays().size());
        assertEquals(10800L, m.getTotalStudySeconds());
        assertEquals(2, m.getAttendanceDays());
        assertEquals(29, m.getEligibleDays()); // 가입 9/2 ~ 9/30
        assertEquals(LocalDate.of(2026, 9, 3), m.getDays().get(2).getDate());
        assertEquals(3600L, m.getDays().get(2).getTotalStudySeconds());
        // 8월 조회: 세션 없음 → 전부 0, eligibleDays 0(그룹 시작 전)
        GroupStudyStatsDTO.MyStudyStats aug = service.getMyStats(MEMBER, GROUP, service.resolvePeriod("MONTH", null, "2026-08"));
        assertEquals(31, aug.getDays().size());
        assertEquals(0L, aug.getTotalStudySeconds());
        assertEquals(0, aug.getEligibleDays());
        assertEquals(0.0, aug.getAttendanceRate());
    }

    // T9/T10/T11/T19 출석부: eligibleDays(기존 7일 vs 신입 2일), competition ranking, my
    @Test
    void t19_attendanceBoard_eligibleDays_andCompetitionRank() {
        // 최근 7일 창 대신 WEEK(09-28~10-04, 오늘 09-30 → 대상 최대 3일)
        session(leader, LocalDateTime.of(2026, 9, 28, 10, 0), LocalDateTime.of(2026, 9, 28, 20, 0)); // 10h
        session(member, LocalDateTime.of(2026, 9, 29, 10, 0), LocalDateTime.of(2026, 9, 29, 19, 0)); // 9h
        session(newbie, LocalDateTime.of(2026, 9, 30, 1, 0), LocalDateTime.of(2026, 9, 30, 10, 0));  // 9h (동률)
        attendance.add(GroupStudyAttendance.builder().id(1L).groupStudy(group).user(leader).date(LocalDate.of(2026, 9, 30))
                .checkInTime(LocalDateTime.of(2026, 9, 30, 8, 0)).status("PRESENT").studyDurationSeconds(0L).build()); // 레거시 0초 체크인 = 출석

        GroupStudyStatsDTO.AttendanceBoard b = service.getAttendanceBoard(NEWBIE, GROUP, service.resolvePeriod("WEEK", LocalDate.of(2026, 9, 30), null));
        assertEquals(3, b.getMemberCount());
        assertEquals(LEADER, b.getMembers().get(0).getUserId());
        assertEquals(1, b.getMembers().get(0).getRank());
        assertEquals(2, b.getMembers().get(1).getRank());
        assertEquals(2, b.getMembers().get(2).getRank());   // 9h 동률 → 둘 다 2등(다음은 4)
        assertEquals("한양대/3/멤버", b.getMembers().stream().filter(r -> r.getUserId().equals(MEMBER)).findFirst().orElseThrow().getNickname());

        var leaderRow = b.getMembers().stream().filter(r -> r.getUserId().equals(LEADER)).findFirst().orElseThrow();
        assertEquals(3, leaderRow.getEligibleDays());      // 28,29,30
        assertEquals(2, leaderRow.getAttendanceDays());    // 28(세션) + 30(레거시 체크인)
        assertEquals(66.7, leaderRow.getAttendanceRate());
        var newbieRow = b.getMy();
        assertNotNull(newbieRow);
        assertEquals(NEWBIE, newbieRow.getUserId());
        assertEquals(2, newbieRow.getEligibleDays());      // 가입 29 → 29,30
        assertEquals(1, newbieRow.getAttendanceDays());
        assertEquals(50.0, newbieRow.getAttendanceRate());
        assertEquals(7, newbieRow.getDays().size());
        // 그룹 전체: 분모 3+3+2=8, 분자 2+1+1=4 → 50.0
        assertEquals(8L, b.getTotalEligibleDays());
        assertEquals(4L, b.getTotalAttendanceDays());
        assertEquals(50.0, b.getAttendanceRate());
        assertEquals(14400L, b.getTargetStudySeconds());
    }

    // T20 no-data user: 0 / null 계약
    @Test
    void t20_noDataUser_zeroContract() {
        GroupStudyStatsDTO.MyStudyStats s = service.getMyStats(NEWBIE, GROUP, day(LocalDate.of(2026, 9, 30)));
        assertEquals(0L, s.getTotalStudySeconds());
        assertEquals(0L, s.getMaxFocusSeconds());
        assertNull(s.getFirstStartedAt());
        assertNull(s.getLastEndedAt());
        assertEquals(0, s.getSessionCount());
        assertEquals(0.0, s.getAchievementRate());
        assertEquals(1, s.getEligibleDays());
        assertEquals(0, s.getAttendanceDays());
        assertFalse(s.getDays().get(0).getAttended());
    }

    // T21 비회원 차단(403) / T22 타인 데이터 직접 조회 경로 없음(/me) / T23 leader 정상
    @Test
    void t21_t23_authorization() {
        assertThrows(SecurityException.class, () -> service.getMyStats(OUTSIDER, GROUP, day(LocalDate.of(2026, 9, 30))));
        assertThrows(SecurityException.class, () -> service.getAttendanceBoard(OUTSIDER, GROUP, day(LocalDate.of(2026, 9, 30))));
        assertThrows(NoSuchElementException.class, () -> service.getMyStats(LEADER, 999L, day(LocalDate.of(2026, 9, 30))));
        GroupStudyStatsDTO.AttendanceBoard b = service.getAttendanceBoard(LEADER, GROUP, day(LocalDate.of(2026, 9, 30)));
        assertEquals(LEADER, b.getMy().getUserId());
        assertEquals("LEADER", b.getMy().getRole());
    }

    @Test
    void resolvePeriod_validation() {
        assertThrows(IllegalArgumentException.class, () -> service.resolvePeriod("YEAR", null, null));
        assertThrows(IllegalArgumentException.class, () -> service.resolvePeriod("MONTH", null, "2026/09"));
        assertEquals(Range.WEEK, service.resolvePeriod(null, null, null).range());
        assertEquals(LocalDate.of(2026, 9, 28), service.resolvePeriod("week", LocalDate.of(2026, 10, 4), null).start());
    }

    @Test
    void competitionRank_1_2_2_4() {
        List<GroupStudyStatsDTO.MemberAttendance> rows = new ArrayList<>(List.of(
                GroupStudyStatsDTO.MemberAttendance.builder().userId(1L).nickname("a").studySeconds(36000L).build(),
                GroupStudyStatsDTO.MemberAttendance.builder().userId(2L).nickname("b").studySeconds(32400L).build(),
                GroupStudyStatsDTO.MemberAttendance.builder().userId(3L).nickname("c").studySeconds(32400L).build(),
                GroupStudyStatsDTO.MemberAttendance.builder().userId(4L).nickname("d").studySeconds(28800L).build()));
        GroupStudyStatsService.assignCompetitionRank(rows);
        assertEquals(List.of(1, 2, 2, 4), rows.stream().map(GroupStudyStatsDTO.MemberAttendance::getRank).toList());
    }
}
