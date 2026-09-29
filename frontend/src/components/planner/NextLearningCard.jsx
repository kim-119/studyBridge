import React, { useCallback, useEffect, useState } from 'react';
import { ArrowRight, CheckCircle2, Clock, Info, RefreshCw } from 'lucide-react';
import { plannerService } from '../../services/api';

/**
 * 다음 학습 추천(DB 기반 · 결정적 규칙). GET /api/planners/{plannerId}/next-learning
 *  - 서버는 이미 존재하는 플래너 중 다음 순서(같은 로드맵 week/day → 같은 과목의 다음 사용자 플래너)만 고른다.
 *  - AI 호출 없음. 자동 이동/자동 생성 없음 — "다음 학습 보기" 버튼을 눌렀을 때만 onOpen(next) 로 이동한다.
 *  - status: READY | IN_PROGRESS(현재 계획 미완료) | NO_NEXT | NO_DATA
 */
export default function NextLearningCard({ plannerId, onOpen }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    if (plannerId == null) { setData(null); return; }
    setLoading(true);
    setError('');
    try {
      const res = await plannerService.getNextLearning(plannerId);
      setData(res || null);
    } catch (e) {
      setError(e?.response?.data?.reason || '다음 학습 정보를 불러오지 못했습니다.');
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [plannerId]);

  useEffect(() => { load(); }, [load]);

  const Wrap = ({ children, right }) => (
    <div className="glass-panel animate-fade-in" style={{ padding: '22px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '14px', gap: '8px' }}>
        <h3 style={{ margin: 0, fontSize: '16px', display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--color-text-main)' }}>
          <ArrowRight size={17} color="#15803D" /> 다음 학습 추천
        </h3>
        {right}
      </div>
      {children}
    </div>
  );
  const refreshBtn = (
    <button className="btn-outline" style={{ width: 'auto', padding: '6px 12px', fontSize: '12px' }} onClick={load} disabled={loading} title="DB 기준으로 다시 확인">
      <RefreshCw size={13} /> 새로고침
    </button>
  );
  const muted = { margin: 0, fontSize: '14px', color: 'var(--color-text-muted)', lineHeight: 1.6 };

  if (plannerId == null) {
    return <Wrap><p style={muted}>원본 플래너가 없는 보관 항목이라 다음 학습 순서를 확인할 수 없습니다.</p></Wrap>;
  }
  if (loading && !data) return <Wrap right={refreshBtn}><p style={muted}>다음 학습 순서를 확인하는 중…</p></Wrap>;
  if (error) return <Wrap right={refreshBtn}><p style={{ ...muted, color: '#B91C1C' }}>{error}</p></Wrap>;
  if (!data) return <Wrap right={refreshBtn}><p style={muted}>다음 학습 정보가 없습니다.</p></Wrap>;

  const ready = data.status === 'READY';
  const inProgress = data.status === 'IN_PROGRESS';
  const pct = data.completionRate == null ? null : Math.round(data.completionRate * 100);
  const orderLabel = data.roadmapWeek != null && data.roadmapDay != null
    ? `로드맵 ${data.roadmapWeek}주차 ${data.roadmapDay}일`
    : data.recommendationType === 'USER_NEXT' ? '같은 과목의 다음 계획' : '다음 학습';
  const titleOnly = String(data.title || '').replace(/^\s*\[로드맵\s*\d+주차\s*\d+일\]\s*/, '').trim();

  if (!data.available) {
    return (
      <Wrap right={refreshBtn}>
        <p style={muted}>{data.reason || '현재 등록된 다음 학습 계획이 없습니다.'}</p>
        {pct != null && (
          <p style={{ ...muted, marginTop: '8px', fontSize: '12.5px' }}>현재 계획 이행도 {pct}% ({data.checklistCompleted}/{data.checklistTotal})</p>
        )}
      </Wrap>
    );
  }

  return (
    <Wrap right={refreshBtn}>
      <div style={{ borderRadius: '14px', border: `1px solid ${ready ? '#BBF7D0' : '#FDE68A'}`, background: ready ? '#F0FDF4' : '#FFFBEB', padding: '14px 16px' }}>
        <div style={{ fontSize: '12px', fontWeight: 700, color: ready ? '#15803D' : '#B45309', display: 'flex', alignItems: 'center', gap: '6px' }}>
          {ready ? <CheckCircle2 size={14} /> : <Clock size={14} />} {orderLabel}
        </div>
        <div style={{ marginTop: '6px', fontSize: '16px', fontWeight: 800, color: 'var(--color-text-main)', lineHeight: 1.45, wordBreak: 'keep-all', overflowWrap: 'anywhere' }}>
          {titleOnly || data.title}
        </div>
        <div style={{ marginTop: '4px', fontSize: '12.5px', color: 'var(--color-text-muted)', display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
          {data.subject && <span>과목 {data.subject}</span>}
          {data.plannerDate && <span>예정일 {data.plannerDate}</span>}
        </div>
        <p style={{ ...muted, marginTop: '10px', fontSize: '13.5px' }}>
          {inProgress
            ? '현재 계획을 먼저 마무리해 주세요. 완료한 뒤 이어서 학습할 수 있습니다.'
            : '현재 계획을 완료한 뒤 이어서 학습할 수 있습니다.'}
        </p>
        {pct != null && (
          <div style={{ marginTop: '10px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px', color: 'var(--color-text-muted)', marginBottom: '4px' }}>
              <span>현재 계획 이행도</span><b style={{ color: ready ? '#15803D' : '#B45309' }}>{pct}% ({data.checklistCompleted}/{data.checklistTotal})</b>
            </div>
            <div style={{ height: '8px', borderRadius: '999px', background: '#E5E7EB', overflow: 'hidden' }}>
              <div style={{ width: `${pct}%`, height: '100%', background: ready ? 'linear-gradient(90deg,#22C55E,#15803D)' : 'linear-gradient(90deg,#FBBF24,#D97706)' }} />
            </div>
          </div>
        )}
        {pct == null && (
          <p style={{ ...muted, marginTop: '8px', fontSize: '12px', display: 'flex', gap: '6px', alignItems: 'center' }}>
            <Info size={13} /> 체크리스트가 없어 이행도를 확인할 수 없습니다. AI 계획 분석의 체크리스트를 완료하면 반영됩니다.
          </p>
        )}
        <button
          className={ready ? 'btn-primary' : 'btn-outline'}
          style={{ marginTop: '14px', width: 'auto', padding: '10px 18px', borderRadius: '12px', fontWeight: 'bold' }}
          onClick={() => onOpen && onOpen(data)}
          title={data.reason}
        >
          다음 학습 보기 <ArrowRight size={14} />
        </button>
        <p style={{ ...muted, marginTop: '8px', fontSize: '12px' }}>{data.reason}</p>
      </div>
    </Wrap>
  );
}
