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

    /** ALL 은 랭킹(study-time) 전용 — 출석부/개인 통계에서는 400. */
    public enum Range { DAY, WEEK, MONTH, ALL }

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

    /** 학습시간 랭킹 멤버 행. studySeconds = 서버 시각 기준 세션 구간 합(진행 중 세션은 마지막 heartbeat 까지). */
    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class StudyTimeMember {
        private Integer rank;            // competition ranking(1,2,2,4) — studySeconds DESC
        private Long userId;
        private Long memberId;
        private String nickname;         // 그룹 닉네임(없으면 사용자 표시명)
        private String profileImageUrl;  // 원본 photoUrl(없으면 null)
        private String role;             // LEADER | MEMBER
        private Boolean isMe;
        private Long studySeconds;
        private Integer sessionCount;    // 집계에 포함된 세션 수(완료 + 진행 중)
        private Boolean activeNow;       // 이 그룹에서 진행 중(heartbeat 생존) 세션이 있는지
    }

    /** GET /api/groups/{groupId}/stats/study-time?range=ALL|DAY|WEEK|MONTH */
    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class StudyTimeRanking {
        private Long groupId;
        private Range range;
        private LocalDate periodStart;   // ALL 이면 null
        private LocalDate periodEnd;     // ALL 이면 null
        private java.time.LocalDateTime generatedAt; // 서버 시각(진행 중 세션 클램프 기준)
        private Integer memberCount;
        private Long totalStudySeconds;
        private StudyTimeMember my;
        private List<StudyTimeMember> members; // rank 순
    }

    /** 퀴즈 랭킹 멤버 행. 미참여 멤버는 전부 0. */
    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class QuizRankingMember {
        private Integer rank;            // competition ranking — score DESC, accuracy DESC, correctCount DESC
        private Long userId;
        private Long memberId;
        private String nickname;
        private String profileImageUrl;
        private String role;
        private Boolean isMe;
        private Integer score;           // Σ points_awarded (기존 채점 정책: rewardPoints + 속도 보너스)
        private Integer correctCount;    // 정답 수
        private Integer totalQuestions;  // 참여한 세션에서 출제(정답 공개)된 문제 수
        private Double accuracy;         // correctCount / totalQuestions × 100 (소수 1자리)
        private Integer quizParticipationCount; // 답안을 1개 이상 제출한 세션 수
    }

    /** GET /api/groups/{groupId}/stats/quiz-ranking */
    @Data
    @NoArgsConstructor
    @AllArgsConstructor
    @Builder
    public static class QuizRanking {
        private Long groupId;
        private java.time.LocalDateTime generatedAt;
        private Integer memberCount;
        private Integer sessionCount;    // 채점 이력이 있는 세션 수
        private QuizRankingMember my;
        private List<QuizRankingMember> members; // rank 순
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
