import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, Loader2, Monitor, RefreshCw, ScanSearch, Send, ShieldCheck, ShieldOff, X } from 'lucide-react';
import { groupService } from '../../services/api';
import RichText from '../studymate/RichText';
import { ToggleSwitch } from './ToggleSwitch';
import { captureShareFrame, newClientRequestId, ScreenCaptureError } from '../../utils/screenAiCapture';
import {
  describeScreenAiError, formatBytes, mergeScreenAiShares, pendingHint, pickDefaultShare, SCREEN_AI_EXAMPLES,
  SCREEN_AI_MAX_QUESTION, streamIdOf, validateQuestion,
} from '../../utils/screenAi';

// 채팅 드로어의 "AI 화면 분석" 탭.
//  · 질문하는 순간 선택한 공유 화면의 현재 프레임 1장만 캡처해(긴 변 1280px·JPEG 0.75) Spring 으로 보낸다(연속 스트림 없음).
//  · 공유자 동의(opt-in)·권한·요청 제한은 서버가 최종 판정한다. 여기 표시는 서버 목록(GET /screen-ai/shares) 기준 안내다.
//  · 답변·질문은 이 탭의 메모리에만 있다(서버·브라우저 저장 없음). 방을 나가면 사라진다.
//  · 탭을 바꿔도 진행 중인 분석이 끊기지 않도록 StudyRoom 은 이 패널을 숨김 상태로 계속 마운트한다.
// shares: StudyRoom screenShares · myConsent: { connectionId, allowed, busy } (이 탭의 내 공유) · onToggleMyConsent(allowed)

const card = { backgroundColor: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)', borderRadius: '12px' };

function ShareOption({ share, selected, onSelect, disabled }) {
  const tone = share.analyzable ? '#34D399' : share.known ? '#FBBF24' : '#94A3B8';
  const status = share.isOwnUser ? '내 화면 · 분석 가능'
    : !share.known ? '공유자 동의 확인 중…'
      : share.aiConsent ? 'AI 분석 허용됨' : '공유자가 AI 분석을 허용하지 않음';
  return (
    <button
      type="button"
      data-testid="screen-ai-share"
      data-connection-id={share.connectionId}
      data-analyzable={share.analyzable ? 'true' : 'false'}
      aria-pressed={selected}
      disabled={disabled}
      onClick={() => onSelect(share.connectionId)}
      style={{
        ...card, display: 'flex', alignItems: 'center', gap: '10px', padding: '10px 12px', textAlign: 'left', width: '100%', cursor: disabled ? 'default' : 'pointer',
        border: `1px solid ${selected ? 'rgba(96,165,250,0.85)' : 'rgba(255,255,255,0.08)'}`,
        backgroundColor: selected ? 'rgba(59,130,246,0.16)' : 'rgba(255,255,255,0.03)', color: '#E5E7EB', opacity: disabled && !selected ? 0.6 : 1,
      }}
    >
      <span style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 30, height: 30, borderRadius: 8, backgroundColor: 'rgba(96,165,250,0.15)', flexShrink: 0 }}>
        <Monitor size={16} color="#93C5FD" />
      </span>
      <span style={{ flex: 1, minWidth: 0 }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px', fontWeight: 800 }}>
          <span style={{ fontSize: '11px', fontWeight: 800, color: '#93C5FD', backgroundColor: 'rgba(59,130,246,0.18)', borderRadius: 6, padding: '1px 6px', flexShrink: 0 }}>화면 {share.index}</span>
          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{share.isMine ? '내 화면' : `${share.name}님의 화면`}</span>
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: '5px', marginTop: '3px', fontSize: '11.5px', color: tone }}>
          {share.analyzable ? <ShieldCheck size={12} /> : <ShieldOff size={12} />}
          {status}
        </span>
      </span>
      <span aria-hidden="true" style={{ width: 14, height: 14, borderRadius: '50%', border: `2px solid ${selected ? '#60A5FA' : 'rgba(255,255,255,0.25)'}`, backgroundColor: selected ? '#60A5FA' : 'transparent', flexShrink: 0 }} />
    </button>
  );
}

function HistoryItem({ item }) {
  const meta = [
    item.image?.width && item.image?.height ? `${item.image.width}×${item.image.height}` : null,
    item.image?.bytes ? formatBytes(item.image.bytes) : null,
    Number.isFinite(item.latencyMs) ? `${(item.latencyMs / 1000).toFixed(1)}초` : null,
  ].filter(Boolean).join(' · ');
  return (
    <div data-testid="screen-ai-answer" data-connection-id={item.connectionId} style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
      <div style={{ alignSelf: 'flex-end', maxWidth: '88%', backgroundColor: 'rgba(59,130,246,0.22)', border: '1px solid rgba(96,165,250,0.35)', color: '#F3F4F6', borderRadius: '12px 12px 4px 12px', padding: '8px 12px', fontSize: '13px', lineHeight: 1.5, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
        <div style={{ fontSize: '11px', color: '#BFDBFE', marginBottom: '2px' }}>화면 {item.shareIndex} · {item.shareName}</div>
        {item.question}
      </div>
      <div style={{ ...card, alignSelf: 'stretch', padding: '10px 12px', color: '#E5E7EB', fontSize: '13px', lineHeight: 1.6, wordBreak: 'break-word' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', fontWeight: 800, color: '#A7F3D0', marginBottom: '6px' }}>
          <ScanSearch size={14} /> AI 화면 분석
        </div>
        <div data-testid="screen-ai-answer-text"><RichText text={item.answer} /></div>
        {meta && <div style={{ marginTop: '8px', fontSize: '11px', color: '#64748B' }}>캡처 {meta}</div>}
      </div>
    </div>
  );
}

export default function ScreenAiPanel({ groupId, shares, stageSelectedId, onFocusShare, visible, consentNonce, myConsent, onToggleMyConsent }) {
  const [server, setServer] = useState(null);
  const [serverError, setServerError] = useState(null);
  const [selectedId, setSelectedId] = useState(null);
  const [question, setQuestion] = useState('');
  const [pending, setPending] = useState(null);
  const [history, setHistory] = useState([]);
  const [notice, setNotice] = useState(null);
  const [now, setNow] = useState(() => Date.now());
  const busyRef = useRef(false);
  const inflightRef = useRef(null); // { controller, clientRequestId, connectionId, reason }
  const mountedRef = useRef(true);
  const listRef = useRef(null);

  const merged = useMemo(() => mergeScreenAiShares(shares, server?.shares || null), [shares, server]);
  const shareKey = (shares || []).map((s) => `${s.connectionId}:${streamIdOf(s.streamManager) || ''}`).join('|');
  const selected = merged.find((s) => s.connectionId === selectedId) || null;
  const mine = merged.find((s) => s.isMine) || null;

  const refresh = useCallback(async () => {
    if (!groupId) return;
    try {
      const data = await groupService.getScreenAiShares(groupId);
      if (!mountedRef.current) return;
      setServer(data);
      setServerError(null);
    } catch (e) {
      if (mountedRef.current) setServerError(describeScreenAiError(e).message);
    }
  }, [groupId]);

  // 탭이 보이는 동안: 화면공유 구성·동의 신호가 바뀌면 즉시, 공유가 있으면 10초마다 서버 상태를 다시 읽는다.
  useEffect(() => {
    if (!visible || !groupId) return undefined;
    refresh();
    if (!shareKey) return undefined;
    const t = setInterval(refresh, 10000);
    return () => clearInterval(t);
  }, [visible, groupId, shareKey, consentNonce, myConsent?.allowed, refresh]);

  useEffect(() => {
    const next = pickDefaultShare(merged, selectedId, stageSelectedId);
    if (next !== selectedId) setSelectedId(next);
  }, [merged, selectedId, stageSelectedId]);

  const cancelInflight = useCallback((reason) => {
    const a = inflightRef.current;
    if (!a || a.reason) return;
    a.reason = reason;
    a.controller.abort();
    groupService.cancelScreenAnalysis(groupId, a.clientRequestId).catch(() => { /* 이미 끝났거나 서버가 끊음 */ });
  }, [groupId]);

  // 분석 중인 화면공유가 끝나면 요청을 취소하고 알린다(공유가 끝난 뒤의 답변은 의미가 없다).
  useEffect(() => {
    if (pending && !merged.some((s) => s.connectionId === pending.connectionId)) cancelInflight('gone');
  }, [merged, pending, cancelInflight]);

  useEffect(() => {
    if (!pending) return undefined;
    setNow(Date.now());
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [pending]);

  useEffect(() => () => {
    mountedRef.current = false;
    const a = inflightRef.current;
    if (a && !a.reason) {
      a.reason = 'unmount';
      a.controller.abort();
      groupService.cancelScreenAnalysis(groupId, a.clientRequestId).catch(() => {});
    }
  }, [groupId]);

  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [history.length, pending?.phase]);

  const selectShare = (connectionId) => {
    if (busyRef.current) return;
    setSelectedId(connectionId);
    setNotice(null);
    onFocusShare?.(connectionId); // 스테이지도 같은 화면을 보여 준다(캡처도 그 <video> 에서 바로 한다)
  };

  const ask = async (override) => {
    if (busyRef.current) return; // 중복 클릭 방지(상태 반영 전 연타 포함)
    const q = String(override ?? question).trim();
    const invalid = validateQuestion(q, server?.limits?.maxQuestionChars || SCREEN_AI_MAX_QUESTION);
    if (invalid) { setNotice({ kind: 'client', message: invalid }); return; }
    if (server && server.enabled === false) { setNotice({ kind: 'server', message: 'AI 화면 분석 기능이 지금은 꺼져 있습니다.' }); return; }
    const share = merged.find((s) => s.connectionId === selectedId);
    if (!share) { setNotice({ kind: 'client', message: '분석할 화면을 먼저 선택해 주세요.' }); return; }
    if (!share.analyzable) {
      setNotice({ kind: 'consent', message: share.known ? `${share.name}님이 이 화면의 AI 분석을 허용하지 않았어요. 공유자에게 'AI 분석 허용'을 요청해 주세요.` : '공유자 동의를 확인하는 중이에요. 잠시 후 다시 시도해 주세요.' });
      if (!share.known) refresh();
      return;
    }
    busyRef.current = true;
    const clientRequestId = newClientRequestId();
    const controller = new AbortController();
    const inflight = { controller, clientRequestId, connectionId: share.connectionId, reason: null };
    inflightRef.current = inflight;
    const base = { id: clientRequestId, connectionId: share.connectionId, shareName: share.isMine ? '내 화면' : share.name, shareIndex: share.index, question: q, startedAt: Date.now() };
    setNotice(null);
    setPending({ ...base, phase: 'capturing' });
    try {
      const frame = await captureShareFrame(share.streamManager);
      if (inflight.reason) throw Object.assign(new Error('canceled'), { code: 'ERR_CANCELED' });
      setPending((p) => (p && p.id === clientRequestId ? { ...p, phase: 'analyzing', frame } : p));
      const res = await groupService.analyzeScreen(groupId, {
        connectionId: share.connectionId,
        streamId: streamIdOf(share.streamManager) || share.streamId,
        question: q,
        image: frame.base64,
        mime: frame.mime,
        clientRequestId,
      }, { signal: controller.signal });
      if (!mountedRef.current) return;
      setHistory((h) => [...h, {
        ...base,
        shareName: res?.sharer?.isMine ? '내 화면' : (res?.sharer?.name || base.shareName),
        answer: res?.answer || '',
        latencyMs: Number(res?.latencyMs),
        image: res?.image || { width: frame.width, height: frame.height, bytes: frame.bytes },
        at: Date.now(),
      }]);
      setQuestion((cur) => (cur.trim() === q ? '' : cur));
    } catch (e) {
      if (!mountedRef.current) return;
      let view = describeScreenAiError(e);
      if (inflight.reason === 'gone') view = { kind: 'gone', code: 'SCREEN_GONE', message: '화면공유가 종료되어 분석을 취소했습니다.', retryable: false };
      else if (view.kind === 'cancelled') view = { ...view, retryable: true };
      if (!(e instanceof ScreenCaptureError)) console.warn('[ScreenAI] analyze failed', { code: view.code, kind: view.kind });
      setNotice({ ...view, question: q });
      if (view.kind === 'consent' || view.kind === 'gone') refresh();
    } finally {
      if (inflightRef.current === inflight) inflightRef.current = null;
      busyRef.current = false;
      if (mountedRef.current) setPending(null);
    }
  };

  const elapsed = pending ? Math.max(0, Math.floor((now - pending.startedAt) / 1000)) : 0;
  const maxChars = server?.limits?.maxQuestionChars || SCREEN_AI_MAX_QUESTION;
  const canAsk = !pending && !!selected && !!question.trim();
  const noticeTone = notice?.kind === 'cancelled' ? '#CBD5E1' : notice?.kind === 'consent' || notice?.kind === 'busy' ? '#FCD34D' : '#FCA5A5';

  return (
    <div data-testid="screen-ai-panel" style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
      <div ref={listRef} className="custom-scrollbar" style={{ flex: 1, minHeight: 0, overflowY: 'auto', overscrollBehavior: 'contain', padding: '16px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
        <div style={{ ...card, padding: '10px 12px', fontSize: '12px', color: '#CBD5E1', lineHeight: 1.55 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontWeight: 800, color: '#93C5FD', marginBottom: '4px' }}>
            <ScanSearch size={14} /> 공유 화면을 AI에게 물어보세요
          </div>
          질문하는 순간의 화면 <b>한 장</b>만 분석에 쓰고 저장하지 않아요. 다른 참여자의 화면은 공유자가 <b>AI 분석 허용</b>을 켠 경우에만 분석할 수 있어요.
        </div>

        {mine && (
          <div data-testid="screen-ai-my-consent" style={{ ...card, padding: '10px 12px', display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: '13px', fontWeight: 800, color: '#F3F4F6' }}>내 화면 AI 분석 허용</div>
              <div style={{ fontSize: '11.5px', color: '#94A3B8', marginTop: '2px' }}>
                {myConsent?.allowed ? '다른 참여자가 내 공유 화면을 AI로 분석할 수 있어요.' : '꺼져 있으면 다른 참여자는 내 화면을 분석할 수 없어요(나는 언제나 가능).'}
              </div>
            </div>
            <ToggleSwitch checked={!!myConsent?.allowed} disabled={!!myConsent?.busy} onChange={(v) => onToggleMyConsent?.(v)} label="내 화면 AI 분석 허용" />
          </div>
        )}

        {merged.length === 0 ? (
          <div data-testid="screen-ai-empty" style={{ ...card, padding: '18px 14px', textAlign: 'center', color: '#94A3B8', fontSize: '13px', lineHeight: 1.6 }}>
            <Monitor size={22} color="#64748B" style={{ marginBottom: '6px' }} />
            <div>지금 공유 중인 화면이 없어요.</div>
            <div style={{ fontSize: '12px' }}>누군가 화면을 공유하면 여기에서 골라 질문할 수 있어요.</div>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            <div style={{ fontSize: '12px', fontWeight: 800, color: '#9CA3AF' }}>분석할 화면 ({merged.length})</div>
            {merged.map((s) => (
              <ShareOption key={s.connectionId} share={s} selected={s.connectionId === selectedId} onSelect={selectShare} disabled={!!pending} />
            ))}
            {server && server.viewerConnected === false && (
              <div style={{ fontSize: '11.5px', color: '#FCD34D' }}>화상통화 연결이 끝난 상태예요. 다시 연결되면 분석할 수 있어요.</div>
            )}
            {serverError && (
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '11.5px', color: '#FCA5A5' }}>
                <AlertTriangle size={12} /> 동의 상태를 불러오지 못했어요. {serverError}
                <button type="button" onClick={refresh} style={{ background: 'none', border: 'none', color: '#93C5FD', cursor: 'pointer', fontSize: '11.5px', padding: 0 }}>다시 확인</button>
              </div>
            )}
          </div>
        )}

        {history.map((item) => <HistoryItem key={item.id} item={item} />)}

        {pending && (
          <div data-testid="screen-ai-pending" data-phase={pending.phase} style={{ ...card, padding: '10px 12px', display: 'flex', alignItems: 'center', gap: '10px' }}>
            <Loader2 size={16} color="#93C5FD" className="animate-spin" style={{ flexShrink: 0 }} />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: '13px', color: '#E5E7EB', fontWeight: 700 }}>{pendingHint(pending.phase, elapsed)}</div>
              <div style={{ fontSize: '11.5px', color: '#94A3B8', marginTop: '2px' }}>
                화면 {pending.shareIndex} · {pending.shareName} · {elapsed}초
                {pending.frame ? ` · 캡처 ${pending.frame.width}×${pending.frame.height} ${formatBytes(pending.frame.bytes)}` : ''}
              </div>
            </div>
            <button type="button" data-testid="screen-ai-cancel" onClick={() => cancelInflight('user')} style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', padding: '6px 10px', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.16)', background: 'rgba(255,255,255,0.05)', color: '#E5E7EB', fontSize: '12px', fontWeight: 700, cursor: 'pointer', flexShrink: 0 }}>
              <X size={13} /> 취소
            </button>
          </div>
        )}
      </div>

      <div style={{ borderTop: '1px solid rgba(255,255,255,0.06)', padding: '12px 16px', backgroundColor: '#0F172A', display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {notice && (
          <div data-testid="screen-ai-notice" data-kind={notice.kind} data-code={notice.code || ''} role="status" style={{ display: 'flex', alignItems: 'flex-start', gap: '8px', fontSize: '12.5px', color: noticeTone, lineHeight: 1.5 }}>
            <AlertTriangle size={14} style={{ flexShrink: 0, marginTop: '2px' }} />
            <span style={{ flex: 1 }}>{notice.message}{notice.retryAfterSeconds ? ` (${notice.retryAfterSeconds}초 뒤 다시 시도)` : ''}</span>
            {notice.retryable && notice.question && !pending && (
              <button type="button" data-testid="screen-ai-retry" onClick={() => ask(notice.question)} style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', background: 'none', border: 'none', color: '#93C5FD', cursor: 'pointer', fontSize: '12px', fontWeight: 700, padding: 0, flexShrink: 0 }}>
                <RefreshCw size={12} /> 다시 시도
              </button>
            )}
            <button type="button" aria-label="안내 닫기" onClick={() => setNotice(null)} style={{ background: 'none', border: 'none', color: '#64748B', cursor: 'pointer', padding: 0, display: 'flex', flexShrink: 0 }}><X size={13} /></button>
          </div>
        )}
        {merged.length > 0 && !question && !pending && (
          <div style={{ display: 'flex', gap: '6px', overflowX: 'auto', paddingBottom: '2px' }} className="custom-scrollbar">
            {SCREEN_AI_EXAMPLES.map((ex) => (
              <button key={ex} type="button" data-testid="screen-ai-example" onClick={() => setQuestion(ex)} style={{ flexShrink: 0, padding: '5px 10px', borderRadius: '999px', border: '1px solid rgba(96,165,250,0.35)', background: 'rgba(59,130,246,0.1)', color: '#BFDBFE', fontSize: '12px', cursor: 'pointer', whiteSpace: 'nowrap' }}>
                {ex}
              </button>
            ))}
          </div>
        )}
        <div style={{ display: 'flex', gap: '8px', alignItems: 'flex-end' }}>
          <textarea
            data-testid="screen-ai-question"
            value={question}
            maxLength={maxChars}
            rows={2}
            disabled={merged.length === 0}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); if (canAsk) ask(); }
            }}
            placeholder={merged.length === 0 ? '공유 중인 화면이 없어요' : selected ? `${selected.isMine ? '내 화면' : `${selected.name}님의 화면`}에 대해 질문하기` : '분석할 화면을 선택하세요'}
            style={{ flex: 1, minWidth: 0, resize: 'none', backgroundColor: '#1F2937', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '10px', padding: '9px 11px', color: '#F3F4F6', fontSize: '14px', lineHeight: 1.45, outline: 'none', fontFamily: 'inherit' }}
          />
          <button
            type="button"
            data-testid="screen-ai-ask"
            onClick={() => ask()}
            disabled={!canAsk}
            aria-busy={pending ? 'true' : 'false'}
            title="현재 화면을 캡처해 질문하기"
            style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: '6px', height: '42px', padding: '0 14px', borderRadius: '10px', border: 'none', backgroundColor: canAsk ? '#3B82F6' : '#374151', color: canAsk ? '#fff' : '#9CA3AF', fontSize: '13px', fontWeight: 800, cursor: canAsk ? 'pointer' : 'not-allowed', flexShrink: 0 }}
          >
            {pending ? <Loader2 size={15} className="animate-spin" /> : <Send size={15} />}
            {pending ? '분석 중' : '질문'}
          </button>
        </div>
        <div style={{ fontSize: '11px', color: '#64748B', textAlign: 'right' }}>{question.length}/{maxChars}</div>
      </div>
    </div>
  );
}
