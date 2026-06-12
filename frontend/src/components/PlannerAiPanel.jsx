import React, { useEffect, useState, useCallback } from 'react';
import { Sparkles, ListChecks, AlertTriangle, CheckCircle2, HelpCircle, RefreshCw, Map as MapIcon, Clock } from 'lucide-react';
import { plannerService } from '../services/api';

/**
 * 공부 플래너 전용 AI 패널 — 자료보관함 PDF AI와 분리된 "학습 실행 관리" 화면.
 *  2) AI 학습 실행 계획  3) 플래너 기반 AI 질문  4) 회고/복습  + F) 12주 로드맵.
 *  brower → Spring(/api/planners/{id}/ai-expand | roadmap/generate) → FastAPI.
 */
const GREEN = '#69CB5B';
const GREEN_DARK = '#15803D';

export default function PlannerAiPanel({ plannerId }) {
  const [aiResult, setAiResult] = useState(null);
  const [roadmap, setRoadmap] = useState(null);
  const [loadingExpand, setLoadingExpand] = useState(false);
  const [loadingRoadmap, setLoadingRoadmap] = useState(false);
  const [error, setError] = useState('');
  const [retro, setRetro] = useState({ done: '', stuck: '', next: '' });

  // 저장된 결과 로드
  const loadSaved = useCallback(async () => {
    if (!plannerId) return;
    try {
      const [r, rm] = await Promise.allSettled([
        plannerService.getPlannerAiResult(plannerId),
        plannerService.getPlannerRoadmap(plannerId),
      ]);
      if (r.status === 'fulfilled' && r.value && r.value.success) setAiResult(r.value); else setAiResult(null);
      if (rm.status === 'fulfilled' && rm.value && rm.value.success) setRoadmap(rm.value); else setRoadmap(null);
    } catch (_) { /* noop */ }
  }, [plannerId]);

  useEffect(() => { setAiResult(null); setRoadmap(null); setError(''); loadSaved(); }, [plannerId, loadSaved]);

  const handleExpand = async () => {
    if (!plannerId) return;
    setLoadingExpand(true); setError('');
    try {
      const res = await plannerService.expandPlanner(plannerId);
      if (res && res.success === false) setError(res.message || 'AI 확장에 실패했습니다.');
      else setAiResult(res);
    } catch (e) {
      setError(e.response?.data?.message || 'AI 확장 요청 중 오류가 발생했습니다.');
    } finally { setLoadingExpand(false); }
  };

  const handleRoadmap = async () => {
    if (!plannerId) return;
    setLoadingRoadmap(true); setError('');
    try {
      const res = await plannerService.generatePlannerRoadmap(plannerId);
      if (res && res.success === false) setError(res.message || '로드맵 생성에 실패했습니다.');
      else setRoadmap(res);
    } catch (e) {
      setError(e.response?.data?.message || '로드맵 생성 요청 중 오류가 발생했습니다.');
    } finally { setLoadingRoadmap(false); }
  };

  if (!plannerId) {
    return (
      <section className="rounded-[20px] border border-[#E5E7EB] bg-white p-6 shadow-[0_2px_8px_rgba(0,0,0,0.04)]">
        <div className="flex items-center gap-2 text-[16px] font-extrabold text-[#111827]">
          <Sparkles size={18} style={{ color: GREEN_DARK }} /> AI 학습 실행 관리
        </div>
        <p className="mt-2 text-[13px] text-[#6B7280]">플래너를 먼저 저장하면 AI 학습 실행 계획과 12주 로드맵을 생성할 수 있어요.</p>
      </section>
    );
  }

  return (
    <section className="flex flex-col gap-5 rounded-[20px] border border-[#E5E7EB] bg-white p-6 shadow-[0_2px_8px_rgba(0,0,0,0.04)]">
      {/* 헤더 + 액션 */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-[16px] font-extrabold text-[#111827]">
          <Sparkles size={18} style={{ color: GREEN_DARK }} /> AI 학습 실행 관리
        </div>
        <div className="flex flex-wrap gap-2">
          <button onClick={handleExpand} disabled={loadingExpand}
            className="inline-flex h-10 items-center gap-1.5 rounded-full bg-[#69CB5B] px-4 text-[13px] font-bold text-white transition hover:bg-[#5cb84f] disabled:opacity-60">
            <RefreshCw size={15} style={{ color: '#fff' }} className={loadingExpand ? 'animate-spin' : ''} />
            {loadingExpand ? 'AI 분석 중…' : (aiResult ? '학습 계획 갱신' : 'AI 학습 계획 생성')}
          </button>
          <button onClick={handleRoadmap} disabled={loadingRoadmap}
            className="inline-flex h-10 items-center gap-1.5 rounded-full border border-[#E7F1E4] bg-[#F4FBF2] px-4 text-[13px] font-bold text-[#15803D] transition hover:bg-[#EAF8E5] disabled:opacity-60">
            <MapIcon size={15} style={{ color: GREEN_DARK }} />
            {loadingRoadmap ? '로드맵 생성 중…' : 'AI 12주 로드맵 생성'}
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-xl border border-[#FECACA] bg-[#FEF2F2] px-4 py-3 text-[13px] text-[#991B1B]">{error}</div>
      )}

      {!aiResult && !loadingExpand && (
        <p className="text-[13px] text-[#6B7280]">대충 적은 주차/목표/할 일을 AI가 깊게 확장해 학습 실행 계획으로 만들어 줍니다. 위 버튼을 눌러보세요.</p>
      )}

      {/* 2. AI 학습 실행 계획 */}
      {aiResult && (
        <div className="flex flex-col gap-4">
          {aiResult.expandedGoal && (
            <Block icon={<Sparkles size={16} style={{ color: GREEN_DARK }} />} title="AI가 확장한 학습 목표">
              <p className="m-0 text-[14px] leading-7 text-[#374151] whitespace-pre-wrap">{aiResult.expandedGoal}</p>
              {aiResult.estimatedTime && (
                <div className="mt-2 inline-flex items-center gap-1 rounded-full bg-[#F4FBF2] px-3 py-1 text-[12px] font-bold text-[#15803D]">
                  <Clock size={13} style={{ color: GREEN_DARK }} /> 예상 소요: {aiResult.estimatedTime}
                </div>
              )}
            </Block>
          )}
          {arr(aiResult.expandedTodos).length > 0 && (
            <Block icon={<ListChecks size={16} style={{ color: GREEN_DARK }} />} title="세분화된 할 일">
              <BulletList items={aiResult.expandedTodos} />
            </Block>
          )}
          {arr(aiResult.studyOrder).length > 0 && (
            <Block icon={<ListChecks size={16} style={{ color: '#3B82F6' }} />} title="권장 학습 순서" accent="#3B82F6">
              <ol className="m-0 flex list-decimal flex-col gap-1.5 pl-5 text-[14px] leading-6 text-[#374151]">
                {aiResult.studyOrder.map((s, i) => <li key={i}>{s}</li>)}
              </ol>
            </Block>
          )}
          {arr(aiResult.riskPoints).length > 0 && (
            <Block icon={<AlertTriangle size={16} style={{ color: '#D97706' }} />} title="이번 주 위험 포인트" accent="#F59E0B">
              <BulletList items={aiResult.riskPoints} />
            </Block>
          )}
          {arr(aiResult.todayCheckpoints).length > 0 && (
            <Block icon={<CheckCircle2 size={16} style={{ color: GREEN_DARK }} />} title="오늘의 체크포인트">
              <BulletList items={aiResult.todayCheckpoints} />
            </Block>
          )}

          {/* 3. 플래너 기반 AI 질문 */}
          {arr(aiResult.aiQuestions).length > 0 && (
            <Block icon={<HelpCircle size={16} style={{ color: '#7C3AED' }} />} title="플래너 기반 AI 질문" accent="#8B5CF6">
              <BulletList items={aiResult.aiQuestions} />
            </Block>
          )}

          {/* 4. 회고/복습 */}
          <Block icon={<RefreshCw size={16} style={{ color: GREEN_DARK }} />} title="회고 / 복습">
            {arr(aiResult.reflectionPrompts).length > 0 && (
              <div className="mb-3">
                <div className="mb-1.5 text-[12px] font-bold text-[#15803D]">AI 회고 질문</div>
                <BulletList items={aiResult.reflectionPrompts} />
              </div>
            )}
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
              <RetroField label="오늘 완료한 일" value={retro.done} onChange={(v) => setRetro((r) => ({ ...r, done: v }))} />
              <RetroField label="막힌 점" value={retro.stuck} onChange={(v) => setRetro((r) => ({ ...r, stuck: v }))} />
              <RetroField label="다음 학습 계획" value={retro.next} onChange={(v) => setRetro((r) => ({ ...r, next: v }))} />
            </div>
          </Block>
        </div>
      )}

      {/* F. 12주 로드맵 */}
      {roadmap && arr(roadmap.weeks).length > 0 && (
        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-2 text-[15px] font-extrabold text-[#111827]">
            <MapIcon size={17} style={{ color: GREEN_DARK }} /> {roadmap.title || 'AI 12주 로드맵'}
            <span className="rounded-full bg-[#F4FBF2] px-2 py-0.5 text-[11px] font-bold text-[#15803D]">{arr(roadmap.weeks).length}주</span>
          </div>
          <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
            {roadmap.weeks.map((w) => (
              <div key={w.week} className="rounded-xl border border-[#E7F1E4] bg-[#F9FEF8] p-3.5">
                <div className="mb-1 flex items-center gap-2">
                  <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-[#69CB5B] text-[11px] font-extrabold text-white">{w.week}</span>
                  <span className="text-[13px] font-bold text-[#111827]">{w.title}</span>
                </div>
                {w.goal && <p className="m-0 mb-1.5 text-[12px] text-[#6B7280]">{w.goal}</p>}
                <ul className="m-0 flex list-disc flex-col gap-1 pl-4 text-[12px] leading-5 text-[#374151]">
                  {arr(w.tasks).map((t, i) => <li key={i}>{t}</li>)}
                </ul>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

function arr(v) { return Array.isArray(v) ? v : []; }

function Block({ icon, title, accent = GREEN, children }) {
  return (
    <div className="rounded-xl border border-[#E5E7EB] bg-white p-4" style={{ borderLeft: `4px solid ${accent}` }}>
      <div className="mb-2 flex items-center gap-1.5 text-[14px] font-bold text-[#111827]">{icon}{title}</div>
      {children}
    </div>
  );
}

function BulletList({ items }) {
  return (
    <ul className="m-0 flex list-disc flex-col gap-1.5 pl-5 text-[14px] leading-6 text-[#374151]">
      {arr(items).map((it, i) => <li key={i}>{it}</li>)}
    </ul>
  );
}

function RetroField({ label, value, onChange }) {
  return (
    <div>
      <label className="mb-1 block text-[12px] font-bold text-[#374151]">{label}</label>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="min-h-[64px] w-full resize-y rounded-lg border border-[#D1D5DB] p-2 text-[13px] text-[#111827] outline-none focus:border-[#69CB5B]"
      />
    </div>
  );
}
