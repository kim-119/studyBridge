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
export function VariantPanel({ note, items, onPick }) {
  const [difficulty, setDifficulty] = useState('normal');
  const [wrongQuestionId, setWrongQuestionId] = useState(1);
  const [questions, setQuestions] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState('');

  const generate = async () => {
    setLoading(true); setErr(''); setQuestions(null);
    try {
      const data = await reviewNoteService.variantQuestion(noteId(note), {
        wrongQuestionId: Number(wrongQuestionId) || 1,
        difficulty,
        count: 1,
      });
      const qs = Array.isArray(data?.questions) ? data.questions : [];
      if (data && data.success === false) {
        // 서버가 명시적으로 실패를 알려준 경우 — 원인 메시지를 그대로 노출
        setErr(data.message || data.error || '유사문제 생성에 실패했습니다. 잠시 후 다시 시도해주세요.');
      } else if (qs.length === 0) {
        // 성공이지만 변형할 원본 오답이 없는 경우 — 빈 성공으로 처리하지 않고 원인 안내
        setErr('이 오답노트에는 변형할 원본 오답 문제가 없습니다. 먼저 퀴즈를 풀고 틀린 문제로 오답노트를 만들어 주세요.');
      } else {
        setQuestions(qs);
      }
    } catch (e) {
      const data = e?.response?.data;
      const serverMsg = data?.message || data?.error || (typeof data === 'string' ? data : '');
      setErr(serverMsg
        ? `유사문제를 생성하지 못했습니다: ${serverMsg}`
        : '유사문제를 생성하지 못했습니다. 잠시 후 다시 시도해주세요.');
    } finally { setLoading(false); }
  };

  if (!note) return <NotePicker items={items} onPick={onPick} label="유사문제를 풀 오답노트를 선택하세요." />;
  const wrongCount = Math.max(1, note.wrongCount ?? 1);
  return (
    <div>
      <h2 style={panelTitle}>유사문제 풀기 · {note.title}</h2>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '12px', alignItems: 'center', marginBottom: '16px' }}>
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
        <button style={{ ...btnPrimary, alignSelf: 'flex-end', opacity: loading ? 0.6 : 1 }} disabled={loading} onClick={generate}>
          {loading ? '생성 중…' : '유사문제 생성'}
        </button>
      </div>
      {err ? <p style={{ ...muted, color: '#B91C1C' }}>{err}</p>
        : questions ? <QuestionRunner questions={questions} />
        : <p style={muted}>난이도를 선택하고 유사문제를 생성해 보세요.</p>}
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
const muted = { color: '#6B7280', fontSize: '14px', margin: 0 };
const miniLabel = { display: 'block', fontSize: '12px', fontWeight: 600, color: '#374151', marginBottom: '6px' };
const selectStyle = { padding: '8px 10px', borderRadius: '8px', border: '1px solid #D1D5DB', fontSize: '13px', color: '#374151' };
const aiBox = { background: '#ECFDF5', border: '1px solid #BBF7D0', borderRadius: '10px', padding: '14px' };
const aiBoxTitle = { fontSize: '13px', fontWeight: 800, color: '#15803D', marginBottom: '6px' };
const aiBoxText = { margin: 0, fontSize: '13.5px', color: '#374151', whiteSpace: 'pre-wrap', lineHeight: 1.8 };
