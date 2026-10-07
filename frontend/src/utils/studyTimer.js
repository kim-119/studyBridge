// 그룹스터디 실시간 학습 타이머(표시 전용). 서버 timer 세션(TimerDTO.Response)이 source of truth 다.
//  · 서버가 LocalDateTime(startTime / lastHeartbeatAt)을 서버 로컬 시각으로 내리므로, 클라이언트 시계·타임존과 무관하게
//    "lastHeartbeatAt − startTime"(둘 다 서버 시각) 을 앵커 경과시간으로 삼고, 그 이후는 클라이언트 단조 시계로만 더한다.
//  · 새로고침/재입장: sync 가 기존 활성 세션(resumed=true)을 돌려주므로 00:00 이 아니라 실제 경과로 복원된다.
//  · heartbeat 응답(30초)마다 앵커를 갱신해 드리프트를 보정한다. 저장/통계는 서버 heartbeat 원장이 담당(프론트 미저장).

const parseServerLocal = (v) => {
  if (!v) return null;
  if (typeof v === 'number') return v;
  const s = String(v);
  // "2026-10-07T11:36:08" / "…08.123" / 배열([y,m,d,h,mi,s]) 모두 허용. 타임존 표기가 있으면 Date 가 처리.
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d+))?$/);
  if (m) return Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +(m[6] || 0), +((m[7] || '0').slice(0, 3).padEnd(3, '0')));
  const t = Date.parse(s);
  return Number.isNaN(t) ? null : t;
};
const parseAny = (v) => (Array.isArray(v) && v.length >= 5
  ? Date.UTC(v[0], v[1] - 1, v[2], v[3], v[4], v[5] || 0)
  : parseServerLocal(v));

// 세션 응답 → 앵커 { elapsedMs, anchoredAt(clientNow), sessionId }. 활성 세션이 아니면 null.
export const anchorFromSession = (session, clientNowMs = Date.now()) => {
  if (!session || !session.startTime) return null;
  if (session.status && String(session.status).toUpperCase() !== 'RUNNING' && String(session.status).toUpperCase() !== 'ACTIVE') {
    if (session.endTime) return null;
  }
  const start = parseAny(session.startTime);
  const hb = parseAny(session.lastHeartbeatAt);
  if (start == null) return null;
  // heartbeat 가 아직 없으면(방금 시작) 경과 0 으로 시작.
  const elapsedMs = hb != null ? Math.max(0, hb - start) : 0;
  return { elapsedMs, anchoredAt: clientNowMs, sessionId: session.id ?? null };
};

// 앵커 + 현재 클라이언트 시각 → 표시 경과(초).
export const elapsedSecondsFrom = (anchor, clientNowMs = Date.now()) => {
  if (!anchor) return 0;
  return Math.max(0, Math.floor((anchor.elapsedMs + (clientNowMs - anchor.anchoredAt)) / 1000));
};

// 00:00:00 형식(기존 학습 시간 표기와 호환되는 HH:MM:SS).
export const formatHMS = (totalSeconds) => {
  const s = Math.max(0, Math.floor(Number(totalSeconds) || 0));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return [h, m, sec].map((n) => String(n).padStart(2, '0')).join(':');
};
