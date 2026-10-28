// 학습리포트 타이머의 서버 세션 해석. 서버 timer 세션(TimerDTO.Response)이 source of truth 다.
//  · 활성 세션(startTime 있고 endTime 없음)이 있을 때만 실행 중으로 본다. 앱 시작·화면 이동만으로는 실행하지 않는다.
//  · 개인 세션(groupStudyId 없음)만 이 화면이 heartbeat 한다. 그룹 세션은 스터디룸(웹)이 heartbeat 의 주인이라
//    여기서 heartbeat 하면 방을 떠난 뒤에도 그룹 출석이 쌓이므로 서버 상태만 다시 읽는다.
//  · 경과 시간은 서버 시각끼리의 차(lastHeartbeatAt − startTime)를 앵커로 삼고 그 뒤는 클라이언트 시계로만 더한다.

export const STUDY_HEARTBEAT_INTERVAL_MS = 30 * 1000;

export const SESSION_KIND = Object.freeze({
  PERSONAL: 'personal',
  GROUP: 'group',
});

const SEOUL_OFFSET_MS = 9 * 60 * 60 * 1000;
const LOCAL_DATE_TIME = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d+))?$/;

// 서버 LocalDateTime(서울 시각, 오프셋 없음) → epoch ms. 배열 직렬화([y,m,d,h,mi,s])와 오프셋 표기도 허용한다.
export function parseServerDateTime(value) {
  if (value == null || value === '') return null;
  if (typeof value === 'number') return value;
  if (Array.isArray(value)) {
    if (value.length < 5) return null;
    return Date.UTC(value[0], value[1] - 1, value[2], value[3], value[4], value[5] || 0) - SEOUL_OFFSET_MS;
  }

  const text = String(value);
  const match = text.match(LOCAL_DATE_TIME);
  if (match) {
    const millis = Number((match[7] || '0').slice(0, 3).padEnd(3, '0'));
    return (
      Date.UTC(+match[1], +match[2] - 1, +match[3], +match[4], +match[5], +(match[6] || 0), millis) - SEOUL_OFFSET_MS
    );
  }

  const parsed = Date.parse(text);
  return Number.isNaN(parsed) ? null : parsed;
}

function normalizeGroupId(groupStudyId) {
  return groupStudyId == null || groupStudyId === '' ? null : String(groupStudyId);
}

// 서버 응답 → 실행 중 세션 상태. 활성 세션이 아니면 null(= 화면에 실행 중으로 표시하지 않음).
export function sessionFromServer(session, clientNowMs = Date.now()) {
  if (!session || typeof session !== 'object') return null;
  if (!session.startTime || session.endTime) return null;

  const startedAt = parseServerDateTime(session.startTime);
  if (startedAt == null) return null;

  const heartbeatAt = parseServerDateTime(session.lastHeartbeatAt);
  // heartbeat 기록이 있으면 서버 시각끼리 계산해 기기 시계·타임존 오차를 없앤다. 없으면(구 세션) 시작 시각 기준으로 추정한다.
  const elapsedMs = heartbeatAt != null ? heartbeatAt - startedAt : clientNowMs - startedAt;
  const groupStudyId = normalizeGroupId(session.groupStudyId);

  return {
    sessionId: session.id ?? null,
    kind: groupStudyId == null ? SESSION_KIND.PERSONAL : SESSION_KIND.GROUP,
    groupStudyId,
    elapsedMs: Math.max(0, elapsedMs),
    anchoredAt: clientNowMs,
  };
}

export function elapsedSecondsOf(running, clientNowMs = Date.now()) {
  if (!running) return 0;
  return Math.max(0, Math.floor((running.elapsedMs + (clientNowMs - running.anchoredAt)) / 1000));
}

// 주기 확인 결과가 화면이 들고 있는 세션과 같은 세션인지. 다르면(종료·자동 종료·다른 컨텍스트) 서버 상태로 다시 불러온다.
export function isSameRunningSession(running, serverSession) {
  const next = sessionFromServer(serverSession);
  if (!running || !next) return false;
  if (next.groupStudyId !== running.groupStudyId) return false;
  if (running.sessionId != null && next.sessionId != null) return String(running.sessionId) === String(next.sessionId);
  return true;
}

// 실행 중 30초 주기 확인. 개인 세션은 heartbeat(진행분 크레딧 + 무응답 자동 종료 기준 갱신), 그룹 세션은 조회만 한다.
export async function checkRunningSession(running, { heartbeat, getCurrentSession }) {
  if (!running) return false;
  const serverSession = running.kind === SESSION_KIND.PERSONAL ? await heartbeat() : await getCurrentSession();
  return isSameRunningSession(running, serverSession);
}

export function describeRunningSession(running) {
  if (!running) return '시작을 누르면 개인 학습 시간이 기록됩니다.';
  if (running.kind === SESSION_KIND.GROUP) {
    return '그룹 스터디룸에서 진행 중인 세션입니다. 개인 타이머를 시작하면 이 세션은 종료됩니다.';
  }
  return '종료를 누르면 오늘의 학습 시간에 누적됩니다.';
}
