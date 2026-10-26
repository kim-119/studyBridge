// 방별 진행 중 스트림의 AbortController 레지스트리 — Stop/새 질문/방 전환/모드 전환/언마운트에서 한 지점으로 취소한다.
//  abort() → fetch 연결 종료 → Spring MVC cancel → WebClient 구독 취소 → AI07 절단 감시(§16 취소 체인의 브라우저 끝).
export function createCancelRegistry() {
  const entries = new Map(); // roomId → { controller, requestId, cancelled, reason }
  const registry = {
    register(roomId, controller, requestId) {
      const key = String(roomId);
      const entry = { controller, requestId, cancelled: false, reason: null };
      entries.set(key, entry);
      return entry;
    },
    // 같은 requestId 가 아직 등록돼 있을 때만 해제(늦은 finally 가 새 턴 등록을 지우지 않게).
    release(roomId, requestId) {
      const key = String(roomId);
      const e = entries.get(key);
      if (e && e.requestId === requestId) entries.delete(key);
    },
    cancel(roomId, reason = 'cancel') {
      const key = String(roomId);
      const e = entries.get(key);
      if (!e || e.cancelled) return false;
      e.cancelled = true;
      e.reason = reason;
      try { e.controller.abort(reason); } catch { /* already aborted */ }
      entries.delete(key);
      return true;
    },
    cancelAll(reason = 'cancel_all') {
      let n = 0;
      for (const key of Array.from(entries.keys())) { if (registry.cancel(key, reason)) n += 1; }
      return n;
    },
    has(roomId) { return entries.has(String(roomId)); },
    get(roomId) { return entries.get(String(roomId)) || null; },
    get size() { return entries.size; },
  };
  return registry;
}
