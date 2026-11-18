import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  AlertTriangle, BookOpen, CalendarClock, CalendarPlus, CheckCircle2, Circle, Clock, Compass, ExternalLink, Flag,
  HelpCircle, Lightbulb, ListChecks, Pause, Play, RefreshCw, Sparkles, Square, Target, Timer, Trophy, X,
} from 'lucide-react';
import { plannerService } from '../../services/api';
import {
  ALLOWED_MINUTES, ACTIVITY_LABEL, FACTOR_LABEL, changeText, createLatestGate, dueLabel, errorView,
  findItem, focusProgress, formatClock, formatDateKo, safeStorage, sameId, statusView, stepLabel, stepOptionLabel,
  sumActivityMinutes, warningText,
} from '../../utils/adaptiveNavigator';
import './AiLearningNavigator.css';

/**
 * AI 학습 내비게이터 — 기존 "다음 예정 계획 / 학습 추천" 화면을 대체한다(AI 계획 분석 탭은 그대로).
 *  · 로드맵 플래너 → AI 학습 코치(ROADMAP_COACH): 선택한 현재 단계를 15·30·60분 안에 어떻게 배울지. 다음 단계는 추천하지 않는다.
 *  · 수기 플래너   → AI 다음 학습(MANUAL_NEXT): 미완료 항목 중 무엇을 먼저 할지 + 점수 구성 + 2·3순위.
 *  · 시간 버튼을 바꾸면 다시 계산한다. 이전 요청은 취소하고 시퀀스로 한 번 더 걸러 오래된 응답이 최신 결과를 덮지 않는다.
 *  · 일정 복구·나눠 하기는 제안일 뿐이다. [일정에 반영] → 날짜·시간 확인 → 승인한 항목만 Spring 이 저장 → 다시 계산.
 *  · AI 문구 보강(AI_ASSISTED)과 규칙 결과(RULE_BASED)를 같은 화면으로 그린다.
 */
const MINUTES_KEY = 'sb.aln.minutes';
const focusKey = (pid) => `sb.aln.focus.${pid}`;

function readFocus(pid) {
  if (pid == null) return null;
  try {
    const raw = safeStorage.get('sessionStorage', focusKey(pid));
    const f = raw ? JSON.parse(raw) : null;
    return f && f.startedAt ? f : null;
  } catch {
    return null;
  }
}

function initialMinutes() {
  const v = Number(safeStorage.get('localStorage', MINUTES_KEY));
  return ALLOWED_MINUTES.includes(v) ? v : 30;
}

export default function AiLearningNavigator({ plannerId, onOpenPlanner, onOpenChecklist, onOpenSchedule }) {
  const [minutes, setMinutes] = useState(initialMinutes);
  const [stepId, setStepId] = useState(null);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [applyOpen, setApplyOpen] = useState(false);
  const [selected, setSelected] = useState({});
  const [applying, setApplying] = useState(false);
  const [applyError, setApplyError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [focus, setFocus] = useState(() => readFocus(plannerId));
  const gateRef = useRef(null);
  if (!gateRef.current) gateRef.current = createLatestGate();

  useEffect(() => {
    setStepId(null);
    setData(null);
    setError(null);
    setNotice(null);
    setApplyOpen(false);
    setFocus(readFocus(plannerId));
  }, [plannerId]);

  useEffect(() => {
    if (plannerId == null) return undefined;
    const gate = gateRef.current;
    const { seq, signal } = gate.next();
    setLoading(true);
    setError(null);
    // 빠른 연속 선택은 짧게 모아 마지막 값만 보낸다(취소 + 시퀀스 검증과 함께 이중 보호).
    const timer = setTimeout(async () => {
      try {
        const body = { availableMinutes: minutes, useLlm: true };
        if (stepId != null) body.currentStepId = stepId;
        const res = await plannerService.getAdaptiveNavigator(plannerId, body, { signal });
        if (!gate.isLatest(seq)) return;
        setData(res || null);
      } catch (e) {
        if (!gate.isLatest(seq)) return;
        const v = errorView(e);
        if (v) setError(v);
      } finally {
        if (gate.isLatest(seq)) setLoading(false);
      }
    }, 200);
    return () => clearTimeout(timer);
  }, [plannerId, minutes, stepId, reloadKey]);

  useEffect(() => () => gateRef.current?.abort(), []);

  const chooseMinutes = (m) => {
    if (m === minutes) return;
    setMinutes(m);
    safeStorage.set('localStorage', MINUTES_KEY, String(m));
  };

  const roadmap = (data?.mode || '') === 'ROADMAP_COACH';
  const result = data?.result || null;
  const view = data ? statusView(data) : null;
  const rec = result?.recommendation || null;
  const changes = Array.isArray(data?.changes) ? data.changes : [];
  const canApply = changes.length > 0 && !!data?.proposalToken;

  const openApply = () => {
    const sel = {};
    changes.forEach((c) => { sel[c.id] = true; });
    setSelected(sel);
    setApplyError(null);
    setApplyOpen(true);
  };

  const confirmApply = async () => {
    const ids = Object.keys(selected).filter((k) => selected[k]);
    if (!ids.length || applying) return;
    setApplying(true);
    setApplyError(null);
    try {
      const res = await plannerService.applyAdaptiveProposal(plannerId, { proposalToken: data.proposalToken, changeIds: ids });
      const applied = Array.isArray(res?.applied) ? res.applied : [];
      const sessions = applied.filter((a) => a.kind === 'ADD_STUDY_SESSION').length;
      const moved = applied.filter((a) => a.kind === 'RESCHEDULE_PLANNER').length;
      setApplyOpen(false);
      setNotice({
        tone: 'success',
        text: res?.alreadyApplied
          ? '이미 일정에 반영되어 있어요. 최신 데이터로 다시 계산했어요.'
          : `일정에 반영했어요 — 주간 일정 ${sessions}건${moved ? `, 플래너 날짜 변경 ${moved}건` : ''}. 최신 데이터로 다시 계산했어요.`,
        schedule: sessions > 0,
      });
      setReloadKey((k) => k + 1);
    } catch (e) {
      const v = errorView(e) || { title: '반영하지 못했어요', message: '잠시 후 다시 시도해 주세요.' };
      if (e?.response?.status === 409) {
        setApplyOpen(false);
        setNotice({ tone: 'warn', text: `${v.message} 새 추천을 불러왔어요.` });
        setReloadKey((k) => k + 1);
      } else {
        setApplyError(v);
      }
    } finally {
      setApplying(false);
    }
  };

  const startFocus = () => {
    if (!rec) return;
    const f = {
      itemId: rec.itemId, title: rec.title, minutes: rec.estimatedMinutes || minutes,
      activities: (rec.activities || []).map((a) => ({ title: a.title, minutes: a.minutes, type: a.type })),
      startedAt: Date.now(), pausedAt: null, pausedMs: 0,
    };
    setFocus(f);
    safeStorage.set('sessionStorage', focusKey(plannerId), JSON.stringify(f));
  };
  const updateFocus = (f) => {
    setFocus(f);
    if (f) safeStorage.set('sessionStorage', focusKey(plannerId), JSON.stringify(f));
    else safeStorage.remove('sessionStorage', focusKey(plannerId));
  };

  if (plannerId == null) {
    return (
      <Shell title="AI 학습 내비게이터" badge={null}>
        <EmptyState icon={<HelpCircle size={26} color="#6B7280" />} title="원본 플래너가 없는 보관 항목이에요"
          message="이 항목은 플래너가 삭제된 뒤 보관된 사본이라 AI 학습 내비게이터를 쓸 수 없습니다." />
      </Shell>
    );
  }

  const title = data ? (roadmap ? 'AI 학습 코치' : 'AI 다음 학습') : 'AI 학습 내비게이터';
  const badge = data ? (roadmap ? '현재 단계 코칭' : '다음 학습') : null;

  return (
    <Shell title={title} badge={badge} source={result?.source}
      right={(
        <button type="button" className="aln-icon-btn" onClick={() => setReloadKey((k) => k + 1)} disabled={loading} title="다시 계산" aria-label="다시 계산">
          <RefreshCw size={15} className={loading ? 'aln-spin' : ''} />
        </button>
      )}>
      <div className="aln-toolbar">
        <div className="aln-seg" role="group" aria-label="학습 시간 선택">
          {ALLOWED_MINUTES.map((m) => (
            <button key={m} type="button" className={`aln-seg-btn ${m === minutes ? 'is-active' : ''}`} aria-pressed={m === minutes}
              onClick={() => chooseMinutes(m)}>
              <Clock size={14} /> {m}분
            </button>
          ))}
        </div>
        {roadmap && Array.isArray(data?.items) && data.items.length > 0 && (
          <label className="aln-step-picker">
            <span>현재 단계</span>
            <select value={data.currentStepId ?? ''} onChange={(e) => setStepId(Number(e.target.value))} disabled={loading}>
              {data.items.map((it) => (
                <option key={it.id} value={it.id}>{stepOptionLabel(it)}</option>
              ))}
            </select>
          </label>
        )}
      </div>

      {notice && (
        <div className={`aln-notice is-${notice.tone}`} role="status">
          {notice.tone === 'success' ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
          <span>{notice.text}</span>
          {notice.schedule && onOpenSchedule && (
            <button type="button" className="aln-link" onClick={onOpenSchedule}>주간 일정 보기</button>
          )}
          <button type="button" className="aln-notice-x" onClick={() => setNotice(null)} aria-label="닫기"><X size={14} /></button>
        </div>
      )}

      {focus && (
        <FocusPanel focus={focus} onChange={updateFocus} onOpenChecklist={onOpenChecklist} />
      )}

      {error && !loading && (
        <div className="aln-error" role="alert">
          <AlertTriangle size={18} />
          <div>
            <b>{error.title}</b>
            <p>{error.message}{error.retryAfter ? ` (${error.retryAfter}초 뒤 다시 시도)` : ''}</p>
          </div>
          {error.retryable && (
            <button type="button" className="aln-btn is-ghost" onClick={() => setReloadKey((k) => k + 1)}>다시 시도</button>
          )}
        </div>
      )}

      {!data && loading && <Skeleton />}

      {data && (
        <div className={`aln-body ${loading ? 'is-stale' : ''}`} aria-busy={loading}>
          {loading && <div className="aln-recalc"><RefreshCw size={13} className="aln-spin" /> {minutes}분 기준으로 다시 계산하는 중…</div>}

          {view?.kind === 'ready' && rec && (
            <ReadyView data={data} rec={rec} roadmap={roadmap} minutes={minutes}
              onStart={startFocus} focusActive={!!focus} canApply={canApply} onApply={openApply} onOpenPlanner={onOpenPlanner} />
          )}

          {view?.kind === 'stepDone' && (
            <EmptyState icon={<CheckCircle2 size={26} color="#15803D" />} title={view.title} message={view.message}>
              {data.suggestedStepId != null && !sameId(data.suggestedStepId, data.currentStepId) && (
                <button type="button" className="aln-btn is-primary" onClick={() => setStepId(Number(data.suggestedStepId))}>
                  <Flag size={15} /> {stepLabel(findItem(data.items, data.suggestedStepId))} 단계로 코칭 받기
                </button>
              )}
              <p className="aln-hint">위의 ‘현재 단계’에서 다른 단계를 직접 고를 수도 있어요.</p>
            </EmptyState>
          )}

          {view?.kind === 'allDone' && (
            <EmptyState icon={<Trophy size={26} color="#CA8A04" />} title={view.title} message={view.message} />
          )}

          {view?.kind === 'empty' && (
            <EmptyState icon={<BookOpen size={26} color="#6B7280" />} title={view.title} message={view.message}>
              {!roadmap && onOpenPlanner && (
                <button type="button" className="aln-btn is-ghost" onClick={() => onOpenPlanner(null)}>플래너 작성하러 가기</button>
              )}
            </EmptyState>
          )}

          {(view?.kind === 'ready' || view?.kind === 'stepDone') && (
            <Warnings warnings={[...(result?.warnings || []), ...(data.warnings || [])]} />
          )}
        </div>
      )}

      {applyOpen && (
        <ApplyDialog changes={changes} today={data?.today} selected={selected} setSelected={setSelected}
          applying={applying} error={applyError} onCancel={() => !applying && setApplyOpen(false)} onConfirm={confirmApply} />
      )}
    </Shell>
  );
}

// ───────────────────────── 화면 조각 ─────────────────────────

function Shell({ title, badge, source, right, children }) {
  return (
    <section className="aln glass-panel animate-fade-in" aria-label="AI 학습 내비게이터">
      <header className="aln-head">
        <div className="aln-head-title">
          <span className="aln-head-icon"><Compass size={18} /></span>
          <h3>{title}</h3>
          {badge && <span className="aln-badge">{badge}</span>}
          {source === 'AI_ASSISTED' && <span className="aln-chip is-ai" title="AI 가 문구를 다듬었어요(시간·대상은 규칙으로 확정)"><Sparkles size={12} /> AI 보강</span>}
          {source === 'RULE_BASED' && <span className="aln-chip" title="학습 데이터 규칙으로 구성했어요">규칙 기반</span>}
        </div>
        {right}
      </header>
      {children}
    </section>
  );
}

function EmptyState({ icon, title, message, children }) {
  return (
    <div className="aln-empty">
      <div className="aln-empty-icon">{icon}</div>
      <b>{title}</b>
      {message && <p>{message}</p>}
      {children}
    </div>
  );
}

function Skeleton() {
  return (
    <div className="aln-skeleton" aria-label="불러오는 중">
      <div /><div /><div />
      <p>학습 데이터를 모아 AI 가 계획을 구성하고 있어요…</p>
    </div>
  );
}

function Warnings({ warnings }) {
  const list = (warnings || []).map(warningText).filter(Boolean);
  if (!list.length) return null;
  return (
    <ul className="aln-warnings">
      {list.map((w, i) => <li key={i}><AlertTriangle size={14} /> {w}</li>)}
    </ul>
  );
}

function ReadyView({ data, rec, roadmap, minutes, onStart, focusActive, canApply, onApply, onOpenPlanner }) {
  const result = data.result || {};
  const item = findItem(data.items, rec.itemId);
  const total = rec.estimatedMinutes ?? sumActivityMinutes(rec.activities);
  const quiz = rec.quizInsight;
  const weak = Array.isArray(quiz?.weakConcepts) ? quiz.weakConcepts : [];
  const untagged = Array.isArray(quiz?.untaggedWrongQuestionIds) ? quiz.untaggedWrongQuestionIds : [];
  const due = item?.dueDate ? dueLabel(item.dueDate, data.today) : null;
  const recovery = result.recoveryPlan;
  const partial = rec.partialPlan;
  const label = rec.nextAction?.label || `${minutes}분 학습 시작`;

  return (
    <>
      <div className="aln-hero">
        <div className="aln-hero-top">
          <span className="aln-kicker"><Target size={14} /> {roadmap ? '현재 학습 목표' : 'AI 가 고른 1순위 학습'}</span>
          {roadmap && item && <span className="aln-meta">{stepLabel(item)}{item.checklistTotal > 0 ? ` · 체크리스트 ${item.checklistCompleted}/${item.checklistTotal}` : ''}</span>}
        </div>
        <h4 className="aln-hero-title">{rec.title}</h4>
        {!roadmap && item && (
          <div className="aln-tags">
            {item.subject && <span className="aln-tag">{item.subject}</span>}
            {item.priority && <span className="aln-tag">우선순위 {item.priority}</span>}
            {item.dueDate && <span className={`aln-tag ${due && due.includes('지남') ? 'is-danger' : ''}`}>마감 {formatDateKo(item.dueDate)}{due ? ` · ${due}` : ''}</span>}
            {item.scheduledDate && <span className="aln-tag">예정 {formatDateKo(item.scheduledDate)}</span>}
          </div>
        )}
        {rec.reason && <p className="aln-reason"><Lightbulb size={15} /> <span>{rec.reason}</span></p>}
        {rec.coachingMessage && <blockquote className="aln-coach">{rec.coachingMessage}</blockquote>}
      </div>

      <div className="aln-section">
        <div className="aln-section-head">
          <h5><ListChecks size={15} /> 이번 {minutes}분 학습 활동</h5>
          <span className="aln-total" title="시간은 모두 추정치예요"><Timer size={13} /> 예상 {total}분 <small>(추정)</small></span>
        </div>
        <ol className="aln-activities">
          {(rec.activities || []).map((a) => (
            <li key={`${a.order}-${a.type}`} className={`aln-activity t-${String(a.type || '').toLowerCase()}`}>
              <span className="aln-activity-no">{a.order}</span>
              <div className="aln-activity-main">
                <div className="aln-activity-top">
                  <span className="aln-activity-type">{ACTIVITY_LABEL[a.type] || a.type}</span>
                  <span className="aln-activity-min">{a.minutes}분</span>
                </div>
                <b>{a.title}</b>
                {a.description && <p>{a.description}</p>}
              </div>
              <span className="aln-bar" style={{ width: `${total ? Math.max(6, Math.round((a.minutes / total) * 100)) : 0}%` }} aria-hidden="true" />
            </li>
          ))}
        </ol>
      </div>

      {roadmap && (
        <div className="aln-section">
          <h5><HelpCircle size={15} /> 퀴즈 오답 반영</h5>
          {weak.length > 0 ? (
            <div className="aln-tags">
              {weak.map((w) => <span key={w.concept} className="aln-tag is-danger">{w.concept} · 오답 {w.wrongCount}</span>)}
            </div>
          ) : untagged.length > 0 ? (
            <p className="aln-muted">최근 퀴즈 오답 {untagged.length}개를 다시 푸는 활동을 넣었어요. (문항에 개념 표시가 없어 개념 이름은 붙이지 않았어요)</p>
          ) : (
            <p className="aln-muted">{data.quiz?.available ? '최근 퀴즈 오답이 없어 일반 코칭으로 구성했어요.' : '이 로드맵 자료로 푼 퀴즈 기록이 없어 일반 코칭으로 구성했어요.'}</p>
          )}
        </div>
      )}

      {!roadmap && Array.isArray(rec.scoreBreakdown) && rec.scoreBreakdown.length > 0 && (
        <details className="aln-section aln-details" open>
          <summary><h5><Flag size={15} /> 선정 근거 <span className="aln-score">{rec.score}점</span></h5></summary>
          <ul className="aln-breakdown">
            {rec.scoreBreakdown.map((b, i) => (
              <li key={`${b.factor}-${i}`}>
                <span className="aln-factor">{FACTOR_LABEL[b.factor] || b.factor}</span>
                <span className="aln-factor-detail">{b.detail}</span>
                <span className="aln-points">+{b.points}</span>
              </li>
            ))}
          </ul>
        </details>
      )}

      {!roadmap && Array.isArray(result.alternatives) && result.alternatives.length > 0 && (
        <div className="aln-section">
          <h5><Compass size={15} /> 다른 후보</h5>
          <ul className="aln-alts">
            {result.alternatives.map((a) => (
              <li key={a.itemId}>
                <span className="aln-rank">{a.rank}순위</span>
                <div>
                  <b>{a.title}</b>
                  <p>{a.reason} · {a.score}점</p>
                </div>
                {onOpenPlanner && (
                  <button type="button" className="aln-icon-btn" onClick={() => onOpenPlanner(a.itemId)} title="플래너 열기" aria-label={`${a.title} 플래너 열기`}>
                    <ExternalLink size={14} />
                  </button>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {Array.isArray(rec.checkQuestions) && rec.checkQuestions.length > 0 && (
        <div className="aln-section">
          <h5><CheckCircle2 size={15} /> 스스로 점검</h5>
          <ul className="aln-questions">
            {rec.checkQuestions.map((q, i) => <li key={i}><Circle size={12} /> {q}</li>)}
          </ul>
        </div>
      )}

      {partial?.isPartial && (
        <div className="aln-section aln-partial">
          <h5><CalendarClock size={15} /> 이번에는 일부만 진행해요</h5>
          <p className="aln-muted">
            남은 예상 {partial.remainingMinutes}분 중 이번에 {partial.thisSessionMinutes}분 · 이후 {partial.remainingAfterSession}분
            ({partial.sessionsNeeded}회로 나눠 진행{partial.truncated ? ', 일부 생략' : ''})
          </p>
          <SessionList sessions={partial.sessions} today={data.today} items={data.items} />
        </div>
      )}

      {recovery && (
        <div className="aln-section aln-recovery">
          <h5><CalendarClock size={15} /> 학습 복구 제안</h5>
          {recovery.message && <p>{recovery.message}</p>}
          {Array.isArray(recovery.sessions) && <SessionList sessions={recovery.sessions} today={data.today} items={data.items} />}
          {Array.isArray(recovery.items) && (
            <ul className="aln-sessions">
              {recovery.items.map((it) => (
                <li key={`${it.itemId}-${it.proposal?.date}`}>
                  <span className="aln-session-date">{formatDateKo(it.proposal?.date, data.today)}</span>
                  <span className="aln-session-title">{it.title}</span>
                  <span className="aln-session-min">{it.proposal?.minutes}분</span>
                  <small className="aln-session-why">{it.delayType === 'OVERDUE' ? `마감 ${it.delayDays}일 지남` : `예정일 ${it.delayDays}일 지남`}</small>
                </li>
              ))}
            </ul>
          )}
          <p className="aln-hint">제안일 뿐이에요. ‘일정에 반영’을 눌러 확인한 항목만 저장됩니다.</p>
        </div>
      )}

      <div className="aln-actions">
        <button type="button" className="aln-btn is-primary" onClick={onStart} disabled={focusActive}>
          <Play size={15} /> {focusActive ? '학습 진행 중' : label}
        </button>
        {canApply && (
          <button type="button" className="aln-btn is-ghost" onClick={onApply}>
            <CalendarPlus size={15} /> 일정에 반영
          </button>
        )}
      </div>
    </>
  );
}

function SessionList({ sessions, today, items }) {
  if (!Array.isArray(sessions) || !sessions.length) return null;
  return (
    <ul className="aln-sessions">
      {sessions.map((s) => (
        <li key={`${s.itemId}-${s.date}-${s.order}`}>
          <span className="aln-session-date">{formatDateKo(s.date, today)}</span>
          <span className="aln-session-title">{findItem(items, s.itemId)?.title || ''}</span>
          <span className="aln-session-min">{s.minutes}분</span>
        </li>
      ))}
    </ul>
  );
}

function ApplyDialog({ changes, today, selected, setSelected, applying, error, onCancel, onConfirm }) {
  const count = changes.filter((c) => selected[c.id]).length;
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onCancel(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onCancel]);
  const body = (
    <div className="aln-modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onCancel(); }}>
      <div className="aln-modal" role="dialog" aria-modal="true" aria-labelledby="aln-apply-title">
        <div className="aln-modal-head">
          <h4 id="aln-apply-title"><CalendarPlus size={17} /> 일정에 반영할까요?</h4>
          <button type="button" className="aln-icon-btn" onClick={onCancel} disabled={applying} aria-label="닫기"><X size={16} /></button>
        </div>
        <p className="aln-muted">체크한 항목만 저장됩니다. 학습 세션은 주간 일정에 추가되고, 플래너 날짜 변경은 예정일만 바꿉니다(내용·마감일은 그대로).</p>
        <ul className="aln-change-list">
          {changes.map((c) => (
            <li key={c.id}>
              <label>
                <input type="checkbox" checked={!!selected[c.id]} disabled={applying}
                  onChange={(e) => setSelected((s) => ({ ...s, [c.id]: e.target.checked }))} />
                <span className="aln-change-kind">{c.kind === 'RESCHEDULE_PLANNER' ? '플래너 날짜 변경' : '주간 일정 추가'}</span>
                <span className="aln-change-title">{c.title}</span>
                <span className="aln-change-when">{changeText(c, today)}</span>
              </label>
            </li>
          ))}
        </ul>
        {error && <div className="aln-error is-inline" role="alert"><AlertTriangle size={16} /><div><b>{error.title}</b><p>{error.message}</p></div></div>}
        <div className="aln-modal-actions">
          <button type="button" className="aln-btn is-ghost" onClick={onCancel} disabled={applying}>취소</button>
          <button type="button" className="aln-btn is-primary" onClick={onConfirm} disabled={applying || count === 0}>
            {applying ? '반영 중…' : `${count}건 반영`}
          </button>
        </div>
      </div>
    </div>
  );
  return typeof document !== 'undefined' ? createPortal(body, document.body) : body;
}

function FocusPanel({ focus, onChange, onOpenChecklist }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (focus.pausedAt) return undefined;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [focus.pausedAt]);
  const elapsedSec = Math.max(0, ((focus.pausedAt || now) - focus.startedAt - (focus.pausedMs || 0)) / 1000);
  const p = useMemo(() => focusProgress(focus.activities, focus.minutes, elapsedSec), [focus.activities, focus.minutes, elapsedSec]);
  const current = p.index >= 0 ? focus.activities[p.index] : null;
  const pause = () => onChange({ ...focus, pausedAt: Date.now() });
  const resume = () => onChange({ ...focus, pausedAt: null, pausedMs: (focus.pausedMs || 0) + (Date.now() - focus.pausedAt) });
  return (
    <div className={`aln-focus ${p.done ? 'is-done' : ''}`} role="timer" aria-live="polite">
      <div className="aln-focus-top">
        <span className="aln-kicker"><Timer size={14} /> {p.done ? '학습 세션 완료' : focus.pausedAt ? '일시정지' : '학습 중'}</span>
        <span className="aln-focus-clock">{formatClock(p.remainingSec)}</span>
      </div>
      <b className="aln-focus-title">{focus.title}</b>
      {!p.done && current && (
        <p className="aln-focus-now">지금: {ACTIVITY_LABEL[current.type] || ''} · {current.title} ({current.minutes}분)</p>
      )}
      {p.done && <p className="aln-focus-now">수고했어요! 마친 과제는 체크리스트에서 직접 완료로 표시해 주세요. (자동으로 완료 처리하지 않아요)</p>}
      <div className="aln-progress"><span style={{ width: `${p.percent}%` }} /></div>
      <div className="aln-focus-actions">
        {!p.done && (focus.pausedAt
          ? <button type="button" className="aln-btn is-ghost" onClick={resume}><Play size={14} /> 계속</button>
          : <button type="button" className="aln-btn is-ghost" onClick={pause}><Pause size={14} /> 일시정지</button>)}
        {p.done && onOpenChecklist && <button type="button" className="aln-btn is-primary" onClick={onOpenChecklist}><ListChecks size={14} /> 체크리스트 열기</button>}
        <button type="button" className="aln-btn is-ghost" onClick={() => onChange(null)}><Square size={14} /> {p.done ? '닫기' : '종료'}</button>
      </div>
      {!p.done && <small className="aln-hint">학습 기록은 자동으로 저장하지 않아요. 이 화면을 떠났다 돌아와도 타이머는 이어집니다.</small>}
    </div>
  );
}
