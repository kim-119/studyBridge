import React, { useEffect, useState } from 'react';
import { reviewNoteService } from '../../services/api';
import { sanitizeMarkdownText } from '../../utils/markdown';

/**
 * 오답노트 복습 기능 패널(다시 풀기 / 유사문제 / AI 해설) — 재사용 단일 소스.
 *  - /review-notes 페이지(ReviewNotesPage)와 자료보관함 REVIEW_NOTE 상세(ReviewNoteArchiveDetail)가 공유한다.
 *  - 실제 기능 실행은 여기(=오답노트 도메인)에서만 한다. PDF 상세는 설명/진입 UI만 둔다.
 */

export const DIFFICULTY_LABEL = { easy: '쉬움', medium: '보통', normal: '보통', hard: '어려움' };
export const VARIANT_LEVELS = [
  { label: '하', value: 'easy' },
  { label: '중', value: 'normal' },
  { label: '상', value: 'hard' },
];

export const formatDate = (value) => {
  if (!value) return '-';
  try {
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return String(value);
    return d.toLocaleDateString('ko-KR', { year: 'numeric', month: '2-digit', day: '2-digit' });
  } catch {
    return String(value);
  }
};

export const noteId = (n) => n?.id ?? n?.reviewNoteId;
export const clean = (v) => sanitizeMarkdownText(v ?? '');

/* ---------------- 오답노트 선택(노트 미지정 시 폴백) ---------------- */
export function NotePicker({ items, onPick, label }) {
  if (!items || items.length === 0) {
    return <p style={{ color: '#6B7280', fontSize: '14px', margin: 0 }}>먼저 오답노트를 만들어 주세요. 오답노트 목록 탭에서 확인할 수 있습니다.</p>;
  }
  return (
    <div>
      <p style={{ color: '#6B7280', fontSize: '14px', marginTop: 0 }}>{label}</p>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {items.map((n) => (
          <button key={noteId(n)} style={{ ...btn, justifyContent: 'space-between', width: '100%' }} onClick={() => onPick(n)}>
            <span>{n.title || '오답노트'}</span>
            <span style={{ color: '#6B7280', fontSize: '12px' }}>오답 {n.wrongCount ?? 0}개</span>
          </button>
        ))}
      </div>
    </div>
  );
}

/* ---------------- 문제 풀이 러너(다시 풀기 / 유사문제 공통) ---------------- */
export function QuestionRunner({ questions }) {
  const [answers, setAnswers] = useState({});
  const [submitted, setSubmitted] = useState({});

  if (!questions || questions.length === 0) {
    return <p style={{ color: '#6B7280', fontSize: '14px', margin: 0 }}>표시할 문제가 없습니다.</p>;
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      {questions.map((q, qi) => {
        const choices = q.choices || q.options || [];
        const correct = q.correctAnswer ?? q.correct_answer;
        const picked = answers[qi];
        const isSubmitted = submitted[qi];
        return (
          <div key={qi} style={{ border: '1px solid #E5E7EB', borderRadius: '10px', padding: '14px' }}>
            <p style={{ margin: '0 0 10px 0', fontWeight: 700, color: '#111827', whiteSpace: 'pre-wrap' }}>
              {qi + 1}. {clean(q.question)}
            </p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              {choices.map((c, ci) => {
                const isCorrect = isSubmitted && String(c) === String(correct);
                const isWrongPick = isSubmitted && picked === ci && String(c) !== String(correct);
                return (
                  <button
                    key={ci}
                    onClick={() => !isSubmitted && setAnswers((p) => ({ ...p, [qi]: ci }))}
                    style={{
                      textAlign: 'left', padding: '8px 10px', borderRadius: '8px', fontSize: '13px', cursor: 'pointer',
                      border: `1px solid ${isCorrect ? '#15803D' : isWrongPick ? '#DC2626' : picked === ci ? '#15803D' : '#D1D5DB'}`,
                      background: isCorrect ? '#ECFDF5' : isWrongPick ? '#FEF2F2' : picked === ci ? '#F0FDF4' : '#fff',
                      color: '#374151',
                    }}
                  >
                    {clean(c)}
                  </button>
                );
              })}
            </div>
            {!isSubmitted ? (
              <button
                style={{ ...btnPrimary, marginTop: '10px', opacity: picked == null ? 0.5 : 1 }}
                disabled={picked == null}
                onClick={() => setSubmitted((p) => ({ ...p, [qi]: true }))}
              >
                제출
              </button>
            ) : (
              <div style={{ marginTop: '10px', fontSize: '13px' }}>
                <div style={{ fontWeight: 700, color: String(choices[picked]) === String(correct) ? '#15803D' : '#DC2626' }}>
                  {String(choices[picked]) === String(correct) ? '정답입니다!' : `오답입니다. 정답: ${clean(correct)}`}
                </div>
                {(q.explanation) && (
                  <p style={{ margin: '6px 0 0 0', color: '#374151', whiteSpace: 'pre-wrap', lineHeight: 1.7 }}>
                    해설: {clean(q.explanation)}
                  </p>
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

/* ---------------- 다시 풀기 ---------------- */
export function RetryPanel({ note, items, onPick }) {
  const [questions, setQuestions] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState('');

  useEffect(() => {
    if (!note) { setQuestions(null); return; }
    let alive = true;
    (async () => {
      setLoading(true); setErr('');
      try {
        const data = await reviewNoteService.retry(noteId(note));
        if (alive) setQuestions(Array.isArray(data?.questions) ? data.questions : []);
      } catch {
        if (alive) setErr('다시 풀기 문제를 불러오지 못했습니다.');
      } finally { if (alive) setLoading(false); }
    })();
    return () => { alive = false; };
  }, [note]);

  if (!note) return <NotePicker items={items} onPick={onPick} label="다시 풀 오답노트를 선택하세요." />;
  return (
    <div>
      <h2 style={panelTitle}>다시 풀기 · {note.title}</h2>
      {loading ? <p style={muted}>문제를 불러오는 중입니다.</p>
        : err ? <p style={{ ...muted, color: '#B91C1C' }}>{err}</p>
        : <QuestionRunner questions={questions} />}
    </div>
  );
}

/* ---------------- 유사문제 ---------------- */
// ai07/Spring 응답 키가 흔들려도(questions / similarQuestions / possibleSimilarQuestions / data.* / result.*)
// 항상 단일 배열로 정규화하고, 각 문항을 화면 계약(번호/본문/선택지/정답/해설/변형포인트)에 맞춰 표준화한다.
export function normalizeSimilarQuestions(response) {
  const raw =
    response?.similarQuestions ??
    response?.possibleSimilarQuestions ??
    response?.questions ??
    response?.data?.similarQuestions ??
    response?.data?.questions ??
    response?.result?.similarQuestions ??
    response?.result?.questions ??
    [];
  const list = Array.isArray(raw) ? raw : (raw && typeof raw === 'object' ? [raw] : []);
  return list.map((q, i) => {
    const choices = q?.choices || q?.options || [];
    const answer = q?.answer ?? q?.correctAnswer ?? q?.correct_answer ?? '';
    return {
      id: String(q?.id ?? q?.questionId ?? `sq-${i}`),
      number: i + 1,
      question: q?.question ?? q?.prompt ?? q?.text ?? '',
      choices: Array.isArray(choices) ? choices : [],
      answer,
      explanation: q?.explanation ?? q?.rationale ?? '',
      difficulty: q?.difficulty ?? '',
      sourceWrongNoteId: q?.sourceWrongNoteId ?? q?.wrongQuestionId ?? null,
      variationPoint: q?.variationPoint ?? q?.variation_point ?? q?.changePoint ?? q?.change_point ?? '',
    };
  });
}

// 정답 판정: 정답이 보기 텍스트일 수도, 0-base / 1-base 인덱스일 수도 있어 모두 허용한다.
function isCorrectChoice(choiceText, choiceIndex, answer) {
  const a = String(answer ?? '').trim();
  if (!a) return false;
  if (String(choiceText).trim() === a) return true;
  if (String(choiceIndex) === a) return true;       // 0-base index
  if (String(choiceIndex + 1) === a) return true;    // 1-base index
  return false;
}

/* 유사문제 1개 풀이 영역(활성 문제 전체: 본문/선택지/제출/결과/정답/해설/변형포인트) */
function SimilarQuestionSolver({ q, picked, submitted, onPick, onSubmit }) {
  const correctText = q.choices.find((c, i) => isCorrectChoice(c, i, q.answer)) ?? q.answer;
  const isRight = submitted && q.choices[picked] != null && isCorrectChoice(q.choices[picked], picked, q.answer);
  return (
    <div style={{ border: '1px solid #15803D', borderRadius: '12px', padding: '16px', background: '#fff', width: '100%', boxSizing: 'border-box' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '10px', flexWrap: 'wrap' }}>
        <span style={numBadge}>{q.number}번</span>
        {q.difficulty && <span style={diffBadge}>{DIFFICULTY_LABEL[q.difficulty] || q.difficulty}</span>}
      </div>
      <p style={{ margin: '0 0 12px 0', fontWeight: 700, color: '#111827', whiteSpace: 'pre-wrap', lineHeight: 1.7 }}>
        {clean(q.question)}
      </p>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {q.choices.length === 0 ? (
          <p style={muted}>이 문제에는 선택지가 없습니다.</p>
        ) : q.choices.map((c, ci) => {
          const showCorrect = submitted && isCorrectChoice(c, ci, q.answer);
          const showWrongPick = submitted && picked === ci && !isCorrectChoice(c, ci, q.answer);
          return (
            <button
              key={ci}
              onClick={() => !submitted && onPick(ci)}
              style={{
                textAlign: 'left', padding: '10px 12px', borderRadius: '8px', fontSize: '13.5px',
                cursor: submitted ? 'default' : 'pointer', width: '100%', boxSizing: 'border-box',
                whiteSpace: 'pre-wrap', lineHeight: 1.6,
                border: `1px solid ${showCorrect ? '#15803D' : showWrongPick ? '#DC2626' : picked === ci ? '#15803D' : '#D1D5DB'}`,
                background: showCorrect ? '#ECFDF5' : showWrongPick ? '#FEF2F2' : picked === ci ? '#F0FDF4' : '#fff',
                color: '#374151',
              }}
            >
              {ci + 1}. {clean(c)}
            </button>
          );
        })}
      </div>
      {!submitted ? (
        <button style={{ ...btnPrimary, marginTop: '12px', opacity: picked == null ? 0.5 : 1 }} disabled={picked == null} onClick={onSubmit}>
          제출
        </button>
      ) : (
        <div style={{ marginTop: '12px', fontSize: '13.5px' }}>
          <div style={{ fontWeight: 700, color: isRight ? '#15803D' : '#DC2626' }}>
            {isRight ? '정답입니다!' : '오답입니다.'}
          </div>
          <p style={{ margin: '8px 0 0 0', color: '#15803D', fontWeight: 600 }}>정답: {clean(correctText)}</p>
          {q.explanation && (
            <p style={{ margin: '8px 0 0 0', color: '#374151', whiteSpace: 'pre-wrap', lineHeight: 1.7 }}>해설: {clean(q.explanation)}</p>
          )}
          {q.variationPoint && (
            <div style={{ marginTop: '10px', background: '#F0FDF4', border: '1px solid #BBF7D0', borderRadius: '8px', padding: '10px 12px' }}>
              <span style={{ fontWeight: 700, color: '#15803D' }}>변형 포인트 </span>
              <span style={{ color: '#374151', whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>{clean(q.variationPoint)}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function VariantPanel({ note, items, onPick }) {
  const [difficulty, setDifficulty] = useState('normal');
  const [wrongQuestionId, setWrongQuestionId] = useState(1);
  const [count, setCount] = useState(3);
  const [questions, setQuestions] = useState([]);   // 정규화된 유사문제 배열(전체)
  const [activeId, setActiveId] = useState(null);    // 현재 풀이 중인 문제 id
  const [answers, setAnswers] = useState({});        // id -> 선택 index
  const [submitted, setSubmitted] = useState({});    // id -> bool
  const [usedFallback, setUsedFallback] = useState(false);
  const [generated, setGenerated] = useState(false); // 생성 시도 여부(빈 결과 안내 분기용)
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState('');

  const generate = async () => {
    setLoading(true); setErr(''); setGenerated(false);
    try {
      const data = await reviewNoteService.variantQuestion(noteId(note), {
        wrongQuestionId: Number(wrongQuestionId) || 1,
        difficulty,
        count: Number(count) || 1,
      });
      if (data && data.success === false) {
        // 서버가 명시적으로 실패를 알려준 경우 — 원인 메시지를 그대로 노출
        setErr(data.message || data.error || '유사문제 생성에 실패했습니다. 잠시 후 다시 시도해주세요.');
        setQuestions([]); setActiveId(null);
      } else {
        const qs = normalizeSimilarQuestions(data); // 응답 전체를 배열로 정규화(첫 요소만 쓰지 않음)
        setQuestions(qs);                            // 새 생성 결과로 교체 → 전부 노출
        setAnswers({}); setSubmitted({});
        setActiveId(qs.length ? qs[0].id : null);
        setUsedFallback(Boolean(data?.usedFallback));
        setGenerated(true);
      }
    } catch (e) {
      const data = e?.response?.data;
      const serverMsg = data?.message || data?.error || (typeof data === 'string' ? data : '');
      setErr(serverMsg
        ? `유사문제를 생성하지 못했습니다: ${serverMsg}`
        : '유사문제를 생성하지 못했습니다. 잠시 후 다시 시도해주세요.');
      setQuestions([]); setActiveId(null);
    } finally { setLoading(false); }
  };

  if (!note) return <NotePicker items={items} onPick={onPick} label="유사문제를 풀 오답노트를 선택하세요." />;
  const wrongCount = Math.max(1, note.wrongCount ?? 1);
  const activeQ = questions.find((q) => q.id === activeId) || null;
  const statusOf = (q) => !submitted[q.id]
    ? '풀이 전'
    : (q.choices[answers[q.id]] != null && isCorrectChoice(q.choices[answers[q.id]], answers[q.id], q.answer) ? '정답' : '오답');

  return (
    <div style={{ width: '100%', boxSizing: 'border-box' }}>
      <h2 style={panelTitle}>유사문제 풀기 · {note.title}</h2>

      {/* [유사문제 생성 컨트롤] 대상 오답 / 난이도 / 문항 수 / 생성 */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px', alignItems: 'flex-end', marginBottom: '20px' }}>
        <div>
          <label style={miniLabel}>대상 오답</label>
          <select value={wrongQuestionId} onChange={(e) => setWrongQuestionId(e.target.value)} style={selectStyle}>
            {Array.from({ length: wrongCount }, (_, i) => i + 1).map((n) => (
              <option key={n} value={n}>{n}번 오답</option>
            ))}
          </select>
        </div>
        <div>
          <label style={miniLabel}>난이도</label>
          <div style={{ display: 'flex', gap: '6px' }}>
            {VARIANT_LEVELS.map((lv) => (
              <button
                key={lv.value}
                onClick={() => setDifficulty(lv.value)}
                style={{
                  ...btn,
                  border: `1px solid ${difficulty === lv.value ? '#15803D' : '#D1D5DB'}`,
                  background: difficulty === lv.value ? '#ECFDF5' : '#fff',
                  color: difficulty === lv.value ? '#15803D' : '#374151',
                }}
              >
                {lv.label}
              </button>
            ))}
          </div>
        </div>
        <div>
          <label style={miniLabel}>문항 수</label>
          <select value={count} onChange={(e) => setCount(e.target.value)} style={selectStyle}>
            {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}개</option>)}
          </select>
        </div>
        <button style={{ ...btnPrimary, opacity: loading ? 0.6 : 1 }} disabled={loading} onClick={generate}>
          {loading ? '생성 중…' : '유사문제 생성'}
        </button>
      </div>

      {err && <p style={{ ...muted, color: '#B91C1C', marginBottom: '12px' }}>{err}</p>}

      {/* 생성 전 안내 */}
      {!err && !generated && questions.length === 0 && (
        <p style={muted}>대상 오답과 난이도·문항 수를 선택하고 유사문제를 생성해 보세요.</p>
      )}

      {/* 빈 결과 안내 — 조용히 사라지지 않게 명시한다 */}
      {!err && generated && questions.length === 0 && (
        <p style={muted}>생성된 유사문제가 없습니다. 이 오답노트에는 변형할 원본 오답 문제가 없을 수 있어요.</p>
      )}

      {questions.length > 0 && (
        <>
          {usedFallback && (
            <p style={{ ...muted, color: '#B45309', marginBottom: '12px' }}>
              AI 변형을 일시적으로 사용할 수 없어 원본 오답 문제를 다시 출제했습니다.
            </p>
          )}

          {/* [생성된 유사문제 리스트] — 전체 카드 목록(선택해도 사라지지 않음) */}
          <div style={{ marginBottom: '20px' }}>
            <h3 style={listTitle}>생성된 유사문제 ({questions.length})</h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              {questions.map((q) => {
                const st = statusOf(q);
                const active = q.id === activeId;
                return (
                  <button
                    key={q.id}
                    onClick={() => setActiveId(q.id)}
                    style={{
                      textAlign: 'left', width: '100%', boxSizing: 'border-box', cursor: 'pointer',
                      border: `1px solid ${active ? '#15803D' : '#E5E7EB'}`, background: active ? '#ECFDF5' : '#fff',
                      borderRadius: '10px', padding: '12px 14px',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px', flexWrap: 'wrap' }}>
                      <span style={numBadge}>{q.number}번</span>
                      {q.difficulty && <span style={diffBadge}>{DIFFICULTY_LABEL[q.difficulty] || q.difficulty}</span>}
                      <span style={{ ...statusBadge, ...(st === '정답' ? statusOk : st === '오답' ? statusNo : statusIdle) }}>{st}</span>
                    </div>
                    <div style={{ fontSize: '13.5px', color: '#374151', whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>
                      {clean(q.question)}
                    </div>
                  </button>
                );
              })}
            </div>
          </div>

          {/* [유사문제 풀이] — 활성 문제 전체 풀이 */}
          <div>
            <h3 style={listTitle}>유사문제 풀이</h3>
            {activeQ ? (
              <SimilarQuestionSolver
                q={activeQ}
                picked={answers[activeQ.id]}
                submitted={Boolean(submitted[activeQ.id])}
                onPick={(ci) => setAnswers((p) => ({ ...p, [activeQ.id]: ci }))}
                onSubmit={() => setSubmitted((p) => ({ ...p, [activeQ.id]: true }))}
              />
            ) : (
              <p style={muted}>위 목록에서 풀 문제를 선택하세요.</p>
            )}
          </div>
        </>
      )}
    </div>
  );
}

/* ---------------- AI 해설 ---------------- */
export function AiExplanationPanel({ note, items, onPick }) {
  const [detail, setDetail] = useState(null);
  const [retry, setRetry] = useState([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState('');

  useEffect(() => {
    if (!note) { setDetail(null); setRetry([]); return; }
    let alive = true;
    (async () => {
      setLoading(true); setErr('');
      try {
        const [d, r] = await Promise.all([
          reviewNoteService.getReviewNote(noteId(note)).catch(() => null),
          reviewNoteService.retry(noteId(note)).catch(() => ({ questions: [] })),
        ]);
        if (!alive) return;
        setDetail(d);
        setRetry(Array.isArray(r?.questions) ? r.questions : []);
      } catch {
        if (alive) setErr('AI 해설을 불러오지 못했습니다.');
      } finally { if (alive) setLoading(false); }
    })();
    return () => { alive = false; };
  }, [note]);

  if (!note) return <NotePicker items={items} onPick={onPick} label="AI 해설을 볼 오답노트를 선택하세요." />;
  const summary = detail?.aiExplanationSummary || detail?.overallFeedback;
  return (
    <div>
      <h2 style={panelTitle}>AI 해설 · {note.title}</h2>
      {loading ? <p style={muted}>AI 해설을 불러오는 중입니다.</p>
        : err ? <p style={{ ...muted, color: '#B91C1C' }}>{err}</p>
        : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
            {summary && (
              <div style={aiBox}>
                <div style={aiBoxTitle}>전체 AI 해설 요약</div>
                <p style={aiBoxText}>{clean(summary)}</p>
              </div>
            )}
            {retry.length === 0 ? (
              <p style={muted}>표시할 문제별 해설이 없습니다. PDF 오답노트에서 상세 해설을 확인할 수 있습니다.</p>
            ) : retry.map((q, i) => (
              <div key={i} style={{ border: '1px solid #E5E7EB', borderRadius: '10px', padding: '14px' }}>
                <p style={{ margin: '0 0 8px 0', fontWeight: 700, color: '#111827', whiteSpace: 'pre-wrap' }}>
                  {i + 1}. {clean(q.question)}
                </p>
                <p style={{ margin: '0 0 4px 0', fontSize: '13px', color: '#15803D', fontWeight: 600 }}>
                  정답: {clean(q.correctAnswer ?? q.correct_answer)}
                </p>
                {q.explanation && (
                  <p style={{ margin: 0, fontSize: '13px', color: '#374151', whiteSpace: 'pre-wrap', lineHeight: 1.7 }}>
                    {clean(q.explanation)}
                  </p>
                )}
              </div>
            ))}
          </div>
        )}
    </div>
  );
}

/* ---------------- styles (공유) ---------------- */
export const btn = {
  display: 'inline-flex', alignItems: 'center', gap: '6px',
  padding: '7px 12px', borderRadius: '8px', fontSize: '13px', fontWeight: 600,
  cursor: 'pointer', border: '1px solid #D1D5DB', background: '#fff', color: '#374151',
};
export const btnPrimary = { ...btn, border: 'none', background: '#15803D', color: '#fff' };
const panelTitle = { margin: '0 0 16px 0', fontSize: '17px', fontWeight: 800, color: '#111827' };
const listTitle = { margin: '0 0 12px 0', fontSize: '15px', fontWeight: 800, color: '#111827' };
const muted = { color: '#6B7280', fontSize: '14px', margin: 0 };
const numBadge = { fontSize: '12px', fontWeight: 800, color: '#15803D', background: '#ECFDF5', border: '1px solid #BBF7D0', borderRadius: '8px', padding: '2px 8px' };
const diffBadge = { fontSize: '12px', fontWeight: 700, color: '#374151', background: '#F3F4F6', border: '1px solid #E5E7EB', borderRadius: '8px', padding: '2px 8px' };
const statusBadge = { fontSize: '12px', fontWeight: 700, borderRadius: '8px', padding: '2px 8px', border: '1px solid transparent' };
const statusIdle = { color: '#6B7280', background: '#F3F4F6', borderColor: '#E5E7EB' };
const statusOk = { color: '#15803D', background: '#ECFDF5', borderColor: '#BBF7D0' };
const statusNo = { color: '#B91C1C', background: '#FEF2F2', borderColor: '#FECACA' };
const miniLabel = { display: 'block', fontSize: '12px', fontWeight: 600, color: '#374151', marginBottom: '6px' };
const selectStyle = { padding: '8px 10px', borderRadius: '8px', border: '1px solid #D1D5DB', fontSize: '13px', color: '#374151' };
const aiBox = { background: '#ECFDF5', border: '1px solid #BBF7D0', borderRadius: '10px', padding: '14px' };
const aiBoxTitle = { fontSize: '13px', fontWeight: 800, color: '#15803D', marginBottom: '6px' };
const aiBoxText = { margin: 0, fontSize: '13.5px', color: '#374151', whiteSpace: 'pre-wrap', lineHeight: 1.8 };
