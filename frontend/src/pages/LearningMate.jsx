import React, { useState, useRef } from 'react';
import { Sparkles, MessageCircleQuestion, Check, Settings2, Loader2, Lightbulb, HelpCircle, Scale, Drama } from 'lucide-react';
import { learningMateService } from '../services/api';

// 질문 중심 AI 학습메이트 — 같은 질문을 4가지 학습 방식으로 다시 보기 + 빠른 조정.
// 기존 멀티에이전트 룸 채팅(StudyMate.jsx)과 분리된 신규 화면. 답변 생성은 /api/learning-mate/chat 경유(기존 AI 흐름).

const MODES = [
  { value: 'explain', label: '기본 설명', icon: Lightbulb, desc: '개념을 빠르게 정리하고 예시와 함께 설명합니다.', result: '개념 정리 · 예시 · 핵심 요약' },
  { value: 'socratic', label: '소크라테스', icon: HelpCircle, desc: '정답을 바로 주지 않고 질문과 힌트로 이해를 유도합니다.', result: '단계별 질문 · 힌트 · 오개념 확인' },
  { value: 'debate', label: '토론', icon: Scale, desc: '장점, 단점, 반론을 비교하며 사고를 넓힙니다.', result: '주장 · 근거 · 반박 · 결론' },
  { value: 'roleplay', label: '상황극', icon: Drama, desc: '현실 상황 속 역할을 맡아 개념을 체험합니다.', result: '시나리오 · 선택지 · 피드백' },
];
const TONES = [
  { value: 'friendly', label: '친근하게' }, { value: 'calm', label: '차분하게' },
  { value: 'strict', label: '엄격하게' }, { value: 'cold', label: '냉철하게' },
  { value: 'humorous', label: '유머러스하게' },
];
// 사용자 라벨은 "학습자 수준"(지식수준 ❌) — AI가 아니라 사용자 이해 수준에 맞춰 답변 깊이를 조정한다는 의미.
const LEVELS = [
  { value: 'beginner', label: '입문' }, { value: 'undergraduate', label: '학부' },
  { value: 'advanced', label: '심화' }, { value: 'expert', label: '전문가' },
];
const QUICK_ACTIONS = [
  { value: 'easier', label: '더 쉽게' }, { value: 'deeper', label: '더 깊게' },
  { value: 'add_example', label: '예시 추가' }, { value: 'code_example', label: '코드 예시' },
  { value: 'short_summary', label: '짧게 요약' },
];
const PLACEHOLDERS = [
  '예: OOP가 뭐야?', '예: REST API랑 GraphQL 차이가 뭐야?',
  '예: 트랜잭션 격리 수준이 왜 필요해?', '예: Java의 상속과 인터페이스 차이가 뭐야?',
];
const toneLabel = (v) => (TONES.find((t) => t.value === v) || {}).label || '친근하게';
const levelLabel = (v) => (LEVELS.find((l) => l.value === v) || {}).label || '입문';

export default function LearningMate() {
  const [question, setQuestion] = useState('');
  const [selectedMode, setSelectedMode] = useState('explain');
  const [mate, setMate] = useState({ name: '돌리', tone: 'friendly', learnerLevel: 'beginner', customInstruction: '' });
  const [isMateSettingOpen, setMateSettingOpen] = useState(false);

  const [result, setResult] = useState(null); // 서버 응답(summaryLabel/answer/mode/...)
  const [lastQuestion, setLastQuestion] = useState('');
  const [loading, setLoading] = useState(false);
  const [loadingKind, setLoadingKind] = useState('generate'); // generate | remode | quick
  const [error, setError] = useState(null);
  const sendingRef = useRef(false);

  const mateSummary = `${mate.name} · ${toneLabel(mate.tone)} 말투 · ${levelLabel(mate.learnerLevel)} 맞춤`;

  // 답변 요청 — opts: { mode, quickAction, useLastQuestion }
  const run = async (opts = {}) => {
    if (sendingRef.current) return;
    const q = opts.useLastQuestion ? lastQuestion : question.trim();
    if (!q) { setError('질문을 입력해 주세요.'); return; }
    const mode = opts.mode || (result ? result.mode : selectedMode) || selectedMode;

    sendingRef.current = true;
    setLoading(true);
    setLoadingKind(opts.quickAction ? 'quick' : (opts.useLastQuestion ? 'remode' : 'generate'));
    setError(null);
    try {
      const payload = {
        question: q,
        mode,
        previousQuestion: lastQuestion || q,
        quickAction: opts.quickAction || null,
        persona: {
          name: mate.name,
          tone: mate.tone,
          learnerLevel: mate.learnerLevel,
          customInstruction: mate.customInstruction || '',
        },
      };
      const res = await learningMateService.chat(payload);
      if (res && res.success === false) {
        setError(res.message || '답변 생성에 실패했습니다. 잠시 후 다시 시도해 주세요.');
      } else {
        setResult(res);
        setLastQuestion(res.question || q);
        setSelectedMode(res.mode || mode);
      }
    } catch (e) {
      setError('답변 생성에 실패했습니다. 잠시 후 다시 시도해 주세요.');
    } finally {
      setLoading(false);
      sendingRef.current = false;
    }
  };

  const loadingText =
    loadingKind === 'remode' ? '같은 질문을 다른 방식으로 다시 설명하고 있습니다…'
    : loadingKind === 'quick' ? '요청하신 방식으로 답변을 다듬고 있습니다…'
    : '선택한 학습 방식으로 답변을 준비하고 있습니다…';

  return (
    <div className="mx-auto max-w-3xl px-4 py-8">
      {/* 서비스 소개 */}
      <div className="mb-6">
        <div className="flex items-center gap-2 text-[#15803D]">
          <Sparkles size={22} />
          <h1 className="text-2xl font-extrabold text-[#111827]">AI 학습메이트</h1>
        </div>
        <p className="mt-2 text-[15px] text-[#374151]">질문 하나를 4가지 학습 방식으로 바꿔드립니다.</p>
        <p className="text-[13px] text-[#6B7280]">모드, 말투, 학습자 수준에 따라 답변의 깊이와 진행 방식이 달라집니다.</p>
      </div>

      {/* 질문 입력 (화면의 핵심) */}
      <label htmlFor="lm-q" className="mb-2 flex items-center gap-1.5 text-[15px] font-bold text-[#111827]">
        <MessageCircleQuestion size={18} className="text-[#15803D]" /> 무엇이 궁금한가요?
      </label>
      <textarea
        id="lm-q"
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        rows={2}
        placeholder={PLACEHOLDERS[0]}
        className="w-full resize-none rounded-xl border-2 border-[#E5E7EB] bg-white px-4 py-3 text-[15px] text-[#111827] outline-none focus:border-[#69CB5B]"
        onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) run(); }}
      />
      <div className="mt-1 text-[12px] text-[#9CA3AF]">{PLACEHOLDERS.slice(1).join('   ')}</div>

      {/* 4개 모드 카드 */}
      <div className="mt-5 mb-2 text-[14px] font-bold text-[#111827]">답변 모드 선택</div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {MODES.map((m) => {
          const Icon = m.icon;
          const active = selectedMode === m.value;
          return (
            <button
              key={m.value}
              type="button"
              aria-pressed={active}
              onClick={() => setSelectedMode(m.value)}
              className={`relative rounded-xl border-2 p-4 text-left transition ${active
                ? 'border-[#69CB5B] bg-[#F4FBF2] shadow-sm'
                : 'border-[#E5E7EB] bg-white hover:border-[#C7E9BF]'}`}
            >
              {active && (
                <span className="absolute right-3 top-3 inline-flex items-center gap-1 rounded-full bg-[#15803D] px-2 py-0.5 text-[10px] font-bold text-white">
                  <Check size={11} /> 선택됨
                </span>
              )}
              <div className="flex items-center gap-2">
                <Icon size={18} className={active ? 'text-[#15803D]' : 'text-[#6B7280]'} />
                <span className="text-[15px] font-bold text-[#111827]">{m.label}</span>
              </div>
              <p className="mt-1.5 text-[13px] leading-relaxed text-[#4B5563]">{m.desc}</p>
              <div className="mt-2 inline-block rounded-md bg-[#EEF2FF] px-2 py-1 text-[11px] font-semibold text-[#4338CA]">
                결과: {m.result}
              </div>
            </button>
          );
        })}
      </div>

      {/* 학습메이트 요약 카드 */}
      <div className="mt-5 rounded-xl border border-[#E5E7EB] bg-white p-4">
        <div className="flex items-center justify-between">
          <div className="min-w-0">
            <div className="text-[12px] font-semibold text-[#6B7280]">현재 학습메이트</div>
            <div className="mt-0.5 truncate text-[15px] font-bold text-[#111827]">{mateSummary}</div>
          </div>
          <button
            type="button"
            onClick={() => setMateSettingOpen((v) => !v)}
            className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-[#D1D5DB] px-3 py-1.5 text-[13px] font-semibold text-[#374151] hover:bg-[#F9FAFB]"
          >
            <Settings2 size={14} /> 변경
          </button>
        </div>

        {isMateSettingOpen && (
          <div className="mt-4 space-y-4 border-t border-[#F3F4F6] pt-4">
            <div>
              <div className="mb-1 text-[13px] font-semibold text-[#374151]">이름</div>
              <input
                value={mate.name}
                onChange={(e) => setMate((p) => ({ ...p, name: e.target.value }))}
                className="w-full rounded-lg border border-[#E5E7EB] px-3 py-2 text-[14px] outline-none focus:border-[#69CB5B]"
              />
            </div>
            <div>
              <div className="mb-1 text-[13px] font-semibold text-[#374151]">말투</div>
              <div className="flex flex-wrap gap-2">
                {TONES.map((t) => (
                  <Chip key={t.value} active={mate.tone === t.value} onClick={() => setMate((p) => ({ ...p, tone: t.value }))}>{t.label}</Chip>
                ))}
              </div>
            </div>
            <div>
              {/* 라벨은 반드시 "학습자 수준"(지식수준 ❌) */}
              <div className="mb-1 text-[13px] font-semibold text-[#374151]">학습자 수준 <span className="font-normal text-[#9CA3AF]">(답변 깊이)</span></div>
              <div className="flex flex-wrap gap-2">
                {LEVELS.map((l) => (
                  <Chip key={l.value} active={mate.learnerLevel === l.value} onClick={() => setMate((p) => ({ ...p, learnerLevel: l.value }))}>{l.label}</Chip>
                ))}
              </div>
            </div>
            <div>
              <div className="mb-1 text-[13px] font-semibold text-[#374151]">추가 요청</div>
              <input
                value={mate.customInstruction}
                onChange={(e) => setMate((p) => ({ ...p, customInstruction: e.target.value }))}
                placeholder="예: 코드 예시를 꼭 포함해줘 / 영어 용어는 한글 뜻도 같이 / 짧게 핵심 위주로"
                className="w-full rounded-lg border border-[#E5E7EB] px-3 py-2 text-[14px] outline-none focus:border-[#69CB5B]"
              />
            </div>
          </div>
        )}
      </div>

      {/* 답변 생성 */}
      <button
        type="button"
        onClick={() => run()}
        disabled={loading}
        className="mt-5 flex w-full items-center justify-center gap-2 rounded-xl bg-[#69CB5B] px-4 py-3 text-[15px] font-bold text-white transition hover:bg-[#5BB94F] disabled:opacity-60"
      >
        {loading ? <><Loader2 size={18} className="animate-spin" /> {loadingText}</> : '답변 생성'}
      </button>

      {error && (
        <div className="mt-4 rounded-xl border border-[#FECACA] bg-[#FEF2F2] px-4 py-3 text-[14px] text-[#B91C1C]">{error}</div>
      )}

      {/* 답변 영역 */}
      {result && result.answer && (
        <div className="mt-6 rounded-2xl border border-[#E5E7EB] bg-white p-5">
          <div className="text-[12px] font-semibold text-[#6B7280]">질문</div>
          <div className="mt-0.5 text-[16px] font-bold text-[#111827]">{result.question}</div>

          <div className="mt-3 text-[12px] font-semibold text-[#6B7280]">답변 방식</div>
          <div className="mt-0.5 inline-block rounded-md bg-[#F4FBF2] px-2 py-1 text-[13px] font-bold text-[#15803D]">{result.summaryLabel}</div>

          <div className="mt-4 whitespace-pre-wrap text-[15px] leading-relaxed text-[#1F2937]">{result.answer}</div>

          {/* 같은 질문 다른 방식으로 보기 */}
          <div className="mt-6 border-t border-[#F3F4F6] pt-4">
            <div className="mb-2 text-[13px] font-bold text-[#111827]">같은 질문을 다른 방식으로 보기</div>
            <div className="flex flex-wrap gap-2">
              {MODES.map((m) => (
                <Chip
                  key={m.value}
                  active={result.mode === m.value}
                  disabled={loading || result.mode === m.value}
                  onClick={() => run({ mode: m.value, useLastQuestion: true })}
                >{m.label}</Chip>
              ))}
            </div>
          </div>

          {/* 빠른 조정 */}
          <div className="mt-4">
            <div className="mb-2 text-[13px] font-bold text-[#111827]">빠른 조정</div>
            <div className="flex flex-wrap gap-2">
              {QUICK_ACTIONS.map((q) => (
                <Chip key={q.value} disabled={loading} onClick={() => run({ mode: result.mode, useLastQuestion: true, quickAction: q.value })}>{q.label}</Chip>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Chip({ active, disabled, onClick, children }) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      aria-pressed={!!active}
      className={`rounded-full border px-3 py-1.5 text-[13px] font-semibold transition disabled:opacity-50 ${active
        ? 'border-[#69CB5B] bg-[#69CB5B] text-white'
        : 'border-[#D1D5DB] bg-white text-[#374151] hover:border-[#69CB5B] hover:text-[#15803D]'}`}
    >
      {children}
    </button>
  );
}
