package com.studybridge.api.service;

import com.studybridge.api.dto.TimerDTO;
import com.studybridge.api.entity.GroupStudy;
import com.studybridge.api.entity.GroupStudyAttendance;
import com.studybridge.api.entity.GroupStudyMemberStatus;
import com.studybridge.api.entity.Timer;
import com.studybridge.api.entity.TimerEndReason;
import com.studybridge.api.entity.TimerStatus;
import com.studybridge.api.entity.User;
import com.studybridge.api.repository.GroupStudyAttendanceRepository;
import com.studybridge.api.repository.GroupStudyMemberRepository;
import com.studybridge.api.repository.GroupStudyRepository;
import com.studybridge.api.repository.TimerRepository;
import com.studybridge.api.repository.UserRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicLong;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * 공부 세션(Timer) 서버 소스오브트루스 + 출석 원장 크레딧 테스트 (T1~T8).
 * 저장소는 인메모리 fake(Mockito answer)로 대체하고 Clock 을 조작해 시간 흐름을 시뮬레이션한다.
 */
class StudySessionTimerServiceTest {

    private static final long USER = 7L;
    private static final long GROUP = 10L;
    private static final long OTHER_GROUP = 11L;
    private static final ZoneId SEOUL = ZoneId.of("Asia/Seoul");

    private MutableClock clock;
    private TimerService service;
    private final Map<Long, Timer> timers = new HashMap<>();
    private final List<GroupStudyAttendance> attendance = new ArrayList<>();
    private final AtomicLong seq = new AtomicLong(100);

    /** 테스트용 가변 Clock. */
    static final class MutableClock extends Clock {
        private Instant instant;
        MutableClock(LocalDateTime at) { this.instant = at.atZone(SEOUL).toInstant(); }
        void set(LocalDateTime at) { this.instant = at.atZone(SEOUL).toInstant(); }
        void advanceSeconds(long s) { this.instant = instant.plusSeconds(s); }
        @Override public ZoneId getZone() { return SEOUL; }
        @Override public Clock withZone(ZoneId zone) { return this; }
        @Override public Instant instant() { return instant; }
    }

    @BeforeEach
    void setUp() {
        clock = new MutableClock(LocalDateTime.of(2026, 9, 30, 10, 0, 0));
        User user = User.builder().id(USER).displayName("u").build();
        GroupStudy group = GroupStudy.builder().id(GROUP).leader(user).startDate(LocalDate.of(2026, 9, 1)).build();

        UserRepository users = mock(UserRepository.class);
        when(users.findById(USER)).thenReturn(Optional.of(user));
        when(users.findByIdForUpdate(USER)).thenReturn(Optional.of(user));

        GroupStudyRepository groups = mock(GroupStudyRepository.class);
        when(groups.findById(GROUP)).thenReturn(Optional.of(group));
        when(groups.findById(OTHER_GROUP)).thenReturn(Optional.of(GroupStudy.builder().id(OTHER_GROUP).leader(user).build()));

        GroupStudyMemberRepository members = mock(GroupStudyMemberRepository.class);
        when(members.existsByGroupStudyIdAndUserIdAndStatus(eq(GROUP), eq(USER), eq(GroupStudyMemberStatus.JOINED))).thenReturn(true);
        when(members.existsByGroupStudyIdAndUserIdAndStatus(eq(OTHER_GROUP), eq(USER), eq(GroupStudyMemberStatus.JOINED))).thenReturn(true);

        GroupStudyAttendanceRepository att = mock(GroupStudyAttendanceRepository.class);
        when(att.findByGroupStudyIdAndUserIdAndDate(anyLong(), anyLong(), any())).thenAnswer(inv -> attendance.stream()
                .filter(a -> a.getGroupStudy().getId().equals(inv.getArgument(0)) && a.getUser().getId().equals(inv.getArgument(1)) && a.getDate().equals(inv.getArgument(2)))
                .findFirst());
        when(att.save(any(GroupStudyAttendance.class))).thenAnswer(inv -> {
            GroupStudyAttendance a = inv.getArgument(0);
            if (a.getId() == null) { a.setId(seq.incrementAndGet()); attendance.add(a); }
            return a;
        });

        TimerRepository repo = mock(TimerRepository.class);
        when(repo.save(any(Timer.class))).thenAnswer(inv -> {
            Timer t = inv.getArgument(0);
            if (t.getId() == null) t.setId(seq.incrementAndGet());
            timers.put(t.getId(), t);
            return t;
        });
        when(repo.saveAndFlush(any(Timer.class))).thenAnswer(inv -> repo.save(inv.getArgument(0)));
        when(repo.findByUserIdAndStatusForUpdate(eq(USER), eq(TimerStatus.STARTED))).thenAnswer(inv -> active());
        when(repo.findByUserIdAndStatus(eq(USER), eq(TimerStatus.STARTED))).thenAnswer(inv -> active());
        when(repo.findByIdForUpdate(anyLong())).thenAnswer(inv -> Optional.ofNullable(timers.get((Long) inv.getArgument(0))));
        when(repo.findFirstByUserIdOrderByStartTimeDesc(USER)).thenAnswer(inv -> timers.values().stream().max(Comparator.comparing(Timer::getStartTime)));
        when(repo.findHeartbeatTimedOutIds(any())).thenAnswer(inv -> timers.values().stream()
                .filter(t -> t.getStatus() == TimerStatus.STARTED && t.getLastHeartbeatAt() != null && t.getLastHeartbeatAt().isBefore(inv.getArgument(0)))
                .map(Timer::getId).toList());
        when(repo.findStaleWithoutHeartbeatIds(any())).thenAnswer(inv -> timers.values().stream()
                .filter(t -> t.getStatus() == TimerStatus.STARTED && t.getLastHeartbeatAt() == null && t.getStartTime().isBefore(inv.getArgument(0)))
                .map(Timer::getId).toList());

        AttendanceLedger ledger = new AttendanceLedger(att, members, groups, users);
        service = new TimerService(repo, users, ledger, clock);
    }

    private Optional<Timer> active() {
        return timers.values().stream().filter(t -> t.getStatus() == TimerStatus.STARTED).findFirst();
    }

    private long activeCount() {
        return timers.values().stream().filter(t -> t.getStatus() == TimerStatus.STARTED).count();
    }

    private TimerDTO.StartRequest groupStart(boolean heartbeat) {
        return TimerDTO.StartRequest.builder().groupStudyId(GROUP).supportsHeartbeat(heartbeat).build();
    }

    private long attendanceSeconds(LocalDate date) {
        return attendance.stream().filter(a -> a.getDate().equals(date)).mapToLong(GroupStudyAttendance::getStudyDurationSeconds).sum();
    }

    // T1 정상 START → STOP: duration 은 서버 시각 차이, 클라이언트 duration 은 무시
    @Test
    void t1_startStop_durationFromServerClock() {
        TimerDTO.Response started = service.startTimer(USER, groupStart(true));
        assertEquals(TimerStatus.STARTED, started.getStatus());
        assertEquals(LocalDateTime.of(2026, 9, 30, 10, 0), started.getStartTime());
        assertEquals(1, attendance.size()); // check-in 행(0초)
        assertEquals(0L, attendanceSeconds(LocalDate.of(2026, 9, 30)));

        clock.advanceSeconds(125);
        TimerDTO.Response ended = service.endTimer(USER, TimerDTO.EndRequest.builder().durationSeconds(999999L).build());
        assertEquals(TimerStatus.COMPLETED, ended.getStatus());
        assertEquals(125L, ended.getDurationSeconds());
        assertEquals(TimerEndReason.USER_STOP, ended.getEndReason());
        assertEquals(125L, attendanceSeconds(LocalDate.of(2026, 9, 30)));
        assertNotNull(attendance.get(0).getCheckOutTime());
    }

    // T2 STOP 두 번: 두 번째는 기존 결과 반환, 크레딧 중복 없음
    @Test
    void t2_doubleStop_isIdempotent() {
        service.startTimer(USER, groupStart(true));
        clock.advanceSeconds(60);
        TimerDTO.Response first = service.endTimer(USER, null);
        clock.advanceSeconds(60);
        TimerDTO.Response second = service.endTimer(USER, null);
        assertEquals(first.getId(), second.getId());
        assertEquals(60L, second.getDurationSeconds());
        assertEquals(60L, attendanceSeconds(LocalDate.of(2026, 9, 30)));
    }

    // T3 START 두 번(같은 컨텍스트): 활성 세션 1개, 두 번째는 resumed
    @Test
    void t3_doubleStart_sameContext_noDuplicateActive() {
        TimerDTO.Response a = service.startTimer(USER, groupStart(true));
        clock.advanceSeconds(30);
        TimerDTO.Response b = service.startTimer(USER, groupStart(true));
        assertEquals(a.getId(), b.getId());
        assertTrue(b.getResumed());
        assertFalse(a.getResumed());
        assertEquals(1, activeCount());
        // 다른 컨텍스트(다른 그룹)로 START → 기존 세션 NEW_SESSION 으로 종료 후 새 세션
        TimerDTO.Response c = service.startTimer(USER, TimerDTO.StartRequest.builder().groupStudyId(OTHER_GROUP).supportsHeartbeat(true).build());
        assertNotEquals(a.getId(), c.getId());
        assertEquals(1, activeCount());
        assertEquals(TimerStatus.COMPLETED, timers.get(a.getId()).getStatus());
        assertEquals(TimerEndReason.NEW_SESSION, timers.get(a.getId()).getEndReason());
        assertEquals(30L, timers.get(a.getId()).getDurationSeconds());
    }

    // T4 heartbeat: lastHeartbeatAt 전진 + 진행분이 출석 원장에 즉시 크레딧
    @Test
    void t4_heartbeat_updatesLastActive_andCreditsProgress() {
        service.startTimer(USER, groupStart(true));
        clock.advanceSeconds(30);
        TimerDTO.Response hb1 = service.heartbeat(USER);
        assertEquals(LocalDateTime.of(2026, 9, 30, 10, 0, 30), hb1.getLastHeartbeatAt());
        assertEquals(30L, attendanceSeconds(LocalDate.of(2026, 9, 30)));
        clock.advanceSeconds(30);
        service.heartbeat(USER);
        assertEquals(60L, attendanceSeconds(LocalDate.of(2026, 9, 30)));
        assertEquals(LocalDateTime.of(2026, 9, 30, 10, 1, 0), attendance.get(0).getLastActiveAt());
        // 활성 세션 없으면 null
        service.endTimer(USER, null);
        assertNull(service.heartbeat(USER));
    }

    // T5 비정상 종료: heartbeat 가 끊기면 reaper 가 마지막 heartbeat 시각으로 종료(손실 ≤ heartbeat 간격)
    @Test
    void t5_abnormalTermination_fallbackToLastHeartbeat() {
        service.startTimer(USER, groupStart(true));
        clock.advanceSeconds(30); service.heartbeat(USER);
        clock.advanceSeconds(30); service.heartbeat(USER);
        // 이후 브라우저 강제 종료 → heartbeat 없음. 60초 뒤(총 90초 미만)는 아직 살아있다고 본다.
        clock.advanceSeconds(60);
        assertTrue(service.findHeartbeatTimedOutIds().isEmpty());
        clock.advanceSeconds(31); // 마지막 heartbeat 로부터 91초
        List<Long> ids = service.findHeartbeatTimedOutIds();
        assertEquals(1, ids.size());
        assertTrue(service.expireTimedOut(ids.get(0)));
        Timer t = timers.get(ids.get(0));
        assertEquals(TimerStatus.COMPLETED, t.getStatus());
        assertEquals(TimerEndReason.HEARTBEAT_TIMEOUT, t.getEndReason());
        assertEquals(LocalDateTime.of(2026, 9, 30, 10, 1, 0), t.getEndTime());
        assertEquals(60L, t.getDurationSeconds());
        assertEquals(60L, attendanceSeconds(LocalDate.of(2026, 9, 30)));
        // 재호출은 no-op
        assertFalse(service.expireTimedOut(ids.get(0)));
    }

    // T6 종료되지 않은 세션 recovery: heartbeat 미지원 좀비(24h+)는 CANCELLED, 공부시간은 기록하지 않음(추정 금지)
    @Test
    void t6_staleSessionWithoutHeartbeat_isCancelledNotEstimated() {
        service.startTimer(USER, groupStart(false)); // 구 클라이언트
        clock.advanceSeconds(3600);
        assertTrue(service.findHeartbeatTimedOutIds().isEmpty()); // heartbeat 미지원은 timeout 대상 아님
        assertTrue(service.findStaleWithoutHeartbeatIds().isEmpty());
        clock.set(LocalDateTime.of(2026, 10, 2, 10, 0, 1));
        List<Long> stale = service.findStaleWithoutHeartbeatIds();
        assertEquals(1, stale.size());
        assertTrue(service.cancelStaleWithoutHeartbeat(stale.get(0)));
        Timer t = timers.get(stale.get(0));
        assertEquals(TimerStatus.CANCELLED, t.getStatus());
        assertEquals(TimerEndReason.STALE_NO_HEARTBEAT, t.getEndReason());
        assertNull(t.getDurationSeconds());
        assertEquals(0L, attendanceSeconds(LocalDate.of(2026, 9, 30)));
        // 좀비가 정리되면 새 세션을 정상 시작할 수 있다
        assertEquals(TimerStatus.STARTED, service.startTimer(USER, groupStart(true)).getStatus());
    }

    // T7 음수 duration 없음: 클럭이 뒤로 가도(NTP 보정 등) 크레딧/기간이 음수가 되지 않는다
    @Test
    void t7_noNegativeDuration_whenClockGoesBackwards() {
        service.startTimer(USER, groupStart(true));
        clock.advanceSeconds(40); service.heartbeat(USER);
        clock.set(LocalDateTime.of(2026, 9, 30, 10, 0, 10)); // 뒤로 30초
        TimerDTO.Response hb = service.heartbeat(USER);
        assertEquals(LocalDateTime.of(2026, 9, 30, 10, 0, 40), hb.getLastHeartbeatAt()); // 전진하지 않음
        TimerDTO.Response ended = service.endTimer(USER, null);
        assertEquals(40L, ended.getDurationSeconds());
        assertEquals(40L, attendanceSeconds(LocalDate.of(2026, 9, 30)));
        assertTrue(ended.getDurationSeconds() >= 0);
    }

    // T8 자정을 넘는 세션: 날짜별로 분할 크레딧(23:50~00:20 → 9/30 10분 + 10/1 20분)
    @Test
    void t8_midnightCrossing_splitsPerDate() {
        clock.set(LocalDateTime.of(2026, 9, 30, 23, 50, 0));
        service.startTimer(USER, groupStart(true));
        clock.set(LocalDateTime.of(2026, 10, 1, 0, 5, 0));
        service.heartbeat(USER);
        clock.set(LocalDateTime.of(2026, 10, 1, 0, 20, 0));
        TimerDTO.Response ended = service.endTimer(USER, null);
        assertEquals(1800L, ended.getDurationSeconds());
        assertEquals(600L, attendanceSeconds(LocalDate.of(2026, 9, 30)));
        assertEquals(1200L, attendanceSeconds(LocalDate.of(2026, 10, 1)));
        assertEquals(2, attendance.size());
        GroupStudyAttendance oct1 = attendance.stream().filter(a -> a.getDate().equals(LocalDate.of(2026, 10, 1))).findFirst().orElseThrow();
        assertEquals(LocalDateTime.of(2026, 10, 1, 0, 0), oct1.getCheckInTime());
    }

    // 비멤버의 그룹 세션 시작은 403
    @Test
    void nonMember_cannotStartGroupSession() {
        assertThrows(SecurityException.class, () -> service.startTimer(USER,
                TimerDTO.StartRequest.builder().groupStudyId(99L).supportsHeartbeat(true).build()));
        assertEquals(0, activeCount());
    }

    // 개인 타이머(그룹 없음)는 출석 원장을 건드리지 않는다
    @Test
    void personalTimer_doesNotTouchAttendance() {
        service.startTimer(USER, TimerDTO.StartRequest.builder().supportsHeartbeat(true).build());
        clock.advanceSeconds(90);
        service.heartbeat(USER);
        service.endTimer(USER, null);
        assertTrue(attendance.isEmpty());
    }

    @Test
    void intervalSplitter_basicCases() {
        assertTrue(StudyIntervalSplitter.split(LocalDateTime.of(2026, 9, 30, 10, 0), LocalDateTime.of(2026, 9, 30, 10, 0)).isEmpty());
        var segs = StudyIntervalSplitter.split(LocalDateTime.of(2026, 9, 29, 23, 0), LocalDateTime.of(2026, 10, 1, 1, 0));
        assertEquals(3, segs.size());
        assertEquals(3600L, segs.get(0).seconds());
        assertEquals(86400L, segs.get(1).seconds());
        assertEquals(3600L, segs.get(2).seconds());
        assertEquals(ZoneOffset.UTC.getTotalSeconds(), 0); // 분할은 타임존 산술을 쓰지 않는다(LocalDateTime 전용)
    }
}
