import React, { useEffect, useRef, useState } from 'react';
import { Activity, AlertTriangle } from 'lucide-react';
import { recommendationService } from '../../services/api';

/**
 * 계획 진단(Optimization Strategy) — 기존 계획을 최적화하기 위한 계산만 보여 준다(새 공부를 만들지 않음).
 *   A = Σ 하루 가용 학습 시간(사용자 입력) · W = Σ 미완료 작업 예상 시간(플래너 기록값) · D = max(0, W − A)
 * 가용 시간을 입력하지 않으면 A·D 를 표시하지 않는다(수치를 추정하지 않음). 마감 창·과부하일·선수관계·일정 중복도 함께 표시.
 * 하루 가용 시간 입력값은 이 브라우저에만 기억한다(per-viewer 편의).
 */
const STATUS_TEXT = {
  OK: { label: '여유 있음', color: '#15803D', bg: '#F0FDF4' },
  SHORTAGE: { label: '시간 부족', color: '#B91C1C', bg: '#FEF2F2' },
  NEEDS_AVAILABILITY: { label: '가용 시간 입력 필요', color: '#92400E', bg: '#FFFBEB' },
  NO_ESTIMATES: { label: '예상 시간 기록 없음', color: '#4B5563', bg: '#F9FAFB' },
  NO_TASKS: { label: '남은 작업 없음', color: '#15803D', bg: '#F0FDF4' },
};

const storageKey = 'studybridge:plan-diagnosis:daily-minutes';
const readStoredMinutes = () => {
  try { return window.localStorage.getItem(storageKey) || ''; } catch { return ''; }
};
const fmt = (m) => (m == null ? '—' : m >= 60 ? `${Math.floor(m / 60)}시간${m % 60 ? ` ${m % 60}분` : ''}` : `${m}분`);

export default function PlanDiagnosisCard({ plannerId }) {
  const [minutes, setMinutes] = useState(readStoredMinutes);
  const [deadline, setDeadline] = useState('');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const seqRef = useRef(0);

  const load = async () => {
    if (plannerId == null) return;
    const seq = ++seqRef.current;
    setLoading(true);
    setError('');
    try {
      const daily = minutes === '' ? null : Number(minutes);
      try { window.localStorage.setItem(storageKey, minutes); } catch { /* storage 불가 — 무시 */ }
      const res = await recommendationService.diagnosis(plannerId, { dailyAvailableMinutes: daily, deadline: deadline || null });
      if (seq === seqRef.current) setData(res);
    } catch (e) {
      if (seq === seqRef.current) setError(e?.response?.data?.message || '계획 진단을 불러오지 못했습니다.');
    } finally {
      if (seq === seqRef.current) setLoading(false);
    }
  };

  // 플래너가 바뀌면 이전 결과를 지우고 다시 진단
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { setData(null); load(); }, [plannerId]);

  if (plannerId == null) return null;
  const st = data ? (STATUS_TEXT[data.status] || STATUS_TEXT.OK) : null;
  const muted = { margin: 0, fontSize: '13px', color: 'var(--color-text-muted)', lineHeight: 1.6 };
  const tile = (label, value, sub) => (
    <div style={{ flex: '1 1 90px', minWidth: 0, padding: '10px 12px', borderRadius: '10px', background: '#F9FAFB', border: '1px solid #E5E7EB' }}>
      <div style={{ fontSize: '11.5px', color: 'var(--color-text-muted)' }}>{label}</div>
      <div style={{ fontSize: '17px', fontWeight: 700, color: 'var(--color-text-main)' }}>{value}</div>
      {sub && <div style={{ fontSize: '11px', color: 'var(--color-text-muted)' }}>{sub}</div>}
    </div>
  );

  return (
    <div className="glass-panel animate-fade-in" data-testid="plan-diagnosis-card" style={{ padding: '22px' }}>
      <h3 style={{ margin: '0 0 4px', fontSize: '16px', display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--color-text-main)' }}>
        <Activity size={17} color="#0369A1" /> 계획 진단
      </h3>
      <p style={{ ...muted, marginBottom: '12px' }}>남은 작업량·가용 시간·마감·선후 관계·일정 중복을 계산해 기존 계획을 점검합니다.</p>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', alignItems: 'flex-end', marginBottom: '12px' }}>
        <label style={{ display: 'flex', flexDirection: 'column', gap: '4px', fontSize: '12.5px', color: 'var(--color-text-muted)' }}>
          하루 가용 학습 시간(분)
          <input type="number" min="0" max="1440" inputMode="numeric" value={minutes} placeholder="예: 120"
            onChange={(e) => setMinutes(e.target.value)}
            style={{ width: '120px', minHeight: '36px', borderRadius: '8px', border: '1px solid var(--color-border)', padding: '4px 8px', fontSize: '14px' }} />
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: '4px', fontSize: '12.5px', color: 'var(--color-text-muted)' }}>
          마감일(선택)
          <input type="date" value={deadline} onChange={(e) => setDeadline(e.target.value)}
            style={{ minHeight: '36px', borderRadius: '8px', border: '1px solid var(--color-border)', padding: '4px 8px', fontSize: '14px' }} />
        </label>
        <button className="btn-outline" style={{ width: 'auto', padding: '6px 14px', fontSize: '13px', minHeight: '36px' }} onClick={load} disabled={loading}>
          {loading ? '계산 중…' : '진단하기'}
        </button>
      </div>

      {error && <p role="alert" style={{ ...muted, color: '#B91C1C' }}>{error}</p>}
      {data && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <div style={{ padding: '8px 12px', borderRadius: '8px', background: st.bg, color: st.color, fontSize: '13.5px', fontWeight: 700 }}>
            {st.label} <span style={{ fontWeight: 400, color: 'var(--color-text-muted)' }}>· {data.from} ~ {data.to} ({data.horizonDays}일){data.deadline ? ` · 마감 ${data.deadline}` : ''}</span>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
            {tile('가용 시간 A', fmt(data.availableMinutes), data.dailyAvailableMinutes != null ? `하루 ${fmt(data.dailyAvailableMinutes)}` : '입력 필요')}
            {tile('예상 작업량 W', fmt(data.workloadMinutes), `${data.estimatedCount}개 작업${data.unestimatedCount ? ` · 미기록 ${data.unestimatedCount}` : ''}`)}
            {tile('부족량 D', fmt(data.deficitMinutes), 'max(0, W − A)')}
          </div>

          {data.firstShortageWindow && (
            <div style={{ display: 'flex', gap: '6px', fontSize: '13px', color: '#B91C1C', lineHeight: 1.5 }}>
              <AlertTriangle size={15} style={{ flexShrink: 0, marginTop: '2px' }} />
              <span>{data.firstShortageWindow.dueDate}까지 계획된 작업 {fmt(data.firstShortageWindow.cumulativeWorkload)} 중 {fmt(data.firstShortageWindow.shortage)}가 그때까지의 가용 시간을 넘습니다.</span>
            </div>
          )}
          {data.overloadedDays?.length > 0 && (
            <div>
              <div style={{ fontSize: '13px', fontWeight: 700, marginBottom: '4px' }}>과부하 날짜</div>
              <ul style={{ margin: 0, paddingLeft: '18px', fontSize: '13px', lineHeight: 1.6 }}>
                {data.overloadedDays.slice(0, 7).map((d) => <li key={d.date}>{d.date}: {fmt(d.plannedMinutes)} 계획 / 가용 {fmt(d.availableMinutes)}</li>)}
              </ul>
            </div>
          )}
          {data.dependencyIssues?.length > 0 && (
            <div>
              <div style={{ fontSize: '13px', fontWeight: 700, marginBottom: '4px' }}>선후 관계 점검</div>
              <ul style={{ margin: 0, paddingLeft: '18px', fontSize: '13px', lineHeight: 1.6, overflowWrap: 'anywhere' }}>
                {data.dependencyIssues.slice(0, 5).map((d, i) => (
                  <li key={i}>{d.kind === 'SCHEDULED_BEFORE_PREREQ'
                    ? `‘${d.title}’이(가) 선행 단계 ‘${d.prereqTitle}’보다 먼저 배치되어 있습니다.`
                    : `선행 단계 ‘${d.prereqTitle}’이(가) 기한이 지났지만 완료되지 않았습니다.`}</li>
                ))}
              </ul>
            </div>
          )}
          {data.overlaps?.length > 0 && (
            <div>
              <div style={{ fontSize: '13px', fontWeight: 700, marginBottom: '4px' }}>일정 중복</div>
              <ul style={{ margin: 0, paddingLeft: '18px', fontSize: '13px', lineHeight: 1.6, overflowWrap: 'anywhere' }}>
                {data.overlaps.slice(0, 5).map((o, i) => <li key={i}>‘{o.first}’ ↔ ‘{o.second}’ {o.overlapMinutes}분 겹침</li>)}
              </ul>
            </div>
          )}
          {data.priority?.length > 0 && (
            <div>
              <div style={{ fontSize: '13px', fontWeight: 700, marginBottom: '4px' }}>권장 처리 순서 <span style={{ fontWeight: 400, color: 'var(--color-text-muted)' }}>(기한 → 선후 관계)</span></div>
              <ol style={{ margin: 0, paddingLeft: '20px', fontSize: '13px', lineHeight: 1.6, overflowWrap: 'anywhere' }}>
                {data.priority.slice(0, 5).map((t) => <li key={t.plannerId}>{t.title}{t.date ? ` · ${t.date}` : ''}{t.estimatedMinutes ? ` · ${fmt(t.estimatedMinutes)}` : ''}</li>)}
              </ol>
            </div>
          )}
          {data.notes?.length > 0 && (
            <ul style={{ margin: 0, paddingLeft: '18px', fontSize: '12px', color: 'var(--color-text-muted)', lineHeight: 1.6 }}>
              {data.notes.map((n, i) => <li key={i}>{n}</li>)}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
