import React, { useEffect, useState, useCallback } from 'react';
import { Sparkles, ListChecks, AlertTriangle, CheckCircle2, ThumbsUp, Clock, ArrowRight, RefreshCw } from 'lucide-react';
import { plannerService } from '../services/api';

/**
 * 공부 플래너 전용 AI 패널 — "학습 실행 관리"만 담당한다.
 *  - 로드맵 / 퀴즈 / 문서 기반 AI 질문 / PDF 요약 없음.
 *  - 플래너를 실행 가능한 계획으로 정리하고 피드백 + 다음 학습을 추천한다.
 *  - 사용자가 직접 쓴 메모는 AI가 덮어쓰지 않는다(원본 보존).
 *  brower → Spring(/api/planners/{id}/ai-assist) → FastAPI(/api/ai/planner/assist).
 */
const GREEN = '#69CB5B';
const GREEN_DARK = '#15803D';

export default function PlannerAiPanel({ plannerId }) {
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const loadSaved = useCallback(async () => {
    if (!plannerId) return;
    try {
      const r = await plannerService.getPlannerAiResult(plannerId);
      setResult(r && r.success ? r : null);
    } catch (_) { /* noop */ }
  }, [plannerId]);

  useEffect(() => { setResult(null); setError(''); loadSaved(); }, [plannerId, loadSaved]);

  const handleAssist = async () => {
    if (!plannerId) return;
    setLoading(true); setError('');
    try {
      const res = await plannerService.assistPlanner(plannerId);
      if (res && res.success === false) setError(res.message || 'AI 피드백 생성에 실패했습니다.');
      else setResult(res);
    } catch (e) {
      setError(e.response?.data?.message || 'AI 피드백 요청 중 오류가 발생했습니다.');
    } finally { setLoading(false); }
  };

  if (!plannerId) {
    return (
      <section className="rounded-[20px] border border-[#E5E7EB] bg-white p-6 shadow-[0_2px_8px_rgba(0,0,0,0.04)]">
        <div className="flex items-center gap-2 text-[16px] font-extrabold text-[#111827]">
          <Sparkles size={18} style={{ color: GREEN_DARK }} /> AI 피드백 및 다음 학습 추천
        </div>
        <p className="mt-2 text-[13px] text-[#6B7280]">플래너를 먼저 저장하면 AI가 오늘 계획을 정리하고 피드백을 줍니다.</p>
      </section>
    );
  }

  return (
    <section className="flex flex-col gap-5 rounded-[20px] border border-[#E5E7EB] bg-white p-6 shadow-[0_2px_8px_rgba(0,0,0,0.04)]">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-[16px] font-extrabold text-[#111827]">
          <Sparkles size={18} style={{ color: GREEN_DARK }} /> AI 피드백 및 다음 학습 추천
        </div>
        <button onClick={handleAssist} disabled={loading}
          className="inline-flex h-10 items-center gap-1.5 rounded-full bg-[#69CB5B] px-4 text-[13px] font-bold text-white transition hover:bg-[#5cb84f] disabled:opacity-60">
          <RefreshCw size={15} style={{ color: '#fff' }} className={loading ? 'animate-spin' : ''} />
          {loading ? 'AI 분석 중…' : (result ? 'AI 피드백 갱신' : 'AI 도움 받기')}
        </button>
      </div>

      {error && (
        <div className="rounded-xl border border-[#FECACA] bg-[#FEF2F2] px-4 py-3 text-[13px] text-[#991B1B]">{error}</div>
      )}

      {!result && !loading && (
        <p className="text-[13px] text-[#6B7280]">오늘 적은 목표·할 일·메모를 바탕으로 AI가 실행 가능한 계획으로 정리하고 다음 학습을 추천합니다. 메모는 그대로 보존돼요.</p>
      )}

      {result && (
        <div className="flex flex-col gap-4">
          {result.usedFallback && (
            <div className="rounded-lg bg-[#FFFBEB] px-3 py-2 text-[12px] text-[#92400E]">
              AI 서버 연결 전이라 기본 분석을 표시합니다. 잠시 후 다시 시도하면 더 정밀한 피드백을 받을 수 있어요.
            </div>
          )}

          {result.aiSummary && (
            <Block icon={<Sparkles size={16} style={{ color: GREEN_DARK }} />} title="AI 요약">
              <p className="m-0 text-[14px] leading-7 text-[#374151] whitespace-pre-wrap">{result.aiSummary}</p>
            </Block>
          )}

          {result.refinedGoal && (
            <Block icon={<CheckCircle2 size={16} style={{ color: GREEN_DARK }} />} title="정리된 학습 목표">
              <p className="m-0 text-[14px] leading-7 text-[#374151] whitespace-pre-wrap">{result.refinedGoal}</p>
            </Block>
          )}

          {arr(result.taskBreakdown).length > 0 && (
            <Block icon={<ListChecks size={16} style={{ color: GREEN_DARK }} />} title="할 일 정리">
              <BulletList items={result.taskBreakdown} />
            </Block>
          )}

          {result.timeFeedback && (
            <Block icon={<Clock size={16} style={{ color: '#3B82F6' }} />} title="시간 진행 상태" accent="#3B82F6">
              <p className="m-0 text-[14px] leading-7 text-[#374151] whitespace-pre-wrap">{result.timeFeedback}</p>
            </Block>
          )}

          {arr(result.strengths).length > 0 && (
            <Block icon={<ThumbsUp size={16} style={{ color: GREEN_DARK }} />} title="장점">
              <BulletList items={result.strengths} />
            </Block>
          )}

          {arr(result.concerns).length > 0 && (
            <Block icon={<AlertTriangle size={16} style={{ color: '#D97706' }} />} title="우려사항" accent="#F59E0B">
              <BulletList items={result.concerns} />
            </Block>
          )}

          {arr(result.recommendations).length > 0 && (
            <Block icon={<Sparkles size={16} style={{ color: '#7C3AED' }} />} title="권장사항" accent="#8B5CF6">
              <BulletList items={result.recommendations} />
            </Block>
          )}

          {arr(result.nextActions).length > 0 && (
            <Block icon={<ArrowRight size={16} style={{ color: GREEN_DARK }} />} title="다음 학습 행동">
              <BulletList items={result.nextActions} />
            </Block>
          )}
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
