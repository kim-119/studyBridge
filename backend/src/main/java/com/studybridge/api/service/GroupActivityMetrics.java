package com.studybridge.api.service;

import java.time.LocalDate;
import java.util.Collection;

/**
 * 그룹 카드 활동 지표(출석률·평균 공부시간)의 결정적 계산. AI/임의 숫자 없음.
 *
 * <p>정의(최근 {@link GroupStudySettingsPolicy#ACTIVITY_WINDOW_DAYS}일, 오늘 포함):</p>
 * <ul>
 *   <li>출석 = 해당 날짜에 그룹 공부 세션이 1회 이상 → group_study_attendances 행(PRESENT). 서버가 세션 구간을 날짜별로 크레딧.</li>
 *   <li>멤버별 대상 일수 = max(창 시작, 그룹 시작일, 멤버 가입일) ~ 오늘 의 일수. 최근 가입자는 가입일부터만 센다.
 *       탈퇴자는 멤버 행이 삭제되므로(이력 없음) 분모·분자 모두에서 제외한다.</li>
 *   <li>attendanceRate = Σ출석(멤버·일) / Σ대상(멤버·일) × 100, 소수 1자리, 0~100 클램프.</li>
 *   <li>avgStudySeconds = 창 안 공부시간 합(초) / Σ대상(멤버·일) → "멤버 1인·1일 평균 공부시간"(avgDailyStudySecondsPerMember).</li>
 * </ul>
 * 기록이 전혀 없거나 분모가 0이면 둘 다 0 이다.
 */
public record GroupActivityMetrics(double attendanceRate, long avgStudySeconds, int windowDays,
                                   long attendedMemberDays, long eligibleMemberDays) {

    public static final GroupActivityMetrics EMPTY = new GroupActivityMetrics(0.0, 0L, GroupStudySettingsPolicy.ACTIVITY_WINDOW_DAYS, 0L, 0L);

    public static LocalDate windowStart(LocalDate today) {
        return today.minusDays(GroupStudySettingsPolicy.ACTIVITY_WINDOW_DAYS - 1L);
    }

    /** [periodStart, periodEnd] 안에서 한 멤버가 출석 대상이 되는 일수(inclusive). 그룹 시작 전/가입 전/미래는 제외. */
    public static int eligibleDays(LocalDate periodStart, LocalDate periodEnd, LocalDate groupStartDate, LocalDate joinedDate) {
        LocalDate from = periodStart;
        if (groupStartDate != null && groupStartDate.isAfter(from)) from = groupStartDate;
        if (joinedDate != null && joinedDate.isAfter(from)) from = joinedDate;
        if (from.isAfter(periodEnd)) return 0;
        return (int) (periodEnd.toEpochDay() - from.toEpochDay()) + 1;
    }

    /** (하위 호환) 창 안에서 그룹 자체가 대상이 되는 일수. */
    public static int eligibleDays(LocalDate today, LocalDate startDate) {
        return eligibleDays(windowStart(today), today, startDate, null);
    }

    public static long sumEligibleMemberDays(LocalDate periodStart, LocalDate periodEnd, LocalDate groupStartDate,
                                             Collection<LocalDate> memberJoinedDates) {
        long sum = 0L;
        if (memberJoinedDates == null) return 0L;
        for (LocalDate joined : memberJoinedDates) {
            sum += eligibleDays(periodStart, periodEnd, groupStartDate, joined);
        }
        return sum;
    }

    public static GroupActivityMetrics compute(LocalDate today, LocalDate groupStartDate, Collection<LocalDate> memberJoinedDates,
                                               long attendanceRows, long totalStudySeconds) {
        long denominator = sumEligibleMemberDays(windowStart(today), today, groupStartDate, memberJoinedDates);
        return fromCounts(attendanceRows, totalStudySeconds, denominator, GroupStudySettingsPolicy.ACTIVITY_WINDOW_DAYS);
    }

    public static GroupActivityMetrics fromCounts(long attendedMemberDays, long totalStudySeconds, long eligibleMemberDays, int windowDays) {
        if (eligibleMemberDays <= 0) {
            return new GroupActivityMetrics(0.0, 0L, windowDays, 0L, 0L);
        }
        double rate = Math.min(100.0, Math.max(0.0, attendedMemberDays * 100.0 / eligibleMemberDays));
        double rounded = Math.round(rate * 10.0) / 10.0;
        long avg = Math.max(0L, totalStudySeconds) / eligibleMemberDays;
        return new GroupActivityMetrics(rounded, avg, windowDays, Math.min(attendedMemberDays, eligibleMemberDays), eligibleMemberDays);
    }
}
