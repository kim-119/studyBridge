const UNNAMED_MEMBER = '이름 없음';

function memberDisplayName(member) {
  const nickname = typeof member.nickname === 'string' ? member.nickname.trim() : '';
  if (nickname) return nickname;
  const displayName = typeof member.displayName === 'string' ? member.displayName.trim() : '';
  return displayName || UNNAMED_MEMBER;
}

function isGroupLeaderMember(member, leaderId) {
  if (leaderId !== undefined && leaderId !== null) return String(member.userId) === String(leaderId);
  return member.role === 'LEADER';
}

function normalizePoints(points) {
  const value = Number(points);
  return Number.isFinite(value) ? value : 0;
}

function normalizeSeconds(seconds) {
  const value = Number(seconds);
  return Number.isFinite(value) && value > 0 ? Math.floor(value) : 0;
}

export function formatStudyTime(seconds) {
  const totalSeconds = normalizeSeconds(seconds);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  return `${hours}시간 ${minutes}분`;
}

function rosterOrder(entry) {
  if (entry.isLeader) return 0;
  if (entry.isOnline) return 1;
  return 2;
}

export function buildParticipantRoster({ members, leaderId, userId, onlineUserIds }) {
  const seenUserIds = new Set();
  const roster = [];

  (Array.isArray(members) ? members : []).forEach((member) => {
    if (member?.userId === undefined || member?.userId === null) return;
    const memberKey = String(member.userId);
    if (seenUserIds.has(memberKey)) return;
    seenUserIds.add(memberKey);

    roster.push({
      userId: member.userId,
      name: memberDisplayName(member),
      isLeader: isGroupLeaderMember(member, leaderId),
      isMe: memberKey === String(userId),
      isOnline: onlineUserIds.has(memberKey),
      points: normalizePoints(member.points),
      recentStudySeconds: normalizeSeconds(member.recentStudyTimeSeconds),
      cumulativeStudySeconds: normalizeSeconds(member.cumulativeStudyTimeSeconds),
    });
  });

  return roster.sort((left, right) => rosterOrder(left) - rosterOrder(right));
}
