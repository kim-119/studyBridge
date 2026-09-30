// node --test frontend/src/utils/__tests__   (vitest/jest 미도입 — Node 내장 테스트 러너 사용)
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  STUDY_TYPES, TARGET_STUDY_MINUTE_OPTIONS, studyTypeLabel, normalizeStudyType,
  formatTargetMinutes, formatStudySeconds, formatAttendanceRate, formatDateDot,
  normalizeGroup, buildSettingsPayload, validateSettingsForm, validateJoinInputs, memberDisplayName,
} from '../groupStudy.js';

test('study type label mapper: GENERAL/CAM, unknown falls back to GENERAL', () => {
  assert.equal(studyTypeLabel('GENERAL'), '일반 스터디');
  assert.equal(studyTypeLabel('CAM'), '캠 스터디');
  assert.equal(studyTypeLabel(undefined), '일반 스터디');
  assert.equal(normalizeStudyType('weird'), STUDY_TYPES.GENERAL);
});

test('target minutes options are 4h..10h hourly', () => {
  assert.deepEqual([...TARGET_STUDY_MINUTE_OPTIONS], [240, 300, 360, 420, 480, 540, 600]);
  assert.equal(formatTargetMinutes(240), '4시간');
  assert.equal(formatTargetMinutes(600), '10시간');
  assert.equal(formatTargetMinutes(270), '4시간 30분');
});

test('study seconds formatter: 12960 → 3시간 36분, no seconds shown', () => {
  assert.equal(formatStudySeconds(12960), '3시간 36분');
  assert.equal(formatStudySeconds(3600), '1시간');
  assert.equal(formatStudySeconds(1500), '25분');
  assert.equal(formatStudySeconds(0), '0분');
  assert.equal(formatStudySeconds(null), '0분');
  assert.equal(formatStudySeconds(-5), '0분');
});

test('attendance rate formatter clamps and trims trailing .0', () => {
  assert.equal(formatAttendanceRate(78), '78%');
  assert.equal(formatAttendanceRate(76.25), '76.3%');
  assert.equal(formatAttendanceRate(120), '100%');
  assert.equal(formatAttendanceRate(undefined), '0%');
});

test('date dot formatter', () => {
  assert.equal(formatDateDot('2026-09-30'), '2026. 9. 30.');
  assert.equal(formatDateDot('2026-09-30T10:11:12'), '2026. 9. 30.');
  assert.equal(formatDateDot(null), '');
});

test('normalizeGroup keeps legacy fields and never fabricates metrics', () => {
  const legacy = normalizeGroup({
    id: 1, title: 'A', description: '', hashtags: 'java, spring', currentCount: 3, capacity: 8,
    leaderId: 7, leaderName: '리더', isPublic: false, status: 'ACTIVE', startDate: '2026-09-01',
  });
  assert.equal(legacy.currentMembers, 3);
  assert.equal(legacy.maxMembers, 8);
  assert.equal(legacy.isPrivate, true);
  assert.deepEqual(legacy.tags, ['java', 'spring']);
  assert.equal(legacy.studyType, 'GENERAL');
  assert.equal(legacy.targetStudyMinutes, 240);
  assert.equal(legacy.joinQuestionEnabled, false);
  assert.equal(legacy.joinQuestion, '');
  assert.equal(legacy.attendanceRate, 0);
  assert.equal(legacy.avgStudySeconds, 0);
  assert.equal(legacy.hasCoverImage, false);

  const modern = normalizeGroup({
    id: 2, title: 'B', description: 'd', memberCount: 16, maxMembers: 30, currentCount: 16, capacity: 30,
    leaderId: 1, leaderName: '홍길동', isPublic: true, status: 'RECRUITING', startDate: '2026-09-30',
    studyType: 'CAM', targetStudyMinutes: 480, joinQuestionEnabled: true, joinQuestion: '목표?',
    nicknameRuleEnabled: false, nicknameRule: '남은문구', attendanceRate: 78.0, avgStudySeconds: 12960,
    coverImageUrl: 'https://x/y.png', activityWindowDays: 7,
  });
  assert.equal(modern.studyType, 'CAM');
  assert.equal(modern.targetStudyMinutes, 480);
  assert.equal(modern.joinQuestion, '목표?');
  assert.equal(modern.nicknameRule, '');            // enabled=false → 문구 무시
  assert.equal(modern.attendanceRate, 78);
  assert.equal(modern.avgStudySeconds, 12960);
  assert.equal(modern.hasCoverImage, true);
});

test('buildSettingsPayload omits text when toggle is off', () => {
  const on = buildSettingsPayload({ studyType: 'CAM', targetStudyMinutes: '300', joinQuestionEnabled: true, joinQuestion: ' q ', nicknameRuleEnabled: true, nicknameRule: 'r' });
  assert.deepEqual(on, { studyType: 'CAM', targetStudyMinutes: 300, joinQuestionEnabled: true, nicknameRuleEnabled: true, joinQuestion: 'q', nicknameRule: 'r' });
  const off = buildSettingsPayload({ studyType: 'GENERAL', targetStudyMinutes: 240, joinQuestionEnabled: false, joinQuestion: 'stale', nicknameRuleEnabled: false, nicknameRule: 'stale' });
  assert.equal('joinQuestion' in off, false);
  assert.equal('nicknameRule' in off, false);
});

test('validateSettingsForm mirrors server rules', () => {
  assert.equal(validateSettingsForm({ targetStudyMinutes: 240, joinQuestionEnabled: false, nicknameRuleEnabled: false }), null);
  assert.match(validateSettingsForm({ targetStudyMinutes: 180 }), /4시간~10시간/);
  assert.match(validateSettingsForm({ targetStudyMinutes: 240, joinQuestionEnabled: true, joinQuestion: ' ' }), /질문 내용/);
  assert.match(validateSettingsForm({ targetStudyMinutes: 240, nicknameRuleEnabled: true, nicknameRule: '' }), /규칙 안내/);
  assert.match(validateSettingsForm({ targetStudyMinutes: 240, joinQuestionEnabled: true, joinQuestion: 'q'.repeat(201) }), /200자/);
});

test('validateJoinInputs requires answer/nickname only when group enables them', () => {
  assert.equal(validateJoinInputs({ joinQuestionEnabled: false, nicknameRuleEnabled: false }, {}), null);
  assert.match(validateJoinInputs({ joinQuestionEnabled: true }, { joinAnswer: '' }), /답변/);
  assert.match(validateJoinInputs({ nicknameRuleEnabled: true }, { nickname: ' ' }), /닉네임/);
  assert.equal(validateJoinInputs({ joinQuestionEnabled: true, nicknameRuleEnabled: true }, { joinAnswer: 'a', nickname: 'n' }), null);
});

test('memberDisplayName prefers group nickname', () => {
  assert.equal(memberDisplayName({ displayName: '김도현', nickname: '한양대/3/도현' }), '한양대/3/도현');
  assert.equal(memberDisplayName({ displayName: '김도현', nickname: null }), '김도현');
});
