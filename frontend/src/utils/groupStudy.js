// 그룹스터디 운영 정책/지표 표시의 단일 출처.
//  · 서버 계약(GroupStudyDTO.Response)의 enum/숫자를 화면 문자열로 바꾸는 곳은 여기뿐이어야 한다.
//  · 숫자→문자열 변환만 하며, 어떤 지표도 프론트에서 "생성"하지 않는다(서버 값이 없으면 0/미표시).

export const STUDY_TYPES = Object.freeze({
  GENERAL: 'GENERAL',
  CAM: 'CAM',
});

const STUDY_TYPE_LABELS = Object.freeze({
  GENERAL: '일반 스터디',
  CAM: '캠 스터디',
});

export const STUDY_TYPE_OPTIONS = Object.freeze([
  { value: STUDY_TYPES.GENERAL, label: STUDY_TYPE_LABELS.GENERAL, description: '자료·퀴즈·채팅 중심으로 함께 공부하는 스터디' },
  { value: STUDY_TYPES.CAM, label: STUDY_TYPE_LABELS.CAM, description: '캠을 켜고 서로의 공부 모습을 확인하는 스터디' },
]);

// 서버 GroupStudySettingsPolicy 와 동일한 범위(4~10시간, 1시간 단위). 서버가 최종 검증한다.
export const TARGET_STUDY_MINUTES_MIN = 240;
export const TARGET_STUDY_MINUTES_MAX = 600;
export const TARGET_STUDY_MINUTES_STEP = 60;
export const TARGET_STUDY_MINUTES_DEFAULT = 240;

export const JOIN_QUESTION_MAX_LENGTH = 200;
export const JOIN_ANSWER_MAX_LENGTH = 500;
export const NICKNAME_RULE_MAX_LENGTH = 100;
export const NICKNAME_MAX_LENGTH = 30;

export const TARGET_STUDY_MINUTE_OPTIONS = Object.freeze(
  Array.from(
    { length: (TARGET_STUDY_MINUTES_MAX - TARGET_STUDY_MINUTES_MIN) / TARGET_STUDY_MINUTES_STEP + 1 },
    (_, i) => TARGET_STUDY_MINUTES_MIN + i * TARGET_STUDY_MINUTES_STEP,
  ),
);

export const normalizeStudyType = (value) => (value === STUDY_TYPES.CAM ? STUDY_TYPES.CAM : STUDY_TYPES.GENERAL);

export const studyTypeLabel = (value) => STUDY_TYPE_LABELS[normalizeStudyType(value)];

// 서버 enum(GroupStudyType) 기준 분기. 입장 준비/스터디룸의 카메라 기능 유무는 오직 이 값으로 결정한다.
export const isCamStudy = (studyType) => normalizeStudyType(studyType) === STUDY_TYPES.CAM;

// ── 입장 준비(PreJoin) 레이아웃: 스터디 타입별로 어떤 하위 컴포넌트를 렌더할지의 단일 출처.
//  GENERAL: 프로필(아바타/선택기) + 마이크(토글/장치) 만. 카메라 preview/토글/장치 선택/권한 요청 없음.
//  CAM    : 기존 카메라 preview/토글 + 마이크(토글/장치) + 장치 설정.
export const resolvePreJoinLayout = (studyType) => {
  const cam = isCamStudy(studyType);
  return Object.freeze({
    studyType: normalizeStudyType(studyType),
    isCam: cam,
    showAvatarPreview: !cam,
    showProfileSelector: !cam,
    showCameraPreview: cam,
    showCameraToggle: cam,
    showCameraDeviceSelector: cam,
    showMicrophoneToggle: true,
    showMicrophoneDeviceSelector: true,
    requestsCameraPermission: cam,
  });
};

// ── 미디어 권한 정책(getUserMedia constraints 단일 출처).
//  GENERAL 은 video:false 로만 호출한다(video permission 요청 자체가 버그). CAM 은 기존 정책(카메라/마이크 각각 획득) 유지.
const audioConstraint = (micDeviceId) => (micDeviceId ? { deviceId: { exact: micDeviceId } } : true);
export const buildMicConstraints = (micDeviceId) => ({ audio: audioConstraint(micDeviceId), video: false });
export const buildCameraPreviewConstraints = (cameraDeviceId) => ({
  video: cameraDeviceId ? { deviceId: { exact: cameraDeviceId } } : true,
  audio: false,
});
// 입장 준비 화면이 스터디 타입별로 요청하는 미디어 종류(테스트/로그용 요약).
export const resolvePreJoinMediaPolicy = (studyType) => (isCamStudy(studyType)
  ? Object.freeze({ audio: true, video: true })
  : Object.freeze({ audio: true, video: false }));

// 마이크 상태 라벨: 켜짐/꺼짐/없음 세 상태를 명확히 구분한다(확인 중·권한 오류는 보조 상태).
//  micStatus: 'idle' | 'checking' | 'available' | 'unavailable' | 'error' | 'off'
export const micStateLabel = (isMicOn, micStatus) => {
  if (!isMicOn) return '마이크 꺼짐';
  if (micStatus === 'unavailable') return '마이크 없음';
  if (micStatus === 'error') return '마이크 권한/오류';
  if (micStatus === 'checking' || micStatus === 'idle') return '마이크 확인 중…';
  return '마이크 켜짐';
};

// ── GENERAL 참가자 visual identity 우선순위.
//  1) 이번 입장 화면에서 지정한 이미지(upload) 2) 기존 계정 프로필 이미지 3) StudyBridge 기본 아바타(lucide User fallback).
//  avatarMode: 'upload' | 'profile' | 'default' (connection metadata 로 전파). 모르면 프로필→기본 순.
//  PROFILE_TYPE(요구사항 DEFAULT/EMOJI/IMAGE)은 이 모드로 표현한다: default | emoji | upload·profile(=IMAGE).
export const AVATAR_MODES = Object.freeze({ UPLOAD: 'upload', PROFILE: 'profile', DEFAULT: 'default', EMOJI: 'emoji' });

// GENERAL 프로필용 Unicode 이모지 프리셋(외부 API/CDN 없음, PNG 변환 없음 — 문자열 그대로 metadata 로 전파).
export const PROFILE_EMOJIS = Object.freeze([
  '🙂', '😊', '😎', '🤓', '🥳', '😴',
  '🐶', '🐱', '🐰', '🐻', '🐼', '🦊',
  '🐯', '🐸', '🐧', '🐵', '🦁', '🐨',
  '🌱', '⭐', '🔥', '🌙', '☀️', '☁️',
  '📚', '💡', '🎯', '🚀', '🎧', '☕',
  '💻', '🧠', '✏️', '📖', '🎓', '📝',
]);
export const isProfileEmoji = (value) => typeof value === 'string' && PROFILE_EMOJIS.includes(value);

// 반환: { kind: 'emoji', value } | { kind: 'image', url } | { kind: 'default' }
export const resolveParticipantAvatar = ({ avatarMode, avatarUrl, avatarValue, profilePhotoUrl } = {}) => {
  if (avatarMode === AVATAR_MODES.EMOJI && isProfileEmoji(avatarValue)) return { kind: 'emoji', value: avatarValue, url: null };
  if (avatarMode === AVATAR_MODES.DEFAULT) return { kind: 'default', url: null };
  if (avatarMode === AVATAR_MODES.UPLOAD && avatarUrl) return { kind: 'image', url: avatarUrl };
  const url = profilePhotoUrl || avatarUrl || null;
  return url ? { kind: 'image', url } : { kind: 'default', url: null };
};

// ── 가입 정책(방장 콘솔 섹션 노출의 단일 출처).
//  서버 계약(GroupStudyDTO.Response)에는 isPublic 만 있고 승인 플래그가 없다(현재 서버: 공개=즉시가입, 비공개=초대 링크 전용).
//  서버가 approvalRequired / joinPolicy 를 내려주면 그대로 따르고, 없으면 isPublic 에서 유도한다(프론트가 값을 만들어내지 않는다).
export const JOIN_POLICIES = Object.freeze({
  OPEN: 'OPEN',                 // 공개 + 즉시가입
  APPROVAL: 'APPROVAL',         // 공개 + 가입승인
  INVITE_ONLY: 'INVITE_ONLY',   // 비공개 + 초대 전용
  JOIN_REQUEST: 'JOIN_REQUEST', // 비공개 + 가입 신청
});
export const resolveJoinPolicy = (study) => {
  if (!study) return JOIN_POLICIES.OPEN;
  const explicit = typeof study.joinPolicy === 'string' ? study.joinPolicy.toUpperCase() : null;
  if (explicit && JOIN_POLICIES[explicit]) return JOIN_POLICIES[explicit];
  const isPrivate = study.isPrivate === true || study.isPublic === false;
  const approvalRequired = study.approvalRequired === true;
  if (isPrivate) return approvalRequired ? JOIN_POLICIES.JOIN_REQUEST : JOIN_POLICIES.INVITE_ONLY;
  return approvalRequired ? JOIN_POLICIES.APPROVAL : JOIN_POLICIES.OPEN;
};
export const isApprovalRequired = (study) => {
  const policy = resolveJoinPolicy(study);
  return policy === JOIN_POLICIES.APPROVAL || policy === JOIN_POLICIES.JOIN_REQUEST;
};
// 방장 콘솔 섹션: 초대 관리는 비공개(INVITE_ONLY/JOIN_REQUEST)만, 대기자 명단은 승인 정책이거나 실제 대기자가 있을 때만(DOM 자체 미렌더).
export const resolveLeaderConsoleSections = (study, pendingCount = 0) => {
  const policy = resolveJoinPolicy(study);
  const pending = Math.max(0, Number(pendingCount) || 0);
  return Object.freeze({
    policy,
    showInviteManagement: policy === JOIN_POLICIES.INVITE_ONLY || policy === JOIN_POLICIES.JOIN_REQUEST,
    showPendingMembers: isApprovalRequired(study) || pending > 0,
  });
};

export const isValidTargetStudyMinutes = (minutes) => TARGET_STUDY_MINUTE_OPTIONS.includes(Number(minutes));

// 240 → "4시간", 270 → "4시간 30분" (목표시간 표시)
export const formatTargetMinutes = (minutes) => {
  const total = Math.max(0, Math.round(Number(minutes) || 0));
  const h = Math.floor(total / 60);
  const m = total % 60;
  if (h && m) return `${h}시간 ${m}분`;
  if (h) return `${h}시간`;
  return `${m}분`;
};

// 12960 → "3시간 36분", 1500 → "25분", 0 → "0분" (공부량 표시). 초 단위는 카드에서 노출하지 않는다.
export const formatStudySeconds = (seconds) => {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  if (h && m) return `${h}시간 ${m}분`;
  if (h) return `${h}시간`;
  return `${m}분`;
};

// 78.04 → "78%", 76.25 → "76.3%" (정수면 소수점 생략). null/undefined → "0%"
export const formatAttendanceRate = (rate) => {
  const n = Math.min(100, Math.max(0, Number(rate) || 0));
  const rounded = Math.round(n * 10) / 10;
  return `${Number.isInteger(rounded) ? rounded : rounded.toFixed(1)}%`;
};

// "2026-09-30" | "2026-09-30T10:00:00" → "2026. 9. 30."
export const formatDateDot = (value) => {
  if (!value) return '';
  const [datePart] = String(value).split('T');
  const [y, m, d] = datePart.split('-').map((v) => parseInt(v, 10));
  if (!y || !m || !d) return datePart;
  return `${y}. ${m}. ${d}.`;
};

const DEFAULT_TAGS = ['자율', '캠스터디'];
// 기본 썸네일: 외부 이미지(unsplash)를 내려받지 않는다. 사용자 지정 이미지가 없으면 GroupProfileImage 가 스터디 타입별 기본 아이콘을 그린다.
const DEFAULT_THUMBNAIL = null;

export const parseHashtags = (hashtags) => {
  if (!hashtags) return [...DEFAULT_TAGS];
  return hashtags.split(/[\s,#]+/).map((s) => s.trim()).filter(Boolean);
};

// 서버 GroupStudyDTO.Response → 화면 모델. GroupStudy.jsx / StudyRoom.jsx 가 같은 모양(study)을 소비한다.
//  · 기존 필드명(currentMembers/maxMembers/leader/isPrivate/thumbnailUrl…)은 StudyRoom 호환을 위해 유지.
//  · 운영 정책/지표는 서버 값이 없으면(구 서버) 기본값/0 으로 두되 절대 임의 숫자를 만들지 않는다.
export const normalizeGroup = (group) => {
  const currentMembers = group.memberCount ?? group.currentCount ?? 1;
  const maxMembers = group.maxMembers ?? group.capacity ?? 10;
  return {
    id: group.id,
    title: group.title,
    description: group.description || '스터디 설명이 없습니다.',
    content: group.description || '스터디 설명이 없습니다.',
    hashtags: group.hashtags || '',
    tags: parseHashtags(group.hashtags),
    currentMembers,
    maxMembers,
    current: currentMembers,
    max: maxMembers,
    leader: group.leaderName || '방장',
    author: group.leaderName || '방장',
    leaderId: group.leaderId,
    leaderPhotoUrl: group.leaderPhotoUrl,
    status: group.status, // 'RECRUITING', 'ACTIVE', 'COMPLETED'
    isPrivate: !group.isPublic,
    thumbnailUrl: group.coverImageUrl || DEFAULT_THUMBNAIL,
    hasCoverImage: Boolean(group.coverImageUrl),
    startDate: group.startDate,
    endDate: group.endDate,
    createdAt: group.createdAt,
    date: group.createdAt ? group.createdAt.split('T')[0] : (group.startDate || new Date().toISOString().split('T')[0]),
    // ── 운영 정책 (서버 계약과 동일 필드명)
    studyType: normalizeStudyType(group.studyType),
    targetStudyMinutes: Number.isFinite(Number(group.targetStudyMinutes)) && group.targetStudyMinutes != null
      ? Number(group.targetStudyMinutes)
      : TARGET_STUDY_MINUTES_DEFAULT,
    joinQuestionEnabled: group.joinQuestionEnabled === true,
    joinQuestion: group.joinQuestionEnabled === true ? (group.joinQuestion || '') : '',
    nicknameRuleEnabled: group.nicknameRuleEnabled === true,
    nicknameRule: group.nicknameRuleEnabled === true ? (group.nicknameRule || '') : '',
    studyIconId: group.studyIconId || null,
    // ── 가입 정책(서버가 내려줄 때만 true/문자열. 현재 서버 계약은 미전송 → 공개=즉시가입, 비공개=초대 전용)
    approvalRequired: group.approvalRequired === true,
    joinPolicy: typeof group.joinPolicy === 'string' ? group.joinPolicy : null,
    // ── 활동 지표 (서버 계산값 그대로)
    attendanceRate: Number(group.attendanceRate) || 0,
    avgStudySeconds: Number(group.avgStudySeconds) || 0,
    activityWindowDays: Number(group.activityWindowDays) || 7,
  };
};

// 생성/수정 폼의 운영 정책 부분 → multipart 필드. enabled=false 이면 문구를 보내지 않는다(서버도 null 정규화).
export const buildSettingsPayload = (form) => {
  const payload = {
    studyType: normalizeStudyType(form.studyType),
    targetStudyMinutes: Number(form.targetStudyMinutes),
    joinQuestionEnabled: Boolean(form.joinQuestionEnabled),
    nicknameRuleEnabled: Boolean(form.nicknameRuleEnabled),
  };
  if (payload.joinQuestionEnabled) payload.joinQuestion = (form.joinQuestion || '').trim();
  if (payload.nicknameRuleEnabled) payload.nicknameRule = (form.nicknameRule || '').trim();
  if (form.studyIconId) payload.studyIconId = form.studyIconId;
  return payload;
};

// 프론트 1차 검증(서버가 최종). 통과 시 null, 실패 시 사용자 메시지.
export const validateSettingsForm = (form) => {
  if (!isValidTargetStudyMinutes(form.targetStudyMinutes)) {
    return '하루 목표 공부시간은 4시간~10시간 중에서 선택해주세요.';
  }
  if (form.joinQuestionEnabled) {
    const q = (form.joinQuestion || '').trim();
    if (!q) return '가입 질문을 사용하려면 질문 내용을 입력해주세요.';
    if (q.length > JOIN_QUESTION_MAX_LENGTH) return `가입 질문은 ${JOIN_QUESTION_MAX_LENGTH}자 이내로 입력해주세요.`;
  }
  if (form.nicknameRuleEnabled) {
    const r = (form.nicknameRule || '').trim();
    if (!r) return '그룹 닉네임 규칙을 사용하려면 규칙 안내 문구를 입력해주세요.';
    if (r.length > NICKNAME_RULE_MAX_LENGTH) return `그룹 닉네임 규칙은 ${NICKNAME_RULE_MAX_LENGTH}자 이내로 입력해주세요.`;
  }
  return null;
};

// 가입 시(질문/닉네임) 프론트 1차 검증. 통과 시 null.
export const validateJoinInputs = (study, { joinAnswer, nickname }) => {
  if (study?.joinQuestionEnabled) {
    const a = (joinAnswer || '').trim();
    if (!a) return '가입 질문에 대한 답변을 입력해주세요.';
    if (a.length > JOIN_ANSWER_MAX_LENGTH) return `답변은 ${JOIN_ANSWER_MAX_LENGTH}자 이내로 입력해주세요.`;
  }
  if (study?.nicknameRuleEnabled) {
    const n = (nickname || '').trim();
    if (!n) return '이 그룹은 그룹 닉네임 입력이 필요합니다.';
    if (n.length > NICKNAME_MAX_LENGTH) return `그룹 닉네임은 ${NICKNAME_MAX_LENGTH}자 이내로 입력해주세요.`;
  }
  return null;
};

// 멤버 표시명: 그룹 닉네임이 있으면 우선, 없으면 사용자 표시명.
export const memberDisplayName = (member) => member?.nickname || member?.displayName || '';
