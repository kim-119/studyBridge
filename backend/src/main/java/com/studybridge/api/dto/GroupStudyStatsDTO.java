package com.studybridge.api.dto;

import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDate;
import java.time.LocalTime;
import java.util.List;

/**
 * 그룹 출석부/개인 공부 통계 계약(웹·Android 공통). 모든 시간은 서버(Asia/Seoul) 벽시계 기준, 초 단위 정수.
 *  · range: DAY | WEEK(월~일) | MONTH(달력 월)
 *  · 세션은 자정 경계에서 분할되어 날짜별로 집계된다(23:50~00:20 → 10분 + 20분).
 *  · 진행 중 세션은 마지막 heartbeat 시각까지만 포함한다.
 */
public class GroupStudyStatsDTO {

    public enum Range { DAY, WEEK, MONTH }

    /** 날짜 셀(달력/출석부 공용). 기록이 없는 날은 0/false/null. */
    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class DaySummary {
        private LocalDate date;
        private Long totalStudySeconds;   // 그날 공부 세션 합
        private Long maxFocusSeconds;     // 그날 가장 긴 연속 세션(자정 분할 후 구간 기준)
        private LocalTime firstStartedAt; // 최초 시작 시각(HH:mm:ss), 없으면 null
        private LocalTime lastEndedAt;    // 마지막 종료 시각, 없으면 null
        private Integer sessionCount;
        private Boolean attended;         // 세션 1회 이상 또는 출석(체크인) 행 존재
        private Double achievementRate;   // totalStudySeconds / targetStudySeconds × 100 (100 초과 허용, UI 가 clamp)
    }

    /** GET /api/groups/{groupId}/study-stats/me — DAY 는 days 가 1개, 상단 필드는 그 날 요약. WEEK/MONTH 는 기간 합계 + days. */
    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class MyStudyStats {
        private Range range;
        private Long groupId;
        private LocalDate date;            // DAY 일 때 조회 날짜(그 외 null)
        private LocalDate periodStart;
        private LocalDate periodEnd;
        private Long totalStudySeconds;
        private Long maxFocusSeconds;      // 기간 내 가장 긴 연속 세션 구간
        private LocalTime firstStartedAt;  // DAY: 그날 최초 시작 / WEEK·MONTH: null
        private LocalTime lastEndedAt;     // DAY: 그날 마지막 종료 / WEEK·MONTH: null
        private Integer sessionCount;
        private Long targetStudySeconds;   // 그룹 하루 목표(targetStudyMinutes × 60)
        private Double achievementRate;    // DAY: total/target×100. WEEK·MONTH: averageDaily/target×100
        private Long averageDailyStudySeconds; // total / eligibleDays (eligibleDays=0 이면 0)
        private Integer attendanceDays;
        private Integer eligibleDays;      // max(기간 시작, 그룹 시작일, 내 가입일) ~ min(기간 끝, 오늘)
        private Double attendanceRate;
        private List<DaySummary> days;
    }

    /** 출석부 멤버 행. 개인정보는 표시명/닉네임/사진만(이메일·전공 없음). */
    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class MemberAttendance {
        private Long userId;
        private Long memberId;           // group_study_member_id
        private String nickname;         // 그룹 닉네임(없으면 사용자 표시명)
        private String photoUrl;
        private String role;             // LEADER | MEMBER
        private Long studySeconds;
        private Integer attendanceDays;
        private Integer eligibleDays;
        private Double attendanceRate;
        private Integer rank;            // competition ranking(1,2,2,4) — studySeconds DESC, 동률 같은 등수
        private List<DaySummary> days;
    }

    /** GET /api/groups/{groupId}/attendance */
    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class AttendanceBoard {
        private Range range;
        private Long groupId;
        private LocalDate periodStart;
        private LocalDate periodEnd;
        private Long targetStudySeconds;
        private Integer memberCount;
        private Long totalAttendanceDays;     // Σ출석(멤버·일)
        private Long totalEligibleDays;       // Σ대상(멤버·일)
        private Double attendanceRate;        // 그룹 전체 출석률
        private Long totalStudySeconds;
        private MemberAttendance my;
        private List<MemberAttendance> members; // rank 순
    }
}
