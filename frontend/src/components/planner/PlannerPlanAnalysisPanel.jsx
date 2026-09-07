import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Sparkles, ListChecks, Target, BookOpen, Workflow, Clock, Download, ChevronDown, RefreshCw, AlertTriangle } from 'lucide-react';
import { plannerService } from '../../services/api';

// 학습 활동 유형 → 한글 라벨
const TYPE_LABEL = {
  CONCEPT: '개념',
  PRACTICE: '실습',
  ANALYSIS: '분석',
  COMPARISON: '비교',
  REVIEW: '복습',
  OUTPUT: '산출물',
};
const typeLabel = (t) => TYPE_LABEL[String(t || '').toUpperCase()] || (t || '학습');

// 목표 정합성 레벨 → 배지 스타일/라벨
const LEVEL_STYLE = {
  HIGH: { label: '높음', color: '#15803D', bg: '#EEF8EB', border: '#BBF7D0' },
  MEDIUM: { label: '보통', color: '#B45309', bg: '#FEF3C7', border: '#FDE68A' },
  LOW: { label: '낮음', color: '#B91C1C', bg: '#FEF2F2', border: '#FECACA' },
};
const levelStyle = (lv) => LEVEL_STYLE[String(lv || '').toUpperCase()] || { label: (lv || '—'), color: '#6B7280', bg: '#F3F4F6', border: '#E5E7EB' };

// 코드/패키지명이 깨지지 않게: 단어 내부(특히 CJK) 분절 금지 + 넘칠 때만 줄바꿈
const codeSafe = { overflowWrap: 'anywhere', wordBreak: 'keep-all', whiteSpace: 'pre-wrap', lineHeight: 1.6 };

// HH:MM + minutes → HH:MM (분 오버플로/24시 순환 처리)
const addMinutes = (hhmm, minutes) => {
  const [h, m] = String(hhmm || '09:00').split(':').map((x) => parseInt(x, 10) || 0);
  const total = h * 60 + m + (Number(minutes) || 0);
  const norm = ((total % 1440) + 1440) % 1440;
  const hh = String(Math.floor(norm / 60)).padStart(2, '0');
  const mm = String(norm % 60).padStart(2, '0');
  return `${hh}:${mm}`;
};

const Card = ({ icon, title, right, children }) => (
  <div className="glass-panel animate-fade-in" style={{ padding: '22px' }}>
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '14px', gap: '8px', flexWrap: 'wrap' }}>
      <h3 style={{ margin: 0, fontSize: '16px', display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--color-text-main)' }}>{icon} {title}</h3>
      {right}
    </div>
    {children}
  </div>
);

const LevelBadge = ({ level }) => {
  const s = levelStyle(level);
  return (
    <span style={{ display: 'inline-block', fontSize: '11px', fontWeight: 700, color: s.color, background: s.bg, border: `1px solid ${s.border}`, borderRadius: '8px', padding: '2px 8px', flexShrink: 0 }}>
      {s.label}
    </span>
  );
};

const ProgressBar = ({ percent }) => (
  <div style={{ height: '10px', borderRadius: '999px', background: '#E5E7EB', overflow: 'hidden' }}>
    <div style={{ width: `${Math.max(0, Math.min(100, percent || 0))}%`, height: '100%', background: 'linear-gradient(90deg,#22C55E,#15803D)', transition: 'width 0.4s' }} />
  </div>
);

// 하나의 학습 활동 상세(데이터 플로우 노드 클릭 / 활동 리스트 클릭이 공유)
const TaskDetail = ({ task }) => {
  if (!task) return null;
  const seq = Array.isArray(task.learningSequence) ? task.learningSequence.filter(Boolean) : [];
  const pre = Array.isArray(task.prerequisites) ? task.prerequisites.filter((p) => p && p.name) : [];
  const ga = task.goalAlignment || {};
  const Line = ({ label, children }) => (
    <div style={{ marginTop: '10px' }}>
      <div style={{ fontSize: '12px', fontWeight: 700, color: 'var(--color-text-muted)', marginBottom: '3px' }}>{label}</div>
      <div style={{ fontSize: '13.5px', color: 'var(--color-text-main)', ...codeSafe }}>{children}</div>
    </div>
  );
  return (
    <div style={{ borderTop: '1px dashed var(--color-border)', marginTop: '10px', paddingTop: '10px' }}>
      <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
        <span style={{ fontSize: '12px', color: 'var(--color-text-muted)' }}>유형 <b style={{ color: 'var(--color-text-main)' }}>{typeLabel(task.type)}</b></span>
        <span style={{ fontSize: '12px', color: 'var(--color-text-muted)' }}>권장시간 <b style={{ color: 'var(--color-text-main)' }}>{task.recommendedMinutes ?? 0}분</b></span>
        {ga.level && <span style={{ fontSize: '12px', color: 'var(--color-text-muted)', display: 'inline-flex', alignItems: 'center', gap: '4px' }}>목표 정합성 <LevelBadge level={ga.level} /></span>}
      </div>
      {ga.reason && <Line label="정합성 이유">{ga.reason}</Line>}
      {task.description && <Line label="설명">{task.description}</Line>}
      {task.whyImportant && <Line label="왜 필요한가">{task.whyImportant}</Line>}
      {pre.length > 0 && (
        <Line label="먼저 알면 좋은 개념">
          {pre.map((p) => p.name).join(', ')}
        </Line>
      )}
      {seq.length > 0 && <Line label="권장 순서">{seq.join(' → ')}</Line>}
    </div>
  );
};

export default function PlannerPlanAnalysisPanel({ plannerId }) {
  const [analysis, setAnalysis] = useState(null);
  const [initialLoading, setInitialLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState(null);       // { message }
  const [expandedTaskId, setExpandedTaskId] = useState(null);

  const [startTime, setStartTime] = useState('09:00');
  const [pdfGenerating, setPdfGenerating] = useState(false);
  const [pdfError, setPdfError] = useState('');

  const load = useCallback(async () => {
    if (plannerId == null) { setInitialLoading(false); return; }
    setInitialLoading(true);
    setError(null);
    try {
      const data = await plannerService.getPlanAnalysis(plannerId);
      setAnalysis(data || null);
    } catch (e) {
      setError({ message: '분석 결과를 불러오지 못했습니다. 잠시 후 다시 시도해주세요.' });
    } finally {
      setInitialLoading(false);
    }
  }, [plannerId]);

  useEffect(() => { load(); }, [load]);

  const runAnalysis = useCallback(async () => {
    if (plannerId == null || analyzing) return;
    setAnalyzing(true);
    setError(null);
    try {
      const data = await plannerService.analyzePlan(plannerId);
      setAnalysis(data || null);
      if (data && data.errorCode) {
        setError({ message: data.summary || '분석 중 문제가 발생했습니다.' });
      }
    } catch (e) {
      setError({ message: 'AI 분석에 실패했습니다. 잠시 후 다시 시도해주세요.' });
    } finally {
      setAnalyzing(false);
    }
  }, [plannerId, analyzing]);

  // 로컬 시간표 미리보기(서버 재호출 없음). flow 우선, 없으면 tasks 사용.
  const previewRows = useMemo(() => {
    if (!analysis) return [];
    const src = Array.isArray(analysis.flow) && analysis.flow.length > 0
      ? analysis.flow
      : (Array.isArray(analysis.tasks) ? analysis.tasks : []);
    let cursor = startTime || '09:00';
    return src.map((n) => {
      const mins = Number(n.recommendedMinutes) || 0;
      const start = cursor;
      const end = addMinutes(cursor, mins);
      cursor = end;
      return { key: n.taskId ?? n.id ?? n.title, title: n.title, type: n.type, recommendedMinutes: mins, startTime: start, endTime: end };
    });
  }, [analysis, startTime]);

  const handleDownloadPdf = useCallback(async () => {
    if (plannerId == null || pdfGenerating) return;
    setPdfGenerating(true);
    setPdfError('');
    try {
      const result = await plannerService.generateSchedulePdf(plannerId, startTime);
      const url = result?.downloadUrl;
      if (url) {
        window.open(url, '_blank', 'noopener');
      } else {
        setPdfError('PDF 생성 실패');
      }
    } catch (e) {
      setPdfError('PDF 생성 실패');
    } finally {
      setPdfGenerating(false);
    }
  }, [plannerId, startTime, pdfGenerating]);

  const toggleTask = (id) => setExpandedTaskId((prev) => (prev === id ? null : id));

  const wrapStyle = { display: 'flex', flexDirection: 'column', gap: '20px' };

  // ── 초기 로딩 ──
  if (initialLoading) {
    return (
      <div style={wrapStyle}>
        <Card icon={<Sparkles size={17} color="var(--color-primary)" />} title="AI 계획 분석">
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {[0, 1, 2].map((i) => (<div key={i} style={{ height: '14px', borderRadius: '6px', background: 'linear-gradient(90deg,#F3F4F6,#E5E7EB,#F3F4F6)', backgroundSize: '200% 100%', animation: 'pulse 1.4s ease-in-out infinite' }} />))}
          </div>
        </Card>
      </div>
    );
  }

  const empty = !analysis || analysis.empty === true;

  // ── 분석 없음(intro) ──
  if (empty) {
    return (
      <div style={wrapStyle}>
        <Card icon={<Sparkles size={17} color="var(--color-primary)" />} title="AI 계획 분석">
          {error && (
            <div style={{ borderRadius: '10px', border: '1px solid #FECACA', background: '#FEF2F2', padding: '12px', marginBottom: '14px', fontSize: '13px', color: '#B91C1C' }}>{error.message}</div>
          )}
          <p style={{ margin: '0 0 14px', fontSize: '14px', color: 'var(--color-text-muted)', ...codeSafe }}>
            아직 분석 결과가 없습니다. AI 계획 분석을 실행하면 학습 목표 정합성, 선수지식, 학습 흐름과 하루 시간표까지 구조적으로 정리해드립니다.
          </p>
          <button className="btn-primary" style={{ width: 'auto', padding: '10px 18px', borderRadius: '12px', fontWeight: 'bold' }} onClick={runAnalysis} disabled={analyzing}>
            <Sparkles size={16} /> {analyzing ? 'AI 분석 중…' : 'AI 계획 분석 실행'}
          </button>
        </Card>
      </div>
    );
  }

  const goal = analysis.goalAlignment || {};
  const prerequisites = Array.isArray(analysis.prerequisites) ? analysis.prerequisites.filter((p) => p && p.name) : [];
  const tasks = Array.isArray(analysis.tasks) ? analysis.tasks : [];
  const flow = Array.isArray(analysis.flow) && analysis.flow.length > 0 ? analysis.flow : tasks;
  const cp = analysis.checklistProgress || { total: 0, completed: 0, percent: 0 };
  const warnings = Array.isArray(analysis.warnings) ? analysis.warnings.filter(Boolean) : [];

  const timeChipLabel = analysis.targetMinutesEstimated
    ? `AI 예상 학습시간 ${analysis.totalRecommendedMinutes ?? 0}분`
    : `총 목표 학습시간 ${analysis.targetMinutes ?? 0}분`;

  const rerunBtn = (
    <button className="btn-outline" style={{ width: 'auto', padding: '6px 12px', fontSize: '12px' }} onClick={runAnalysis} disabled={analyzing}>
      <RefreshCw size={14} /> {analyzing ? '분석 중…' : '다시 분석'}
    </button>
  );

  return (
    <div style={wrapStyle}>
      {/* stale 배너 */}
      {analysis.stale && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap', borderRadius: '10px', border: '1px solid #FDE68A', background: '#FEFCE8', padding: '10px 14px' }}>
          <AlertTriangle size={16} color="#B45309" style={{ flexShrink: 0 }} />
          <span style={{ fontSize: '13px', color: '#92400E', flex: 1, minWidth: '160px' }}>플래너 내용이 바뀌었어요. 다시 분석하기</span>
          <button className="btn-outline" style={{ width: 'auto', padding: '6px 12px', fontSize: '12px' }} onClick={runAnalysis} disabled={analyzing}>
            <RefreshCw size={14} /> {analyzing ? '분석 중…' : '다시 분석'}
          </button>
        </div>
      )}

      {/* 오류 배너(패널 blank 방지) */}
      {error && (
        <div style={{ borderRadius: '10px', border: '1px solid #FECACA', background: '#FEF2F2', padding: '12px', fontSize: '13px', color: '#B91C1C' }}>{error.message}</div>
      )}

      {/* 헤더 블록 */}
      <Card icon={<Sparkles size={17} color="var(--color-primary)" />} title={analysis.title || 'AI 계획 분석'} right={rerunBtn}>
        {analysis.learningGoal && (
          <p style={{ margin: '0 0 12px', fontSize: '14px', color: 'var(--color-text-main)', ...codeSafe }}>{analysis.learningGoal}</p>
        )}
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginBottom: '14px' }}>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', fontSize: '12px', fontWeight: 700, color: '#15803D', background: '#EEF8EB', border: '1px solid #BBF7D0', borderRadius: '999px', padding: '4px 12px' }}>
            <Clock size={13} /> {timeChipLabel}
          </span>
          {analysis.subject && (
            <span style={{ fontSize: '12px', fontWeight: 600, color: 'var(--color-text-muted)', background: '#F3F4F6', borderRadius: '999px', padding: '4px 12px' }}>{analysis.subject}</span>
          )}
        </div>
        {analysis.summary && (
          <p style={{ margin: '0 0 14px', fontSize: '13.5px', color: 'var(--color-text-main)', ...codeSafe }}>{analysis.summary}</p>
        )}
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px', fontSize: '13px' }}>
          <span style={{ color: 'var(--color-text-muted)' }}>체크리스트 진행</span>
          <b style={{ color: '#15803D' }}>{cp.completed || 0}/{cp.total || 0} ({cp.percent || 0}%)</b>
        </div>
        <ProgressBar percent={cp.percent} />
        {warnings.length > 0 && (
          <ul style={{ margin: '14px 0 0', paddingLeft: '18px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
            {warnings.map((w, i) => <li key={i} style={{ fontSize: '12.5px', color: '#B45309', ...codeSafe }}>{w}</li>)}
          </ul>
        )}
      </Card>

      {/* 목표 정합성 */}
      <Card icon={<Target size={17} color="#0F766E" />} title="목표 정합성" right={<LevelBadge level={goal.level} />}>
        {goal.summary && <p style={{ margin: '0 0 8px', fontSize: '14px', color: 'var(--color-text-main)', ...codeSafe }}>{goal.summary}</p>}
        {goal.reason && <p style={{ margin: 0, fontSize: '13.5px', color: 'var(--color-text-muted)', ...codeSafe }}>{goal.reason}</p>}
        {Array.isArray(goal.issues) && goal.issues.length > 0 && (
          <div style={{ marginTop: '14px' }}>
            <div style={{ fontSize: '13px', fontWeight: 700, color: 'var(--color-text-main)', marginBottom: '6px' }}>정합성 점검</div>
            <ul style={{ margin: 0, paddingLeft: '18px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
              {goal.issues.map((line, i) => <li key={i} style={{ fontSize: '13.5px', color: 'var(--color-text-main)', ...codeSafe }}>{typeof line === 'string' ? line : (line?.reason || line?.name || '')}</li>)}
            </ul>
          </div>
        )}
      </Card>

      {/* 선수지식 */}
      {prerequisites.length > 0 && (
        <Card icon={<BookOpen size={17} color="#15803D" />} title="학습 전 확인 권장">
          <ul style={{ margin: 0, paddingLeft: '18px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {prerequisites.map((p, i) => (
              <li key={i} style={{ fontSize: '13.5px', color: 'var(--color-text-main)', ...codeSafe }}>
                <b>{p.name}</b>
                {p.reason && <span style={{ display: 'block', fontSize: '12.5px', color: 'var(--color-text-muted)', marginTop: '2px' }}>{p.reason}</span>}
              </li>
            ))}
          </ul>
          <p style={{ margin: '12px 0 0', fontSize: '12px', color: 'var(--color-text-muted)' }}>현재 플래너의 목표 학습시간에는 포함되지 않습니다.</p>
        </Card>
      )}

      {/* 학습 Data Flow */}
      {flow.length > 0 && (
        <Card icon={<Workflow size={17} color="#0F766E" />} title="학습 Data Flow">
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'stretch', gap: '0' }}>
            {flow.map((n, idx) => {
              const tid = n.taskId ?? n.id ?? n.order;
              return (
                <React.Fragment key={`${tid}-${idx}`}>
                  <button
                    onClick={() => { setExpandedTaskId(tid); }}
                    style={{ textAlign: 'left', cursor: 'pointer', border: '1px solid var(--color-border)', background: expandedTaskId === tid ? '#F0FDF4' : '#fff', borderRadius: '10px', padding: '10px 14px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '10px', width: '100%' }}
                    title={n.title}
                  >
                    <span style={{ fontSize: '13.5px', fontWeight: 600, color: 'var(--color-text-main)', flex: 1, minWidth: 0, ...codeSafe }}>{n.title}</span>
                    <span style={{ fontSize: '12px', color: 'var(--color-text-muted)', flexShrink: 0 }}>{n.recommendedMinutes ?? 0}분</span>
                  </button>
                  {idx < flow.length - 1 && (
                    <div style={{ textAlign: 'center', color: 'var(--color-text-muted)', fontSize: '14px', lineHeight: '20px', padding: '2px 0' }}>↓</div>
                  )}
                </React.Fragment>
              );
            })}
          </div>
          <div style={{ marginTop: '14px', fontSize: '13px', color: 'var(--color-text-muted)', textAlign: 'right' }}>총 <b style={{ color: '#15803D' }}>{analysis.totalRecommendedMinutes ?? 0}분</b></div>
        </Card>
      )}

      {/* 학습 활동 */}
      {tasks.length > 0 && (
        <Card icon={<ListChecks size={17} color="#15803D" />} title="학습 활동">
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {tasks.map((t) => {
              const tid = t.id ?? t.order;
              const open = expandedTaskId === tid;
              return (
                <div key={tid} style={{ border: '1px solid var(--color-border)', background: open ? '#F0FDF4' : '#fff', borderRadius: '10px', padding: '12px 14px' }}>
                  <button onClick={() => toggleTask(tid)} style={{ width: '100%', textAlign: 'left', cursor: 'pointer', background: 'none', border: 'none', padding: 0, display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '10px' }}>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <span style={{ display: 'block', fontSize: '14px', fontWeight: 600, color: 'var(--color-text-main)', ...codeSafe }} title={t.title}>{t.title}</span>
                      <span style={{ display: 'block', marginTop: '3px', fontSize: '12px', color: 'var(--color-text-muted)' }}>{typeLabel(t.type)} · {t.recommendedMinutes ?? 0}분</span>
                    </div>
                    <ChevronDown size={18} color="#9CA3AF" style={{ flexShrink: 0, transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }} />
                  </button>
                  {open && <TaskDetail task={t} />}
                </div>
              );
            })}
          </div>
        </Card>
      )}

      {/* 하루 학습 시간표 */}
      <Card icon={<Clock size={17} color="#15803D" />} title="하루 학습 시간표">
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap', marginBottom: '14px' }}>
          <label style={{ fontSize: '13px', color: 'var(--color-text-muted)' }}>학습 시작 시간</label>
          <input type="time" value={startTime} onChange={(e) => setStartTime(e.target.value || '09:00')}
            style={{ borderRadius: '10px', border: '1px solid var(--color-border)', padding: '8px 10px', fontSize: '14px' }} />
          <button className="btn-primary" style={{ width: 'auto', padding: '8px 16px', borderRadius: '10px', fontWeight: 'bold' }} onClick={handleDownloadPdf} disabled={pdfGenerating}>
            <Download size={15} /> {pdfGenerating ? 'PDF 생성 중…' : 'PDF 다운로드'}
          </button>
        </div>
        {pdfError && <div style={{ fontSize: '12.5px', color: '#B91C1C', marginBottom: '12px' }}>{pdfError}</div>}
        {previewRows.length === 0 ? (
          <p style={{ margin: 0, fontSize: '13.5px', color: 'var(--color-text-muted)' }}>표시할 학습 활동이 없습니다.</p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {previewRows.map((r) => (
              <div key={r.key} style={{ display: 'flex', alignItems: 'center', gap: '10px', border: '1px solid var(--color-border)', borderRadius: '10px', padding: '10px 12px', flexWrap: 'wrap' }}>
                <span style={{ fontSize: '13px', fontWeight: 700, color: '#15803D', flexShrink: 0 }}>{r.startTime} ~ {r.endTime}</span>
                <span style={{ fontSize: '13.5px', color: 'var(--color-text-main)', flex: 1, minWidth: '120px', ...codeSafe }} title={r.title}>{r.title}</span>
                <span style={{ fontSize: '11.5px', color: 'var(--color-text-muted)', flexShrink: 0 }}>{typeLabel(r.type)}</span>
              </div>
            ))}
          </div>
        )}
        <div style={{ marginTop: '14px', fontSize: '13px', color: 'var(--color-text-muted)', textAlign: 'right' }}>총 학습시간 <b style={{ color: '#15803D' }}>{analysis.totalRecommendedMinutes ?? 0}분</b></div>
      </Card>
    </div>
  );
}
