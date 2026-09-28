export const DEFAULT_COVER_IMAGE_URL =
  'https://images.unsplash.com/photo-1517842645767-c639042777db?ixlib=rb-4.0.3&auto=format&fit=crop&w=800&q=80';

export const COVER_IMAGE_PRESETS = [
  {
    key: 'desk',
    previewUrl:
      'https://images.unsplash.com/photo-1517842645767-c639042777db?ixlib=rb-4.0.3&auto=format&fit=crop&w=400&q=80',
    sourceUrl: DEFAULT_COVER_IMAGE_URL,
  },
  {
    key: 'notes',
    previewUrl:
      'https://images.unsplash.com/photo-1434030216411-0b793f4b4173?ixlib=rb-4.0.3&auto=format&fit=crop&w=400&q=80',
    sourceUrl:
      'https://images.unsplash.com/photo-1434030216411-0b793f4b4173?ixlib=rb-4.0.3&auto=format&fit=crop&w=800&q=80',
  },
  {
    key: 'team',
    previewUrl:
      'https://images.unsplash.com/photo-1519389950473-47ba0277781c?ixlib=rb-4.0.3&auto=format&fit=crop&w=400&q=80',
    sourceUrl:
      'https://images.unsplash.com/photo-1519389950473-47ba0277781c?ixlib=rb-4.0.3&auto=format&fit=crop&w=800&q=80',
  },
];

export const DEFAULT_COVER_PRESET_KEY = COVER_IMAGE_PRESETS[0].key;

export const COVER_IMAGE_ACCEPT = 'image/jpeg,image/png,image/webp';
export const COVER_IMAGE_MAX_BYTES = 5 * 1024 * 1024;

const COVER_IMAGE_MIME_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp']);
const COVER_IMAGE_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.webp'];

export const CAPACITY_MIN = 2;
export const CAPACITY_MAX = 10;
export const DEFAULT_CAPACITY = 10;
export const DESCRIPTION_MAX_LENGTH = 1000;
export const MAX_HASHTAGS = 3;
export const DEFAULT_STUDY_PERIOD_DAYS = 92;

export const VISIBILITY = {
  PUBLIC: 'PUBLIC',
  PRIVATE: 'PRIVATE',
};

const LISTED_STATUSES = ['ACTIVE', 'RECRUITING'];

export const GROUP_STATUS_LABEL = {
  RECRUITING: '모집 중',
  ACTIVE: '진행 중',
  COMPLETED: '종료',
};

export const MEMBERSHIP = {
  LEADER: 'leader',
  MEMBER: 'member',
  GUEST: 'guest',
};

export function validateCoverImageFile(file) {
  const name = (file?.name || '').toLowerCase();
  const hasValidMime = COVER_IMAGE_MIME_TYPES.has(file?.type);
  const hasValidExtension = COVER_IMAGE_EXTENSIONS.some((extension) => name.endsWith(extension));

  if (!hasValidMime && !hasValidExtension) {
    return '대표 이미지는 JPG, PNG, WEBP 파일만 업로드할 수 있습니다.';
  }

  if (file.size > COVER_IMAGE_MAX_BYTES) {
    return '대표 이미지는 5MB 이하만 업로드할 수 있습니다.';
  }

  return null;
}

export function toIsoDate(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

export function defaultStudyPeriod(today) {
  const end = new Date(today.getTime());
  end.setDate(end.getDate() + DEFAULT_STUDY_PERIOD_DAYS);
  return { startDate: toIsoDate(today), endDate: toIsoDate(end) };
}

export function countStudyDays(startDate, endDate) {
  if (!startDate || !endDate) return null;

  const start = Date.parse(`${startDate}T00:00:00Z`);
  const end = Date.parse(`${endDate}T00:00:00Z`);
  if (Number.isNaN(start) || Number.isNaN(end) || end < start) return null;

  return Math.round((end - start) / 86400000) + 1;
}

export function parseHashtags(hashtags) {
  if (!hashtags) return [];
  return hashtags
    .split(/[\s,#]+/)
    .map((tag) => tag.trim())
    .filter(Boolean);
}

export function addHashtag(tags, rawTag) {
  const [tag] = parseHashtags(rawTag);
  if (!tag || tags.includes(tag) || tags.length >= MAX_HASHTAGS) return tags;
  return [...tags, tag];
}

export function validateCreateForm(form) {
  const errors = {};

  if (!form.title.trim()) errors.title = '스터디 이름을 입력해주세요.';
  if (!form.description.trim()) errors.description = '스터디 소개를 입력해주세요.';
  if (form.description.length > DESCRIPTION_MAX_LENGTH) {
    errors.description = `스터디 소개는 ${DESCRIPTION_MAX_LENGTH}자 이하로 입력해주세요.`;
  }

  if (!form.startDate || !form.endDate) {
    errors.period = '운영 기간의 시작일과 종료일을 모두 입력해주세요.';
  } else if (form.endDate < form.startDate) {
    errors.period = '종료일은 시작일과 같거나 이후여야 합니다.';
  }

  const capacity = parseInt(form.capacity, 10);
  if (!capacity || capacity < CAPACITY_MIN) {
    errors.capacity = `스터디 정원은 최소 ${CAPACITY_MIN}명 이상이어야 합니다.`;
  } else if (capacity > CAPACITY_MAX) {
    errors.capacity = `스터디 정원은 최대 ${CAPACITY_MAX}명까지 설정할 수 있습니다.`;
  }

  return errors;
}

export function toCreatePayload(form, image) {
  return {
    title: form.title.trim(),
    hashtags: form.tags.join(','),
    description: form.description.trim(),
    startDate: form.startDate,
    endDate: form.endDate,
    capacity: parseInt(form.capacity, 10),
    isPublic: form.isPublic,
    image: image || null,
  };
}

export function toGroupCard(group, userId) {
  const currentCount = group.currentCount || 1;
  const capacity = group.capacity || DEFAULT_CAPACITY;

  return {
    id: group.id,
    title: group.title,
    description: group.description || '스터디 설명이 없습니다.',
    tags: parseHashtags(group.hashtags),
    currentCount,
    capacity,
    isPrivate: !group.isPublic,
    isFull: currentCount >= capacity,
    isMine: userId != null && Number(group.leaderId) === Number(userId),
    leaderName: group.leaderName || '방장',
    status: group.status,
    coverUrl: group.coverImageUrl || DEFAULT_COVER_IMAGE_URL,
  };
}

function matchesKeyword(card, keyword) {
  if (!keyword) return true;
  return card.title.includes(keyword) || card.tags.some((tag) => tag.includes(keyword));
}

function matchesVisibility(card, visibility) {
  if (visibility === VISIBILITY.PUBLIC) return !card.isPrivate;
  if (visibility === VISIBILITY.PRIVATE) return card.isPrivate;
  return true;
}

export function selectVisibleGroups(groups, { userId, visibility, keyword }) {
  const trimmedKeyword = (keyword || '').trim();

  return (groups || [])
    .filter((group) => LISTED_STATUSES.includes(group.status))
    .map((group) => toGroupCard(group, userId))
    .filter((card) => matchesVisibility(card, visibility))
    .filter((card) => matchesKeyword(card, trimmedKeyword))
    .sort((first, second) => second.id - first.id);
}

export function describeCardAction(card) {
  if (card.isMine) return { label: '내 스터디', disabled: false };
  if (card.isFull) return { label: '정원 마감', disabled: true };
  if (card.isPrivate) return { label: '참여 신청', disabled: false };
  return { label: '참여하기', disabled: false };
}

export function isGroupLeader(group, userId) {
  if (userId == null || group?.leaderId == null) return false;
  return Number(group.leaderId) === Number(userId);
}

export function resolveMembership(group, members, userId) {
  if (userId == null || !group) return MEMBERSHIP.GUEST;
  if (isGroupLeader(group, userId)) return MEMBERSHIP.LEADER;

  const isJoined = (members || []).some((member) => Number(member.userId) === Number(userId));
  return isJoined ? MEMBERSHIP.MEMBER : MEMBERSHIP.GUEST;
}

export function resolveMyDisplayName(user, userId) {
  return user?.displayName || user?.nickname || `User_${userId}`;
}

export function buildConnectionData(userId, displayName) {
  return JSON.stringify({ userId, clientData: displayName });
}

export function describeConnection(metadata) {
  const source = metadata || {};
  return {
    userId: source.userId ?? null,
    name: source.clientData || source.name || source.nickname || null,
  };
}

export function splitChatHistory(entries, userId) {
  const list = Array.isArray(entries) ? entries : [];

  const chat = list
    .filter((entry) => !entry.isAi && !entry.isAiQuery)
    .map((entry) => ({
      id: `history-${entry.id}`,
      serverId: entry.id == null ? null : String(entry.id),
      senderId: entry.senderId,
      senderName: entry.senderName,
      content: entry.content,
    }));

  const ai = list
    .filter((entry) => entry.isAi || entry.isAiQuery)
    .map((entry) => ({
      id: `history-${entry.id}`,
      senderName: entry.senderName,
      content: entry.content,
      isUser: Boolean(entry.isAiQuery || (entry.senderId && String(entry.senderId) === String(userId))),
    }));

  return { chat, ai };
}

export function formatElapsed(totalSeconds) {
  const safe = Math.max(0, Math.floor(totalSeconds));
  const hours = String(Math.floor(safe / 3600)).padStart(2, '0');
  const minutes = String(Math.floor((safe % 3600) / 60)).padStart(2, '0');
  const seconds = String(safe % 60).padStart(2, '0');
  return `${hours}:${minutes}:${seconds}`;
}

export function isPdfMaterial(material) {
  const contentType = (material?.contentType || '').toLowerCase();
  const fileName = (material?.originalFileName || '').toLowerCase();
  return contentType.includes('pdf') || fileName.endsWith('.pdf');
}

export const MEMBER_REMOVAL_EVENTS = [
  'PARTICIPANT_LEFT',
  'PARTICIPANT_KICKED',
  'PARTICIPANT_BANNED',
  'PARTICIPANT_DISCONNECTED',
];

export function describeMemberEvent(event, userId) {
  if (!event || !MEMBER_REMOVAL_EVENTS.includes(event.type)) return { kind: 'ignore' };

  if (String(event.targetUserId) === String(userId)) {
    const message =
      event.type === 'PARTICIPANT_KICKED'
        ? '방장에 의해 그룹스터디에서 강제 퇴장되었습니다.'
        : '그룹스터디 참여가 종료되어 화상채팅에서 나갑니다.';
    return { kind: 'self-removed', message };
  }

  return { kind: 'other-removed', targetUserId: event.targetUserId };
}
