import { useCallback, useEffect, useRef, useState } from 'react';
import { mindmapService } from '../services/api';
import { semanticRequestKey, SEMANTIC_STATUS } from '../utils/graph/semanticGraphMerge';

// ─────────────────────────────────────────────────────────────────────────────
// 마인드맵 화면 진입 시(LAZY) Spring → AI07 Semantic Graph 를 받아오는 훅.
//  · 상태: idle | loading | ok | degraded | failed. FAILED 는 명시적 실패(폴백 그래프 없음).
//  · 같은 (roomId, question, answers) 는 모듈 캐시로 재요청하지 않는다(화면 재진입/재렌더 시 GPU LLM 재호출 방지).
//    서버도 Redis fingerprint 캐시를 갖고 있어 새 탭에서도 재생성되지 않는다.
//  · 늦게 도착한 이전 요청 응답은 requestSeq 로 폐기한다.
// ─────────────────────────────────────────────────────────────────────────────
const memoryCache = new Map(); // requestKey → semantic response (OK/DEGRADED 만)
const MAX_CACHE = 40;

export function clearSemanticMindmapCache() { memoryCache.clear(); }

export function useSemanticMindmap({ roomId, question, answers, enabled = true }) {
  const [state, setState] = useState('idle');
  const [semantic, setSemantic] = useState(null);
  const [reason, setReason] = useState('');
  const seqRef = useRef(0);
  const [refreshTick, setRefreshTick] = useState(0);
  const forceRef = useRef(false);

  const key = semanticRequestKey(roomId, question, answers);
  const answerCount = Array.isArray(answers) ? answers.length : 0;

  useEffect(() => {
    if (!enabled || roomId == null || answerCount === 0) {
      // 계약: answers 최소 1개. 답변이 없으면 요청 자체를 보내지 않고 EMPTY_ANSWER 로 명시한다.
      setState(answerCount === 0 && enabled ? 'failed' : 'idle');
      setSemantic(null);
      setReason(answerCount === 0 && enabled ? 'EMPTY_ANSWER' : '');
      return undefined;
    }
    const force = forceRef.current;
    forceRef.current = false;
    if (!force && memoryCache.has(key)) {
      const cached = memoryCache.get(key);
      setSemantic(cached);
      setState(cached.status === SEMANTIC_STATUS.DEGRADED ? 'degraded' : 'ok');
      setReason(cached.degradedReason || '');
      return undefined;
    }
    const seq = seqRef.current + 1;
    seqRef.current = seq;
    let alive = true;
    setState('loading');
    setReason('');
    (async () => {
      try {
        const res = await mindmapService.getSemanticGraph({ roomId, question, answers, forceRefresh: force });
        if (!alive || seq !== seqRef.current) return;
        const status = String(res?.status || '').toUpperCase();
        if (status === SEMANTIC_STATUS.OK || status === SEMANTIC_STATUS.DEGRADED) {
          if (memoryCache.size >= MAX_CACHE) memoryCache.delete(memoryCache.keys().next().value);
          memoryCache.set(key, res);
          setSemantic(res);
          setState(status === SEMANTIC_STATUS.DEGRADED ? 'degraded' : 'ok');
          setReason(res.degradedReason || '');
        } else {
          // 계약상 200 본문에 FAILED 는 오지 않지만, 오더라도 성공으로 위장하지 않는다.
          setSemantic(null);
          setState('failed');
          setReason(res?.degradedReason || 'FAILED');
        }
      } catch (e) {
        if (!alive || seq !== seqRef.current) return;
        // Spring 은 AI07 FAILED 를 실제 HTTP 상태로 내려준다: 422(EMPTY_ANSWER/NO_VALID_CONCEPTS) / 502(INTERNAL_ERROR 등) / 504(TIMEOUT) / 503.
        // 본문(GlobalExceptionHandler): { status, code, message, retryable, upstreamCode }.
        const http = e?.response?.status;
        const data = e?.response?.data || {};
        console.error('[Mindmap] semantic graph 요청 실패', http, data.code, data.upstreamCode);
        setSemantic(null);
        setState('failed');
        setReason(data.upstreamCode || data.code || (http ? `HTTP_${http}` : 'NETWORK_ERROR'));
      }
    })();
    return () => { alive = false; };
  }, [key, roomId, answerCount, enabled, refreshTick]); // eslint-disable-line react-hooks/exhaustive-deps

  const retry = useCallback((force = true) => {
    forceRef.current = !!force;
    if (force) memoryCache.delete(key);
    setRefreshTick((t) => t + 1);
  }, [key]);

  return { state, semantic, reason, retry };
}
