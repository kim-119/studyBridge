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

    @Test
    void metrics_useEligibleDaysAndMemberCountAsDenominator() {
        LocalDate today = LocalDate.of(2026, 9, 30);
        // 시작한 지 오래된 그룹, 3명, 7일 → 분모 21. 출석 행 16 → 76.2%, 공부 합 3시간 = 10800초 → 514초/인·일
        GroupActivityMetrics m = GroupActivityMetrics.compute(today, LocalDate.of(2026, 1, 1), 3, 16, 10800);
        assertEquals(76.2, m.attendanceRate());
        assertEquals(514L, m.avgStudySeconds());
        assertEquals(7, m.windowDays());
    }

    @Test
    void metrics_capWindowAtStartDate_andZeroWhenNoDenominator() {
        LocalDate today = LocalDate.of(2026, 9, 30);
        // 3일 전 시작(28,29,30 → 3일) 2명 → 분모 6. 출석 6 → 100%
        GroupActivityMetrics recent = GroupActivityMetrics.compute(today, LocalDate.of(2026, 9, 28), 2, 6, 0);
        assertEquals(100.0, recent.attendanceRate());
        assertEquals(3, GroupActivityMetrics.eligibleDays(today, LocalDate.of(2026, 9, 28)));

        // 아직 시작 전 → 0
        GroupActivityMetrics future = GroupActivityMetrics.compute(today, LocalDate.of(2026, 10, 5), 5, 0, 0);
        assertEquals(0.0, future.attendanceRate());
        assertEquals(0L, future.avgStudySeconds());

        // 인원 정보 없음/0 → 0 (예외 없음)
        assertEquals(GroupActivityMetrics.EMPTY, GroupActivityMetrics.compute(today, LocalDate.of(2026, 1, 1), 0, 10, 100));
        assertEquals(GroupActivityMetrics.EMPTY, GroupActivityMetrics.compute(today, LocalDate.of(2026, 1, 1), null, 10, 100));
    }

    @Test
    void metrics_clampAbove100() {
        LocalDate today = LocalDate.of(2026, 9, 30);
        // 탈퇴한 멤버의 과거 출석이 남아 분자가 분모를 넘는 경우에도 100 을 넘지 않는다.
        GroupActivityMetrics m = GroupActivityMetrics.compute(today, LocalDate.of(2026, 1, 1), 1, 9, 0);
        assertEquals(100.0, m.attendanceRate());
    }
}
