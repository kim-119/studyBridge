package com.studybridge.api.service;

import com.studybridge.api.dto.GroupStudyStatsDTO;
import com.studybridge.api.dto.GroupStudyStatsDTO.DaySummary;
import com.studybridge.api.dto.GroupStudyStatsDTO.MemberAttendance;
import com.studybridge.api.dto.GroupStudyStatsDTO.Range;
import com.studybridge.api.entity.GroupStudy;
import com.studybridge.api.entity.GroupStudyAttendance;
import com.studybridge.api.entity.GroupStudyMember;
import com.studybridge.api.entity.GroupStudyMemberStatus;
import com.studybridge.api.entity.Timer;
import com.studybridge.api.entity.TimerStatus;
import com.studybridge.api.dto.GroupStudyStatsDTO.QuizRankingMember;
import com.studybridge.api.dto.GroupStudyStatsDTO.StudyTimeMember;
import com.studybridge.api.entity.GroupStudyQuizSessionStatus;
import com.studybridge.api.repository.GroupStudyAttendanceRepository;
import com.studybridge.api.repository.GroupStudyMemberRepository;
import com.studybridge.api.repository.GroupStudyQuizSessionAnswerRepository;
import com.studybridge.api.repository.GroupStudyRepository;
import com.studybridge.api.repository.TimerRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Clock;
import java.time.DayOfWeek;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.YearMonth;
import java.time.temporal.TemporalAdjusters;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.NoSuchElementException;
import java.util.Objects;
import java.util.function.ToLongFunction;
import java.util.stream.Collectors;

/**
 * 그룹 출석부 / 개인 공부 통계(DAY·WEEK·MONTH). 원천 = timers(세션, 서버 시각) + group_study_attendances(체크인 사실).
 * 요청당 쿼리 4개(그룹, 멤버+사용자 fetch join, 기간 세션, 기간 출석행) — 날짜/멤버 수와 무관(N+1 없음).
 * 권한: 그룹 멤버만(비공개/공개 무관) — 비멤버는 403. 개인 통계는 /me 만 제공(타인 userId 파라미터 없음).
 */
@Service
@RequiredArgsConstructor
@Slf4j
@Transactional(readOnly = true)
public class GroupStudyStatsService {

    private final GroupStudyRepository groupStudyRepository;
    private final GroupStudyMemberRepository memberRepository;
    private final TimerRepository timerRepository;
    private final GroupStudyAttendanceRepository attendanceRepository;
    private final GroupStudyQuizSessionAnswerRepository quizAnswerRepository;
    private final Clock clock;

    // ── 기간 ──────────────────────────────────────────────────────────────────

    public record Period(Range range, LocalDate start, LocalDate end) {
        LocalDateTime startDateTime() { return start.atStartOfDay(); }
        LocalDateTime endExclusive() { return end.plusDays(1).atStartOfDay(); }
        List<LocalDate> dates() {
            List<LocalDate> out = new ArrayList<>();
            for (LocalDate d = start; !d.isAfter(end); d = d.plusDays(1)) out.add(d);
            return out;
        }
    }

    /** range/date/month 파라미터 → 기간. WEEK 은 월~일, MONTH 는 달력 월. 잘못된 값은 400. ALL 은 허용하지 않는다(랭킹 전용). */
    public Period resolvePeriod(String rangeParam, LocalDate date, String month) {
        return resolvePeriod(rangeParam, date, month, Range.WEEK, false);
    }

    /** 학습시간 랭킹용: 기본 ALL(그룹 전체 기간), DAY/WEEK/MONTH 도 허용. */
    public Period resolveRankingPeriod(String rangeParam, LocalDate date, String month) {
        return resolvePeriod(rangeParam, date, month, Range.ALL, true);
    }

    private Period resolvePeriod(String rangeParam, LocalDate date, String month, Range defaultRange, boolean allowAll) {
        Range range;
        try {
            range = rangeParam == null || rangeParam.isBlank() ? defaultRange : Range.valueOf(rangeParam.trim().toUpperCase());
        } catch (IllegalArgumentException e) {
            throw new IllegalArgumentException(allowAll ? "range 는 ALL, DAY, WEEK, MONTH 중 하나여야 합니다."
                    : "range 는 DAY, WEEK, MONTH 중 하나여야 합니다.");
        }
        if (range == Range.ALL) {
            if (!allowAll) {
                throw new IllegalArgumentException("range 는 DAY, WEEK, MONTH 중 하나여야 합니다.");
            }
            // 전체 기간: 서비스 개시 이전(1970)부터 오늘까지. dates() 는 랭킹에서 호출하지 않는다.
            return new Period(range, LocalDate.of(1970, 1, 1), LocalDate.now(clock));
        }
        LocalDate anchor = date != null ? date : LocalDate.now(clock);
        if (range == Range.MONTH && month != null && !month.isBlank()) {
            try {
                anchor = YearMonth.parse(month.trim()).atDay(1);
            } catch (Exception e) {
                throw new IllegalArgumentException("month 는 YYYY-MM 형식이어야 합니다.");
            }
        }
        return switch (range) {
            case DAY -> new Period(range, anchor, anchor);
            case WEEK -> new Period(range, anchor.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY)),
                    anchor.with(TemporalAdjusters.nextOrSame(DayOfWeek.SUNDAY)));
            case MONTH -> new Period(range, YearMonth.from(anchor).atDay(1), YearMonth.from(anchor).atEndOfMonth());
            case ALL -> throw new IllegalArgumentException("range 는 DAY, WEEK, MONTH 중 하나여야 합니다.");
        };
    }

    // ── 집계 코어 ──────────────────────────────────────────────────────────────

    /** (userId, date) 단위 누적기. */
    static final class DayAcc {
        long total;
        long maxFocus;
        LocalDateTime first;
        LocalDateTime last;
        int sessions;
        boolean checkedIn;

        void add(StudyIntervalSplitter.DaySegment seg) {
            long secs = seg.seconds();
            total += secs;
            maxFocus = Math.max(maxFocus, secs);
            if (first == null || seg.start().isBefore(first)) first = seg.start();
            if (last == null || seg.end().isAfter(last)) last = seg.end();
            sessions++;
        }

        boolean attended() { return total > 0 || sessions > 0 || checkedIn; }
    }

    private record Snapshot(GroupStudy group, List<GroupStudyMember> members, Period period, LocalDate today,
                            Map<Long, Map<LocalDate, DayAcc>> byUser) {
        long targetSeconds() {
            Integer m = group.getTargetStudyMinutes();
            return (m != null ? m : GroupStudySettingsPolicy.TARGET_STUDY_MINUTES_DEFAULT) * 60L;
        }
    }

    private Snapshot load(Long groupId, Long requesterId, Period period) {
        GroupStudy group = groupStudyRepository.findById(groupId)
                .orElseThrow(() -> new NoSuchElementException("Group study not found with ID: " + groupId));
        List<GroupStudyMember> members = requireMember(groupId, requesterId);
        List<Long> userIds = members.stream().map(m -> m.getUser().getId()).collect(Collectors.toList());
        LocalDateTime now = LocalDateTime.now(clock);
        LocalDate today = now.toLocalDate();

        Map<Long, Map<LocalDate, DayAcc>> byUser = new HashMap<>();
        for (Long uid : userIds) byUser.put(uid, new HashMap<>());

        List<Timer> sessions = timerRepository.findGroupSessionsOverlapping(groupId, userIds, period.startDateTime(), period.endExclusive());
        for (Timer t : sessions) {
            LocalDateTime end = effectiveEnd(t, now);
            if (end == null) continue; // heartbeat 미지원 진행 중 세션: 생존 여부 불명 → 종료될 때까지 제외
            Map<LocalDate, DayAcc> perDay = byUser.get(t.getUser().getId());
            if (perDay == null) continue;
            for (StudyIntervalSplitter.DaySegment seg : StudyIntervalSplitter.splitWithin(t.getStartTime(), end, period.startDateTime(), period.endExclusive())) {
                perDay.computeIfAbsent(seg.date(), d -> new DayAcc()).add(seg);
            }
        }
        for (GroupStudyAttendance a : attendanceRepository.findByGroupStudyIdAndDateBetween(groupId, period.start(), period.end())) {
            Map<LocalDate, DayAcc> perDay = byUser.get(a.getUser().getId());
            if (perDay == null) continue; // 탈퇴자 행은 제외
            perDay.computeIfAbsent(a.getDate(), d -> new DayAcc()).checkedIn = true;
        }
        return new Snapshot(group, members, period, today, byUser);
    }

    /** 세션의 유효 종료 시각: 완료 → endTime, 진행 중 → 마지막 heartbeat(없으면 null), 미래 값은 now 로 클램프. */
    static LocalDateTime effectiveEnd(Timer t, LocalDateTime now) {
        LocalDateTime end;
        if (t.getStatus() == TimerStatus.COMPLETED) {
            end = t.getEndTime();
        } else if (t.getStatus() == TimerStatus.STARTED) {
            end = t.getLastHeartbeatAt();
        } else {
            return null;
        }
        if (end == null) return null;
        return end.isAfter(now) ? now : end;
    }

    private static double pct(long num, long den, int scale) {
        if (den <= 0) return 0.0;
        double factor = Math.pow(10, scale);
        return Math.round(num * 100.0 / den * factor) / factor;
    }

    private List<DaySummary> daySummaries(Snapshot s, Long userId) {
        Map<LocalDate, DayAcc> perDay = s.byUser().getOrDefault(userId, Map.of());
        long target = s.targetSeconds();
        List<DaySummary> out = new ArrayList<>();
        for (LocalDate d : s.period().dates()) {
            DayAcc acc = perDay.get(d);
            if (acc == null) {
                out.add(DaySummary.builder().date(d).totalStudySeconds(0L).maxFocusSeconds(0L).sessionCount(0)
                        .attended(false).achievementRate(0.0).build());
                continue;
            }
            out.add(DaySummary.builder()
                    .date(d)
                    .totalStudySeconds(acc.total)
                    .maxFocusSeconds(acc.maxFocus)
                    .firstStartedAt(acc.first != null ? acc.first.toLocalTime() : null)
                    .lastEndedAt(acc.last != null ? acc.last.toLocalTime() : null)
                    .sessionCount(acc.sessions)
                    .attended(acc.attended())
                    .achievementRate(pct(acc.total, target, 2))
                    .build());
        }
        return out;
    }

    private int eligibleDaysFor(Snapshot s, GroupStudyMember m) {
        LocalDate periodEnd = s.period().end().isAfter(s.today()) ? s.today() : s.period().end();
        LocalDate joined = m.getJoinedAt() != null ? m.getJoinedAt().toLocalDate() : null;
        return GroupActivityMetrics.eligibleDays(s.period().start(), periodEnd, s.group().getStartDate(), joined);
    }

    // ── 개인 통계 ──────────────────────────────────────────────────────────────

    public GroupStudyStatsDTO.MyStudyStats getMyStats(Long userId, Long groupId, Period period) {
        Snapshot s = load(groupId, userId, period);
        GroupStudyMember me = s.members().stream().filter(m -> m.getUser().getId().equals(userId)).findFirst().orElseThrow();
        List<DaySummary> days = daySummaries(s, userId);

        long total = days.stream().mapToLong(DaySummary::getTotalStudySeconds).sum();
        long maxFocus = days.stream().mapToLong(DaySummary::getMaxFocusSeconds).max().orElse(0L);
        int sessionCount = days.stream().mapToInt(DaySummary::getSessionCount).sum();
        int attendanceDays = (int) days.stream().filter(d -> Boolean.TRUE.equals(d.getAttended())).count();
        int eligibleDays = eligibleDaysFor(s, me);
        long target = s.targetSeconds();
        long avgDaily = eligibleDays > 0 ? total / eligibleDays : 0L;

        GroupStudyStatsDTO.MyStudyStats.MyStudyStatsBuilder b = GroupStudyStatsDTO.MyStudyStats.builder()
                .range(period.range())
                .groupId(groupId)
                .periodStart(period.start())
                .periodEnd(period.end())
                .totalStudySeconds(total)
                .maxFocusSeconds(maxFocus)
                .sessionCount(sessionCount)
                .targetStudySeconds(target)
                .averageDailyStudySeconds(avgDaily)
                .attendanceDays(attendanceDays)
                .eligibleDays(eligibleDays)
                .attendanceRate(pct(attendanceDays, eligibleDays, 1))
                .days(days);

        if (period.range() == Range.DAY) {
            DaySummary d = days.get(0);
            b.date(period.start())
             .firstStartedAt(d.getFirstStartedAt())
             .lastEndedAt(d.getLastEndedAt())
             .achievementRate(pct(total, target, 2));
        } else {
            b.achievementRate(pct(avgDaily, target, 2));
        }
        return b.build();
    }

    // ── 출석부 ────────────────────────────────────────────────────────────────

    public GroupStudyStatsDTO.AttendanceBoard getAttendanceBoard(Long userId, Long groupId, Period period) {
        Snapshot s = load(groupId, userId, period);

        List<MemberAttendance> rows = new ArrayList<>();
        long totalAttendance = 0L;
        long totalEligible = 0L;
        long totalStudy = 0L;
        for (GroupStudyMember m : s.members()) {
            Long uid = m.getUser().getId();
            List<DaySummary> days = daySummaries(s, uid);
            long study = days.stream().mapToLong(DaySummary::getTotalStudySeconds).sum();
            int attended = (int) days.stream().filter(d -> Boolean.TRUE.equals(d.getAttended())).count();
            int eligible = eligibleDaysFor(s, m);
            totalAttendance += Math.min(attended, eligible);
            totalEligible += eligible;
            totalStudy += study;
            rows.add(MemberAttendance.builder()
                    .userId(uid)
                    .memberId(m.getId())
                    .nickname(m.getNickname() != null && !m.getNickname().isBlank() ? m.getNickname() : m.getUser().getDisplayName())
                    .photoUrl(m.getUser().getPhotoUrl())
                    .role(m.getRole() != null ? m.getRole().name() : null)
                    .studySeconds(study)
                    .attendanceDays(attended)
                    .eligibleDays(eligible)
                    .attendanceRate(pct(attended, eligible, 1))
                    .days(days)
                    .build());
        }
        assignCompetitionRank(rows);

        MemberAttendance my = rows.stream().filter(r -> r.getUserId().equals(userId)).findFirst().orElse(null);
        return GroupStudyStatsDTO.AttendanceBoard.builder()
                .range(period.range())
                .groupId(groupId)
                .periodStart(period.start())
                .periodEnd(period.end())
                .targetStudySeconds(s.targetSeconds())
                .memberCount(rows.size())
                .totalAttendanceDays(totalAttendance)
                .totalEligibleDays(totalEligible)
                .attendanceRate(pct(totalAttendance, totalEligible, 1))
                .totalStudySeconds(totalStudy)
                .my(my)
                .members(rows)
                .build();
    }

    // ── 학습시간 랭킹 ─────────────────────────────────────────────────────────

    /** (userId) 단위 학습시간 누적기. */
    static final class StudyAcc {
        long seconds;
        int sessions;
        boolean activeNow;
    }

    /**
     * GET /stats/study-time — 그룹 멤버별 실제 학습시간 랭킹.
     * 정본 = timers(서버 시각). 완료 세션은 [startTime, endTime), 진행 중 세션은 [startTime, lastHeartbeatAt)(서버 현재시각으로 클램프),
     * CANCELLED/heartbeat 미지원 진행 세션은 제외. 세션 행은 id 로 중복 제거(중복 합산 방지), 역전 구간은 0초.
     * 클라이언트가 보낸 durationSeconds 는 사용하지 않는다. 쿼리 3개(그룹, 멤버+사용자, 그룹 세션) — 멤버 수와 무관.
     */
    public GroupStudyStatsDTO.StudyTimeRanking getStudyTimeRanking(Long userId, Long groupId, Period period) {
        GroupStudy group = groupStudyRepository.findById(groupId)
                .orElseThrow(() -> new NoSuchElementException("Group study not found with ID: " + groupId));
        List<GroupStudyMember> members = requireMember(groupId, userId);
        LocalDateTime now = LocalDateTime.now(clock);

        Map<Long, StudyAcc> byUser = new LinkedHashMap<>();
        for (GroupStudyMember m : members) byUser.put(m.getUser().getId(), new StudyAcc());
        List<Long> userIds = new ArrayList<>(byUser.keySet());

        Map<Long, Timer> distinct = new LinkedHashMap<>(); // 같은 세션이 두 번 오더라도 한 번만 합산
        for (Timer t : timerRepository.findGroupSessionsOverlapping(groupId, userIds, period.startDateTime(), period.endExclusive())) {
            if (t == null || t.getUser() == null) continue;
            distinct.putIfAbsent(t.getId() != null ? t.getId() : (long) System.identityHashCode(t), t);
        }
        for (Timer t : distinct.values()) {
            StudyAcc acc = byUser.get(t.getUser().getId());
            if (acc == null) continue; // 탈퇴/강퇴 사용자 세션 제외
            LocalDateTime end = effectiveEnd(t, now);
            if (end == null) continue;
            long secs = 0L;
            for (StudyIntervalSplitter.DaySegment seg : StudyIntervalSplitter.splitWithin(t.getStartTime(), end, period.startDateTime(), period.endExclusive())) {
                secs += seg.seconds();
            }
            if (secs <= 0L && t.getStatus() != TimerStatus.STARTED) continue; // 0초/역전 완료 세션은 세션 수에도 넣지 않는다
            acc.seconds += secs;
            acc.sessions++;
            if (t.getStatus() == TimerStatus.STARTED) acc.activeNow = true;
        }

        List<StudyTimeMember> rows = new ArrayList<>();
        long total = 0L;
        for (GroupStudyMember m : members) {
            Long uid = m.getUser().getId();
            StudyAcc acc = byUser.get(uid);
            total += acc.seconds;
            rows.add(StudyTimeMember.builder()
                    .userId(uid)
                    .memberId(m.getId())
                    .nickname(displayNameOf(m))
                    .profileImageUrl(m.getUser().getPhotoUrl())
                    .role(m.getRole() != null ? m.getRole().name() : null)
                    .isMe(uid.equals(userId))
                    .studySeconds(acc.seconds)
                    .sessionCount(acc.sessions)
                    .activeNow(acc.activeNow)
                    .build());
        }
        rows.sort(Comparator.comparing(StudyTimeMember::getStudySeconds, Comparator.reverseOrder())
                .thenComparing(r -> r.getNickname() == null ? "" : r.getNickname())
                .thenComparing(StudyTimeMember::getUserId));
        assignCompetitionRank(rows, r -> r.getStudySeconds(), StudyTimeMember::setRank);

        boolean all = period.range() == Range.ALL;
        return GroupStudyStatsDTO.StudyTimeRanking.builder()
                .groupId(groupId)
                .range(period.range())
                .periodStart(all ? null : period.start())
                .periodEnd(all ? null : period.end())
                .generatedAt(now)
                .memberCount(rows.size())
                .totalStudySeconds(total)
                .my(rows.stream().filter(r -> Boolean.TRUE.equals(r.getIsMe())).findFirst().orElse(null))
                .members(rows)
                .build();
    }

    // ── 퀴즈 랭킹 ────────────────────────────────────────────────────────────

    /** (userId) 단위 퀴즈 누적기. */
    static final class QuizAcc {
        int score;
        int correct;
        int totalQuestions;
        int sessions;
    }

    /**
     * GET /stats/quiz-ranking — 그룹 멤버별 퀴즈 누적 랭킹. 정본 = RDS(group_study_quiz_session_answers, 채점 완료 행).
     *  · score = Σ points_awarded (기존 채점 정책: 정답 시 quiz.rewardPoints + 남은 시간 보너스). 새 점수식을 만들지 않는다.
     *  · correctCount = 정답 수, quizParticipationCount = 답안을 1개 이상 제출한 세션 수.
     *  · totalQuestions = 참여한 세션에서 정답 공개까지 진행된 문제 수(완료 세션 = 출제 문제 수, 중단 세션 = 채점된 문제 수 하한).
     *    미제출 문제도 분모에 들어가므로 "아는 것만 답해서 정답률 100%" 가 되지 않는다.
     *  · accuracy = correct / totalQuestions × 100(소수 1자리). 미참여 멤버는 전부 0.
     * 쿼리 4개(그룹, 멤버+사용자, 세션·사용자 집계, 세션별 채점 문제 수) — 멤버/세션 수와 무관. Redis 를 사용하지 않는다
     * (실시간 점수판 캐시와 같은 정의이며, 캐시가 비어도 이 API 는 항상 정본을 돌려준다).
     */
    public GroupStudyStatsDTO.QuizRanking getQuizRanking(Long userId, Long groupId) {
        groupStudyRepository.findById(groupId)
                .orElseThrow(() -> new NoSuchElementException("Group study not found with ID: " + groupId));
        List<GroupStudyMember> members = requireMember(groupId, userId);
        LocalDateTime now = LocalDateTime.now(clock);

        Map<Long, Integer> gradedQuestionsBySession = new HashMap<>();
        for (Object[] row : quizAnswerRepository.countGradedQuestionsBySession(groupId)) {
            gradedQuestionsBySession.put(((Number) row[0]).longValue(), (int) ((Number) row[1]).longValue());
        }

        Map<Long, QuizAcc> byUser = new LinkedHashMap<>();
        for (GroupStudyMember m : members) byUser.put(m.getUser().getId(), new QuizAcc());
        java.util.Set<Long> sessionIds = new java.util.HashSet<>();
        for (Object[] row : quizAnswerRepository.aggregateBySessionAndUser(groupId)) {
            Long sessionId = ((Number) row[0]).longValue();
            GroupStudyQuizSessionStatus status = row[1] instanceof GroupStudyQuizSessionStatus st ? st
                    : row[1] == null ? null : GroupStudyQuizSessionStatus.valueOf(String.valueOf(row[1]));
            String orderJson = row[2] == null ? null : String.valueOf(row[2]);
            Long uid = ((Number) row[3]).longValue();
            int correct = row[5] == null ? 0 : (int) ((Number) row[5]).longValue();
            int points = row[6] == null ? 0 : (int) ((Number) row[6]).longValue();
            sessionIds.add(sessionId);
            QuizAcc acc = byUser.get(uid);
            if (acc == null) continue; // 탈퇴/강퇴 사용자 답안 제외
            int graded = gradedQuestionsBySession.getOrDefault(sessionId, 0);
            int questions = status == GroupStudyQuizSessionStatus.COMPLETED ? Math.max(countQuestions(orderJson), graded) : graded;
            acc.score += points;
            acc.correct += correct;
            acc.totalQuestions += questions;
            acc.sessions++;
        }

        List<QuizRankingMember> rows = new ArrayList<>();
        for (GroupStudyMember m : members) {
            Long uid = m.getUser().getId();
            QuizAcc acc = byUser.get(uid);
            rows.add(QuizRankingMember.builder()
                    .userId(uid)
                    .memberId(m.getId())
                    .nickname(displayNameOf(m))
                    .profileImageUrl(m.getUser().getPhotoUrl())
                    .role(m.getRole() != null ? m.getRole().name() : null)
                    .isMe(uid.equals(userId))
                    .score(acc.score)
                    .correctCount(acc.correct)
                    .totalQuestions(acc.totalQuestions)
                    .accuracy(pct(acc.correct, acc.totalQuestions, 1))
                    .quizParticipationCount(acc.sessions)
                    .build());
        }
        rows.sort(Comparator.comparing(QuizRankingMember::getScore, Comparator.reverseOrder())
                .thenComparing(QuizRankingMember::getAccuracy, Comparator.reverseOrder())
                .thenComparing(QuizRankingMember::getCorrectCount, Comparator.reverseOrder())
                .thenComparing(r -> r.getNickname() == null ? "" : r.getNickname())
                .thenComparing(QuizRankingMember::getUserId));
        int rank = 0;
        QuizRankingMember prev = null;
        for (int i = 0; i < rows.size(); i++) {
            QuizRankingMember r = rows.get(i);
            if (prev == null || !Objects.equals(prev.getScore(), r.getScore()) || !Objects.equals(prev.getAccuracy(), r.getAccuracy())
                    || !Objects.equals(prev.getCorrectCount(), r.getCorrectCount())) {
                rank = i + 1;
                prev = r;
            }
            r.setRank(rank);
        }

        return GroupStudyStatsDTO.QuizRanking.builder()
                .groupId(groupId)
                .generatedAt(now)
                .memberCount(rows.size())
                .sessionCount(sessionIds.size())
                .my(rows.stream().filter(r -> Boolean.TRUE.equals(r.getIsMe())).findFirst().orElse(null))
                .members(rows)
                .build();
    }

    /** questionOrderJson("[1,2,3]") 의 원소 수. 파싱 불가/비어 있으면 0. */
    static int countQuestions(String orderJson) {
        if (orderJson == null) return 0;
        String body = orderJson.trim();
        if (body.length() < 2 || body.charAt(0) != '[') return 0;
        body = body.substring(1, body.length() - 1).trim();
        if (body.isEmpty()) return 0;
        int n = 0;
        for (String part : body.split(",")) {
            if (!part.trim().isEmpty()) n++;
        }
        return n;
    }

    // ── 공통 ─────────────────────────────────────────────────────────────────

    /** 그룹의 JOINED 멤버(+사용자 fetch join)를 돌려주고, 요청자가 멤버가 아니면 403. */
    private List<GroupStudyMember> requireMember(Long groupId, Long requesterId) {
        List<GroupStudyMember> members = memberRepository.findWithUserByGroupStudyIdAndStatus(groupId, GroupStudyMemberStatus.JOINED);
        boolean requesterIsMember = requesterId != null && members.stream().anyMatch(m -> m.getUser().getId().equals(requesterId));
        if (!requesterIsMember) {
            throw new SecurityException("그룹 멤버만 그룹 통계를 조회할 수 있습니다.");
        }
        return members;
    }

    private static String displayNameOf(GroupStudyMember m) {
        if (m.getNickname() != null && !m.getNickname().isBlank()) return m.getNickname();
        return m.getUser().getDisplayName();
    }

    /** competition ranking 공용: 이미 정렬된 rows 에 대해 key 가 같으면 같은 등수, 다음 등수는 건너뜀(1,2,2,4). */
    static <T> void assignCompetitionRank(List<T> rows, ToLongFunction<T> key, java.util.function.ObjIntConsumer<T> setRank) {
        int rank = 0;
        long prev = Long.MIN_VALUE;
        boolean first = true;
        for (int i = 0; i < rows.size(); i++) {
            long v = key.applyAsLong(rows.get(i));
            if (first || v != prev) {
                rank = i + 1;
                prev = v;
                first = false;
            }
            setRank.accept(rows.get(i), rank);
        }
    }

    /** competition ranking: studySeconds DESC, 동률은 같은 등수, 다음 등수는 건너뜀(1,2,2,4). 동률 내 정렬은 이름 오름차순(결정적). */
    static void assignCompetitionRank(List<MemberAttendance> rows) {
        rows.sort(Comparator.comparing(MemberAttendance::getStudySeconds, Comparator.reverseOrder())
                .thenComparing(r -> r.getNickname() == null ? "" : r.getNickname()));
        int rank = 0;
        long prev = -1L;
        for (int i = 0; i < rows.size(); i++) {
            long secs = rows.get(i).getStudySeconds();
            if (secs != prev) {
                rank = i + 1;
                prev = secs;
            }
            rows.get(i).setRank(rank);
        }
    }
}
