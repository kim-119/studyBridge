// 턴(요청) 세대 가드 — 방별 활성 requestId 를 하나만 인정하고, 늦게 도착한 이전 턴/다른 턴 이벤트를 차단한다.
//  · requestId 는 브라우저가 발급(X-Request-ID)하고 Spring → AI07 가 그대로 echo 하므로 모든 이벤트의 data.requestId 로 대조 가능.
//  · turnId 는 AI07 가 발급한다. failover 시 후순위 업스트림이 새 turnId 를 만들 수 있어 identity 는 requestId, turnId 는 관측값이다.
//  · eventId 중복(재전송/reconnect)은 턴 안에서 1회만 통과시킨다.
export function createTurnGuard() {
  const active = new Map(); // roomId → requestId

  const makeRequestId = () => {
    const rand = (typeof crypto !== 'undefined' && crypto.randomUUID) ? crypto.randomUUID().replace(/-/g, '').slice(0, 12)
      : Math.random().toString(36).slice(2, 14);
    return `web-${Date.now().toString(36)}-${rand}`;
  };

  return {
    // 새 턴 시작: 이 방의 이전 turn 은 즉시 stale 이 된다.
    begin(roomId, requestId = makeRequestId()) {
      const key = String(roomId);
      active.set(key, requestId);
      const seenEventIds = new Set();
      let turnId = null;
      const token = {
        roomId: key,
        requestId,
        get turnId() { return turnId; },
        isActive: () => active.get(key) === requestId,
        // 이벤트 수용 판정: stale 턴 / 다른 requestId / 중복 eventId 는 false.
        accept(data) {
          if (active.get(key) !== requestId) return { ok: false, reason: 'stale_turn' };
          if (data && data.requestId != null && String(data.requestId) !== String(requestId)) return { ok: false, reason: 'foreign_request' };
          if (data && data.eventId != null) {
            const id = String(data.eventId);
            if (seenEventIds.has(id)) return { ok: false, reason: 'duplicate_event' };
            seenEventIds.add(id);
          }
          if (data && data.turnId != null && turnId == null) turnId = String(data.turnId);
          return { ok: true, reason: null };
        },
        end() { if (active.get(key) === requestId) active.delete(key); },
      };
      return token;
    },
    activeRequestId(roomId) { return active.get(String(roomId)) || null; },
    isActive(roomId, requestId) { return active.get(String(roomId)) === requestId; },
    invalidate(roomId) { active.delete(String(roomId)); },
    makeRequestId,
  };
}
