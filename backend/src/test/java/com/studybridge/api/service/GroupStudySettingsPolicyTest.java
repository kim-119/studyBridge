package com.studybridge.api.service;

import com.studybridge.api.entity.GroupStudyType;
import org.junit.jupiter.api.Test;

import java.time.LocalDate;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;

/**
 * 운영 정책 검증(GroupStudySettingsPolicy) + 카드 지표 계산(GroupActivityMetrics) 단위 테스트.
 * 서버 계약: 허용 외 값은 IllegalArgumentException(→400), enabled=false 문구는 null 정규화, 지표는 결정적 계산.
 */
class GroupStudySettingsPolicyTest {

    @Test
    void targetStudyMinutes_allowsOnlyFourToTenHoursHourly() {
        assertEquals(List.of(240, 300, 360, 420, 480, 540, 600), GroupStudySettingsPolicy.allowedTargetStudyMinutes());
        assertEquals(240, GroupStudySettingsPolicy.requireTargetStudyMinutes(240));
        assertEquals(600, GroupStudySettingsPolicy.requireTargetStudyMinutes(600));
        assertThrows(IllegalArgumentException.class, () -> GroupStudySettingsPolicy.requireTargetStudyMinutes(null));
        assertThrows(IllegalArgumentException.class, () -> GroupStudySettingsPolicy.requireTargetStudyMinutes(180));
        assertThrows(IllegalArgumentException.class, () -> GroupStudySettingsPolicy.requireTargetStudyMinutes(660));
        assertThrows(IllegalArgumentException.class, () -> GroupStudySettingsPolicy.requireTargetStudyMinutes(270));
    }

    @Test
    void studyType_rejectsNull() {
        assertEquals(GroupStudyType.CAM, GroupStudySettingsPolicy.requireStudyType(GroupStudyType.CAM));
        assertThrows(IllegalArgumentException.class, () -> GroupStudySettingsPolicy.requireStudyType(null));
    }

    @Test
    void joinQuestion_enabledRequiresText_disabledNormalizesToNull() {
        assertEquals("어떤 목표를 가지고 있나요?", GroupStudySettingsPolicy.normalizeJoinQuestion(true, "  어떤 목표를 가지고 있나요?  "));
        assertThrows(IllegalArgumentException.class, () -> GroupStudySettingsPolicy.normalizeJoinQuestion(true, "   "));
        assertThrows(IllegalArgumentException.class, () -> GroupStudySettingsPolicy.normalizeJoinQuestion(true, "가".repeat(201)));
        assertNull(GroupStudySettingsPolicy.normalizeJoinQuestion(false, "남아있는 질문"));
        assertNull(GroupStudySettingsPolicy.normalizeJoinQuestion(false, null));
    }

    @Test
    void nicknameRule_enabledRequiresText_disabledNormalizesToNull() {
        assertEquals("학교/학년/닉네임", GroupStudySettingsPolicy.normalizeNicknameRule(true, "학교/학년/닉네임"));
        assertThrows(IllegalArgumentException.class, () -> GroupStudySettingsPolicy.normalizeNicknameRule(true, ""));
        assertThrows(IllegalArgumentException.class, () -> GroupStudySettingsPolicy.normalizeNicknameRule(true, "규".repeat(101)));
        assertNull(GroupStudySettingsPolicy.normalizeNicknameRule(false, "규칙"));
    }

    @Test
    void joinAnswerAndNickname_requiredOnlyWhenGroupEnablesThem() {
        assertEquals("취업 준비", GroupStudySettingsPolicy.requireJoinAnswer(true, " 취업 준비 "));
        assertThrows(IllegalArgumentException.class, () -> GroupStudySettingsPolicy.requireJoinAnswer(true, null));
        assertNull(GroupStudySettingsPolicy.requireJoinAnswer(false, "무시되는 답변"));

        assertEquals("한양대/3/도현", GroupStudySettingsPolicy.requireNickname(true, "한양대/3/도현"));
        assertThrows(IllegalArgumentException.class, () -> GroupStudySettingsPolicy.requireNickname(true, " "));
        assertThrows(IllegalArgumentException.class, () -> GroupStudySettingsPolicy.requireNickname(false, "닉".repeat(31)));
        assertNull(GroupStudySettingsPolicy.requireNickname(false, ""));
        assertEquals("선택닉", GroupStudySettingsPolicy.requireNickname(false, "선택닉"));
    }

    @Test
    void studyIconId_acceptsSafeTokenOnly() {
        assertNull(GroupStudySettingsPolicy.normalizeStudyIconId(null));
        assertNull(GroupStudySettingsPolicy.normalizeStudyIconId("  "));
        assertEquals("owl-01", GroupStudySettingsPolicy.normalizeStudyIconId("owl-01"));
        assertThrows(IllegalArgumentException.class, () -> GroupStudySettingsPolicy.normalizeStudyIconId("../etc"));
        assertThrows(IllegalArgumentException.class, () -> GroupStudySettingsPolicy.normalizeStudyIconId("http://x"));
    }

    private static List<LocalDate> joined(LocalDate... dates) { return List.of(dates); }

    // T9/T11: 7일 전부터 있던 회원 3명 → 대상 21(멤버·일). 출석 16 → 76.2%, 공부 합 10800초 → 514초/멤버·일
    @Test
    void metrics_useEligibleMemberDaysAsDenominator() {
        LocalDate today = LocalDate.of(2026, 9, 30);
        LocalDate old = LocalDate.of(2026, 1, 1);
        GroupActivityMetrics m = GroupActivityMetrics.compute(today, old, joined(old, old, old), 16, 10800);
        assertEquals(21L, m.eligibleMemberDays());
        assertEquals(76.2, m.attendanceRate());
        assertEquals(514L, m.avgStudySeconds());
        assertEquals(7, m.windowDays());
    }

    // T10/T11/T12: 어제 가입한 회원은 2일만 대상 → 7 + 7 + 2 = 16 (21 이 아님). 같은 분모로 avg 계산.
    @Test
    void metrics_recentJoiner_countsFromJoinDate() {
        LocalDate today = LocalDate.of(2026, 9, 30);
        LocalDate old = LocalDate.of(2026, 1, 1);
        LocalDate yesterday = today.minusDays(1);
        assertEquals(7, GroupActivityMetrics.eligibleDays(today.minusDays(6), today, old, old));
        assertEquals(2, GroupActivityMetrics.eligibleDays(today.minusDays(6), today, old, yesterday));
        GroupActivityMetrics m = GroupActivityMetrics.compute(today, old, joined(old, old, yesterday), 16, 16000);
        assertEquals(16L, m.eligibleMemberDays());
        assertEquals(100.0, m.attendanceRate());
        assertEquals(1000L, m.avgStudySeconds()); // 16000 / 16
    }

    @Test
    void metrics_capWindowAtStartDate_andZeroWhenNoDenominator() {
        LocalDate today = LocalDate.of(2026, 9, 30);
        // 3일 전 시작(28,29,30 → 3일) 2명 → 분모 6. 출석 6 → 100%
        LocalDate start = LocalDate.of(2026, 9, 28);
        GroupActivityMetrics recent = GroupActivityMetrics.compute(today, start, joined(start, start), 6, 0);
        assertEquals(100.0, recent.attendanceRate());
        assertEquals(6L, recent.eligibleMemberDays());
        assertEquals(3, GroupActivityMetrics.eligibleDays(today, start));

        // 아직 시작 전 → 0
        GroupActivityMetrics future = GroupActivityMetrics.compute(today, LocalDate.of(2026, 10, 5), joined(today, today), 0, 0);
        assertEquals(0.0, future.attendanceRate());
        assertEquals(0L, future.avgStudySeconds());

        // 멤버 없음 → 0 (예외 없음)
        assertEquals(GroupActivityMetrics.EMPTY, GroupActivityMetrics.compute(today, LocalDate.of(2026, 1, 1), List.of(), 10, 100));
        assertEquals(GroupActivityMetrics.EMPTY, GroupActivityMetrics.compute(today, LocalDate.of(2026, 1, 1), null, 10, 100));
    }

    @Test
    void metrics_clampAbove100() {
        LocalDate today = LocalDate.of(2026, 9, 30);
        // 집계 창 밖 데이터 등으로 분자가 분모를 넘어도 100 을 넘지 않는다.
        GroupActivityMetrics m = GroupActivityMetrics.compute(today, LocalDate.of(2026, 1, 1), joined(LocalDate.of(2026, 1, 1)), 9, 0);
        assertEquals(100.0, m.attendanceRate());
        assertEquals(7L, m.attendedMemberDays());
    }
}
