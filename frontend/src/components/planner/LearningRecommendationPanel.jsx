import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AlertTriangle, Check, CheckCircle2, ExternalLink, Lightbulb, RefreshCw, X } from 'lucide-react';
import { recommendationService } from '../../services/api';

/**
 * 학습 추천 패널 — 세 기능을 출처별로 구분해 보여 준다(서버 mode 기준).
 *  - USER_PLANNER_TASK : 사용자 플래너의 다음 학습 과제(Learning Task)
 *  - ROADMAP_NODE      : 로드맵 전체(선수관계 DAG·진도·숙련도) 기준 다음 단계(Learning Node)
 *  - DOCUMENT          : 원본 플래너가 없는 자료의 문서 기반 추천(로드맵 단계로 표현하지 않음)
 * 추천은 제안일 뿐이다 — [승인]을 눌러야 플래너에 등록된다. 확인이 필요한 추천은 체크 후에만 승인할 수 있다.
 * 계획 최적화(시간 부족·마감·의존·중복)는 이 패널이 아니라 'AI 계획 분석' 탭의 계획 진단이 담당한다.
 */
const MODE_META = {
  USER_PLANNER_TASK: { title: '다음 학습 과제', desc: '현재 계획의 진행 기록·교재 목차·퀴즈·오답을 근거로 다음에 할 과제를 제안합니다.' },
  ROADMAP_NODE: { title: '로드맵 다음 단계', desc: '로드맵 전체의 선수 단계 완료 여부와 숙련도(측정된 경우)를 기준으로 다음 단계를 제안합니다.' },
  DOCUMENT: { title: '문서 기반 추천', desc: '원본 플래너가 없는 자료입니다. 문서의 개념 복습·실습·심화를 제안하며 로드맵 진도와는 무관합니다.' },
};

const TYPE_LABEL = {
  NEXT_CHAPTER: '다음 장', CONCEPT_REVIEW: '개념 정리', PRACTICE: '문제 풀이·확인', PREREQUISITE_GAP: '선행 보완',
  APPLICATION: '응용', WRONG_ANSWER_REVIEW: '오답 복습', ROADMAP_NODE: '로드맵 단계',
  DOCUMENT_CONCEPT_REVIEW: '개념 복습', DOCUMENT_PRACTICE: '실습·확인', DOCUMENT_DEEP_DIVE: '심화', DOCUMENT_REVIEW: '복습',
};

const STATUS_STYLE = {
  GENERATED: null,
  ACCEPTED: { label: '승인됨', color: '#15803D', bg: '#DCFCE7' },
  COMPLETED: { label: '완료', color: '#1D4ED8', bg: '#DBEAFE' },
};

const tomorrow = () => {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

const errorOf = (e, fallback) => {
  const data = e?.response?.data || {};
  return {
    message: data.message || (e?.code === 'ECONNABORTED' ? '응답 시간이 초과되었습니다.' : fallback),
    retryable: data.retryable !== false,
    requestId: data.requestId || null,
  };
};

export default function LearningRecommendationPanel({ plannerId = null, materialId = null, onOpenPlanner }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const [itemError, setItemError] = useState({});
  const [ack, setAck] = useState({});
  const [dates, setDates] = useState({});
  const seqRef = useRef(0);

  // 원본 플래너가 연결돼 있으면 플래너 기준, 없으면 자료(문서) 기준.
  const tKind = plannerId != null ? 'planner' : materialId != null ? 'material' : null;
  const tId = plannerId != null ? plannerId : materialId;

  const run = useCallback(async (generate) => {
    if (!tKind) return;
    const seq = ++seqRef.current;
    generate ? setGenerating(true) : setLoading(true);
    setError(null);
    try {
      const res = tKind === 'planner'
        ? await (generate ? recommendationService.generateForPlanner(tId) : recommendationService.listForPlanner(tId))
        : await (generate ? recommendationService.generateForMaterial(tId) : recommendationService.listForMaterial(tId));
      if (seq !== seqRef.current) return; // 대상이 바뀌었거나 더 최근 요청이 있음 → 늦은 응답 무시
      setData(res || null);
    } catch (e) {
      if (seq !== seqRef.current) return;
      setError(errorOf(e, generate ? '추천을 만들지 못했습니다.' : '추천 목록을 불러오지 못했습니다.'));
    } finally {
      if (seq === seqRef.current) { setGenerating(false); setLoading(false); }
    }
  }, [tKind, tId]);

  useEffect(() => { setData(null); setItemError({}); setAck({}); run(false); }, [run]);

  const replaceItem = (item) => setData((prev) => prev ? { ...prev, items: prev.items.map((x) => (x.id === item.id ? item : x)) } : prev);

  const act = async (item, kind) => {
    if (busyId != null) return; // 중복 클릭 방지(서버도 조건부 UPDATE 로 1건만 처리)
    setBusyId(item.id);
    setItemError((p) => ({ ...p, [item.id]: null }));
    try {
      let res;
      if (kind === 'accept') {
        res = await recommendationService.accept(item.id, {
          plannerDate: item.type === 'ROADMAP_NODE' ? null : (dates[item.id] || tomorrow()),
          acknowledgeVerification: !!ack[item.id],
        });
      } else if (kind === 'reject') {
        res = await recommendationService.reject(item.id);
      } else {
        res = await recommendationService.complete(item.id);
      }
      if (kind === 'reject') {
        setData((prev) => prev ? { ...prev, items: prev.items.filter((x) => x.id !== item.id) } : prev);
      } else {
        replaceItem(res);
      }
    } catch (e) {
      setItemError((p) => ({ ...p, [item.id]: errorOf(e, '처리하지 못했습니다.').message }));
    } finally {
      setBusyId(null);
    }
  };

  const muted = { margin: 0, fontSize: '14px', color: 'var(--color-text-muted)', lineHeight: 1.6 };
  const meta = MODE_META[data?.mode] || MODE_META[tKind === 'material' ? 'DOCUMENT' : 'USER_PLANNER_TASK'];
  const items = Array.isArray(data?.items) ? data.items : [];
  const btn = { minHeight: '36px', padding: '6px 14px', borderRadius: '18px', fontSize: '13px', cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: '4px' };

  if (!tKind) return null;

  return (
    <div className="glass-panel animate-fade-in" data-testid="learning-recommendation-panel" style={{ padding: '22px' }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '10px', flexWrap: 'wrap', marginBottom: '10px' }}>
        <div style={{ minWidth: 0, flex: '1 1 220px' }}>
          <h3 style={{ margin: 0, fontSize: '16px', display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--color-text-main)' }}>
            <Lightbulb size={17} color="#B45309" /> {meta.title}
          </h3>
          <p style={{ ...muted, fontSize: '12.5px', marginTop: '4px' }}>{meta.desc}</p>
        </div>
        <button className="btn-outline" style={{ width: 'auto', padding: '6px 12px', fontSize: '12px', minHeight: '36px' }}
          onClick={() => run(true)} disabled={generating || loading}>
          <RefreshCw size={13} /> {generating ? '추천 만드는 중…' : items.length ? '다시 추천' : '추천 받기'}
        </button>
      </div>

      {error && (
        <div role="alert" style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', alignItems: 'center', padding: '10px 12px', borderRadius: '10px', background: '#FEF2F2', border: '1px solid #FECACA', color: '#991B1B', fontSize: '13px', marginBottom: '10px' }}>
          <span style={{ flex: '1 1 200px' }}>{error.message}{error.requestId && <span style={{ display: 'block', fontSize: '11px', opacity: 0.7, wordBreak: 'break-all' }}>요청 ID: {error.requestId}</span>}</span>
          {error.retryable && <button type="button" style={{ ...btn, border: '1px solid currentColor', background: '#fff', color: 'inherit' }} onClick={() => run(false)}>다시 시도</button>}
        </div>
      )}

      {data?.note && <p style={{ ...muted, marginBottom: '10px' }}>{data.note}</p>}
      {loading && !data && <p style={muted}>추천을 불러오는 중…</p>}
      {!loading && data && items.length === 0 && !data.note && (
        <p style={muted}>아직 추천이 없습니다. ‘추천 받기’를 누르면 현재 기록을 바탕으로 제안합니다.</p>
      )}

      <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: '12px' }}>
        {items.map((it) => {
          const st = STATUS_STYLE[it.status];
          const pending = it.status === 'GENERATED';
          const needsAck = pending && it.verificationRequired;
          return (
            <li key={it.id} data-testid="recommendation-item" style={{ border: '1px solid var(--color-border)', borderRadius: '12px', padding: '14px', background: '#fff' }}>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', alignItems: 'center', marginBottom: '6px' }}>
                <span style={{ fontSize: '11.5px', fontWeight: 700, padding: '2px 8px', borderRadius: '999px', background: '#FEF3C7', color: '#92400E' }}>{TYPE_LABEL[it.type] || it.type}</span>
                <span style={{ fontSize: '11px', padding: '2px 8px', borderRadius: '999px', background: '#F3F4F6', color: '#4B5563' }}
                  title={it.generator === 'AI' ? `AI 후보(EC2 검증 통과) · ${it.modelProvider || ''} ${it.modelName || ''}` : 'EC2 기록 기반 규칙'}>
                  {it.generator === 'AI' ? `AI${it.modelName ? ` · ${it.modelName}` : ''}` : '기록 기반'}
                </span>
                {st && <span style={{ fontSize: '11px', fontWeight: 700, padding: '2px 8px', borderRadius: '999px', background: st.bg, color: st.color }}>{st.label}</span>}
              </div>
              <div style={{ fontSize: '14.5px', fontWeight: 600, color: 'var(--color-text-main)', overflowWrap: 'anywhere', lineHeight: 1.5 }}>{it.title}</div>
              {it.reason && <p style={{ ...muted, fontSize: '13px', marginTop: '4px' }}>{it.reason}</p>}

              {Array.isArray(it.evidence) && it.evidence.length > 0 && (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginTop: '8px' }} aria-label="근거">
                  {it.evidence.map((ev, i) => (
                    <span key={i} title={`${ev.type} #${ev.id}`} style={{ fontSize: '11.5px', padding: '2px 8px', borderRadius: '6px', background: '#F9FAFB', border: '1px solid #E5E7EB', color: '#374151', maxWidth: '100%', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      근거 · {ev.label || `${ev.type} ${ev.id}`}
                    </span>
                  ))}
                </div>
              )}

              {it.verificationRequired && (
                <div style={{ marginTop: '10px', padding: '8px 10px', borderRadius: '8px', background: '#FFFBEB', border: '1px solid #FDE68A', color: '#92400E', fontSize: '12.5px', lineHeight: 1.5 }}>
                  <div style={{ display: 'flex', gap: '6px', alignItems: 'flex-start' }}><AlertTriangle size={14} style={{ flexShrink: 0, marginTop: '2px' }} /> <span>확인 필요: {it.verificationNote || '근거 데이터가 충분하지 않습니다.'}</span></div>
                  {needsAck && (
                    <label style={{ display: 'flex', gap: '6px', alignItems: 'center', marginTop: '6px', cursor: 'pointer', minHeight: '28px' }}>
                      <input type="checkbox" checked={!!ack[it.id]} onChange={(e) => setAck((p) => ({ ...p, [it.id]: e.target.checked }))} />
                      확인 사항을 검토했습니다
                    </label>
                  )}
                </div>
              )}

              {itemError[it.id] && <p role="alert" style={{ margin: '8px 0 0', fontSize: '12.5px', color: '#B91C1C' }}>{itemError[it.id]}</p>}

              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginTop: '10px', alignItems: 'center' }}>
                {pending && it.type !== 'ROADMAP_NODE' && (
                  <label style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', fontSize: '12.5px', color: 'var(--color-text-muted)' }}>
                    등록일
                    <input type="date" value={dates[it.id] || tomorrow()} onChange={(e) => setDates((p) => ({ ...p, [it.id]: e.target.value }))}
                      style={{ minHeight: '34px', borderRadius: '8px', border: '1px solid var(--color-border)', padding: '2px 6px', fontSize: '13px' }} />
                  </label>
                )}
                {pending && (
                  <>
                    <button type="button" disabled={busyId != null || (needsAck && !ack[it.id])} onClick={() => act(it, 'accept')}
                      style={{ ...btn, border: 'none', background: needsAck && !ack[it.id] ? '#D1D5DB' : 'var(--color-primary)', color: '#fff', opacity: busyId === it.id ? 0.6 : 1 }}>
                      <Check size={14} /> {busyId === it.id ? '처리 중…' : it.type === 'ROADMAP_NODE' ? '이 단계로 진행' : '플래너에 등록'}
                    </button>
                    <button type="button" disabled={busyId != null} onClick={() => act(it, 'reject')}
                      style={{ ...btn, border: '1px solid var(--color-border)', background: '#fff', color: 'var(--color-text-muted)' }}>
                      <X size={14} /> 거절
                    </button>
                  </>
                )}
                {it.status === 'ACCEPTED' && (
                  <>
                    {it.acceptedPlannerId != null && onOpenPlanner && (
                      <button type="button" onClick={() => onOpenPlanner(it.acceptedPlannerId)} style={{ ...btn, border: '1px solid var(--color-border)', background: '#fff', color: 'var(--color-text-main)' }}>
                        <ExternalLink size={14} /> 플래너 열기
                      </button>
                    )}
                    <button type="button" disabled={busyId != null} onClick={() => act(it, 'complete')}
                      style={{ ...btn, border: '1px solid #93C5FD', background: '#EFF6FF', color: '#1D4ED8' }}>
                      <CheckCircle2 size={14} /> 완료로 표시
                    </button>
                  </>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
