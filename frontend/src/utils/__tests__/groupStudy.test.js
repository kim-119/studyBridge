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

// ──────────────────────────────────────────────────────────────────────────
// 스터디 타입별 입장 준비 UI / 미디어 권한 정책 / 가입 정책 섹션 노출 (2026-10-07)
// ──────────────────────────────────────────────────────────────────────────
import {
  isCamStudy, resolvePreJoinLayout, buildMicConstraints, buildCameraPreviewConstraints, resolvePreJoinMediaPolicy,
  micStateLabel, AVATAR_MODES, resolveParticipantAvatar,
  JOIN_POLICIES, resolveJoinPolicy, isApprovalRequired, resolveLeaderConsoleSections,
} from '../groupStudy.js';

test('GENERAL prejoin layout: avatar/profile/mic only — no camera preview/toggle/device selector/permission', () => {
  const l = resolvePreJoinLayout('GENERAL');
  assert.equal(l.isCam, false);
  assert.equal(l.showAvatarPreview, true);
  assert.equal(l.showProfileSelector, true);
  assert.equal(l.showMicrophoneToggle, true);
  assert.equal(l.showMicrophoneDeviceSelector, true);
  assert.equal(l.showCameraPreview, false);
  assert.equal(l.showCameraToggle, false);
  assert.equal(l.showCameraDeviceSelector, false);
  assert.equal(l.requestsCameraPermission, false);
  // 서버가 studyType 을 안 내려주는 구 row 도 GENERAL 로 취급(normalizeStudyType)
  assert.equal(resolvePreJoinLayout(undefined).isCam, false);
  assert.equal(isCamStudy('weird'), false);
});

test('CAM prejoin layout keeps camera preview/toggle/device selector + mic toggle/device selector', () => {
  const l = resolvePreJoinLayout('CAM');
  assert.equal(l.isCam, true);
  assert.equal(l.showCameraPreview, true);
  assert.equal(l.showCameraToggle, true);
  assert.equal(l.showCameraDeviceSelector, true);
  assert.equal(l.showMicrophoneToggle, true);
  assert.equal(l.showMicrophoneDeviceSelector, true);
  assert.equal(l.showAvatarPreview, false);
  assert.equal(l.showProfileSelector, false);
  assert.equal(l.requestsCameraPermission, true);
});

test('media policy: GENERAL getUserMedia is audio:true/video:false; CAM requests audio+video', () => {
  assert.deepEqual(resolvePreJoinMediaPolicy('GENERAL'), { audio: true, video: false });
  assert.deepEqual(resolvePreJoinMediaPolicy('CAM'), { audio: true, video: true });
  assert.deepEqual(buildMicConstraints(''), { audio: true, video: false });
  assert.deepEqual(buildMicConstraints('mic-1'), { audio: { deviceId: { exact: 'mic-1' } }, video: false });
  // CAM 카메라 프리뷰는 video 만(audio:false) — 기존 정책 유지
  assert.deepEqual(buildCameraPreviewConstraints(''), { video: true, audio: false });
  assert.deepEqual(buildCameraPreviewConstraints('cam-1'), { video: { deviceId: { exact: 'cam-1' } }, audio: false });
});

test('mic state label distinguishes 켜짐 / 꺼짐 / 없음', () => {
  assert.equal(micStateLabel(true, 'available'), '마이크 켜짐');
  assert.equal(micStateLabel(false, 'available'), '마이크 꺼짐');
  assert.equal(micStateLabel(true, 'unavailable'), '마이크 없음');
  assert.equal(micStateLabel(true, 'error'), '마이크 권한/오류');
  assert.equal(micStateLabel(true, 'checking'), '마이크 확인 중…');
});

test('participant avatar priority: upload > account profile > default', () => {
  assert.deepEqual(resolveParticipantAvatar({ avatarMode: AVATAR_MODES.UPLOAD, avatarUrl: 'u.png', profilePhotoUrl: 'p.png' }), { kind: 'image', url: 'u.png' });
  assert.deepEqual(resolveParticipantAvatar({ avatarMode: AVATAR_MODES.PROFILE, avatarUrl: null, profilePhotoUrl: 'p.png' }), { kind: 'image', url: 'p.png' });
  assert.deepEqual(resolveParticipantAvatar({ avatarMode: AVATAR_MODES.DEFAULT, avatarUrl: 'u.png', profilePhotoUrl: 'p.png' }), { kind: 'default', url: null });
  // 메타데이터 없는 구 클라이언트: 프로필 있으면 프로필, 없으면 기본
  assert.deepEqual(resolveParticipantAvatar({ profilePhotoUrl: 'p.png' }), { kind: 'image', url: 'p.png' });
  assert.deepEqual(resolveParticipantAvatar({}), { kind: 'default', url: null });
  // upload 모드인데 url 이 없으면(업로드 실패) 프로필로 폴백
  assert.deepEqual(resolveParticipantAvatar({ avatarMode: AVATAR_MODES.UPLOAD, avatarUrl: null, profilePhotoUrl: 'p.png' }), { kind: 'image', url: 'p.png' });
});

test('join policy derives from server fields only (isPublic + optional approvalRequired/joinPolicy)', () => {
  assert.equal(resolveJoinPolicy({ isPrivate: false }), JOIN_POLICIES.OPEN);
  assert.equal(resolveJoinPolicy({ isPrivate: false, approvalRequired: true }), JOIN_POLICIES.APPROVAL);
  assert.equal(resolveJoinPolicy({ isPrivate: true }), JOIN_POLICIES.INVITE_ONLY);
  assert.equal(resolveJoinPolicy({ isPrivate: true, approvalRequired: true }), JOIN_POLICIES.JOIN_REQUEST);
  assert.equal(resolveJoinPolicy({ isPublic: false, joinPolicy: 'join_request' }), JOIN_POLICIES.JOIN_REQUEST);
  assert.equal(resolveJoinPolicy(null), JOIN_POLICIES.OPEN);
  // normalizeGroup: 서버 미전송 → approvalRequired=false (프론트가 승인 정책을 만들어내지 않는다)
  const g = normalizeGroup({ id: 1, title: 't', isPublic: true });
  assert.equal(g.approvalRequired, false);
  assert.equal(g.joinPolicy, null);
  assert.equal(isApprovalRequired(g), false);
});

test('leader console sections: pending list only when approval policy or real pending members; invite only for private', () => {
  // approval OFF + 0 pending → PendingMemberSection 없음
  let s = resolveLeaderConsoleSections({ isPrivate: false }, 0);
  assert.equal(s.showPendingMembers, false);
  assert.equal(s.showInviteManagement, false);
  // approval ON → 있음
  s = resolveLeaderConsoleSections({ isPrivate: false, approvalRequired: true }, 0);
  assert.equal(s.showPendingMembers, true);
  // approval OFF 라도 실제 대기자(레거시 PENDING row)가 있으면 방장이 처리할 수 있게 표시
  s = resolveLeaderConsoleSections({ isPrivate: false }, 2);
  assert.equal(s.showPendingMembers, true);
  // INVITE_ONLY → 초대 관리 있음 / 대기자 명단 없음
  s = resolveLeaderConsoleSections({ isPrivate: true }, 0);
  assert.equal(s.policy, JOIN_POLICIES.INVITE_ONLY);
  assert.equal(s.showInviteManagement, true);
  assert.equal(s.showPendingMembers, false);
  // JOIN_REQUEST → 둘 다
  s = resolveLeaderConsoleSections({ isPrivate: true, approvalRequired: true }, 0);
  assert.equal(s.policy, JOIN_POLICIES.JOIN_REQUEST);
  assert.equal(s.showInviteManagement, true);
  assert.equal(s.showPendingMembers, true);
});

// ── GENERAL 프로필 모델: DEFAULT / EMOJI / IMAGE(upload·profile) (2026-10-07)
import { PROFILE_EMOJIS, isProfileEmoji } from '../groupStudy.js';

test('profile emoji preset: 30+ unique Unicode emojis, validator rejects arbitrary strings', () => {
  assert.ok(PROFILE_EMOJIS.length >= 30);
  assert.equal(new Set(PROFILE_EMOJIS).size, PROFILE_EMOJIS.length);
  for (const e of ['🐰', '🤓', '📚', '☀️']) assert.ok(isProfileEmoji(e), e);
  assert.equal(isProfileEmoji('<img src=x>'), false);
  assert.equal(isProfileEmoji(''), false);
  assert.equal(isProfileEmoji(null), false);
});

test('participant avatar: EMOJI mode wins with valid value, invalid value falls back to image/default', () => {
  assert.deepEqual(resolveParticipantAvatar({ avatarMode: AVATAR_MODES.EMOJI, avatarValue: '🐰', profilePhotoUrl: 'p.png' }), { kind: 'emoji', value: '🐰', url: null });
  assert.deepEqual(resolveParticipantAvatar({ avatarMode: AVATAR_MODES.EMOJI, avatarValue: 'javascript:', profilePhotoUrl: 'p.png' }), { kind: 'image', url: 'p.png' });
  assert.deepEqual(resolveParticipantAvatar({ avatarMode: AVATAR_MODES.EMOJI, avatarValue: null }), { kind: 'default', url: null });
  // IMAGE(upload) 는 이모지 값이 남아 있어도 모드가 upload 면 이미지
  assert.deepEqual(resolveParticipantAvatar({ avatarMode: AVATAR_MODES.UPLOAD, avatarValue: '🐰', avatarUrl: 'u.png' }), { kind: 'image', url: 'u.png' });
});
