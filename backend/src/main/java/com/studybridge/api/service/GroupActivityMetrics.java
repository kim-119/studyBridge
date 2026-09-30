package com.studybridge.api.service;

import java.time.LocalDate;

/**
 * 그룹 카드 활동 지표(출석률·평균 공부시간)의 결정적 계산. AI/임의 숫자 없음.
 *
 * <p>정의(최근 {@link GroupStudySettingsPolicy#ACTIVITY_WINDOW_DAYS}일, 오늘 포함):</p>
 * <ul>
 *   <li>출석 = 해당 날짜에 그룹 연동 공부 세션(타이머)이 1회 이상 → group_study_attendances 행(PRESENT). 기존 데이터 재사용.</li>
 *   <li>대상 일수 = 창 안에서 그룹 시작일(startDate) 이후의 날짜 수. 시작 전 그룹은 0.</li>
 *   <li>attendanceRate = 출석 행 수 / (현재 인원 × 대상 일수) × 100, 소수 1자리, 0~100 클램프.</li>
 *   <li>avgStudySeconds = 창 안 공부시간 합(초) / (현재 인원 × 대상 일수) → "그룹원 1인·1일 평균 공부시간".</li>
 * </ul>
 * 기록이 전혀 없거나 분모가 0이면 둘 다 0 이다.
 */
public record GroupActivityMetrics(double attendanceRate, long avgStudySeconds, int windowDays) {

    public static final GroupActivityMetrics EMPTY = new GroupActivityMetrics(0.0, 0L, GroupStudySettingsPolicy.ACTIVITY_WINDOW_DAYS);

    public static LocalDate windowStart(LocalDate today) {
        return today.minusDays(GroupStudySettingsPolicy.ACTIVITY_WINDOW_DAYS - 1L);
    }

    /** 창 안에서 실제로 출석 대상이 되는 일수: max(startDate, windowStart) ~ today. */
    public static int eligibleDays(LocalDate today, LocalDate startDate) {
        LocalDate from = windowStart(today);
        if (startDate != null && startDate.isAfter(from)) {
            from = startDate;
        }
        if (from.isAfter(today)) {
            return 0;
        }
        return (int) (today.toEpochDay() - from.toEpochDay()) + 1;
    }

    public static GroupActivityMetrics compute(LocalDate today, LocalDate startDate, Integer memberCount,
                                               long attendanceRows, long totalStudySeconds) {
        int days = eligibleDays(today, startDate);
        int members = memberCount == null ? 0 : memberCount;
        long denominator = (long) days * members;
        if (denominator <= 0) {
            return EMPTY;
        }
        double rate = Math.min(100.0, Math.max(0.0, attendanceRows * 100.0 / denominator));
        double rounded = Math.round(rate * 10.0) / 10.0;
        long avg = Math.max(0L, totalStudySeconds) / denominator;
        return new GroupActivityMetrics(rounded, avg, GroupStudySettingsPolicy.ACTIVITY_WINDOW_DAYS);
    }
}
