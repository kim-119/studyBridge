import React, { useEffect, useState } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { ListChecks, RotateCcw, Shuffle, Sparkles, FileText, Download, StickyNote, Archive, FolderCheck } from 'lucide-react';
import { reviewNoteService } from '../services/api';
import { sanitizeMarkdownText } from '../utils/markdown';

/**
 * 오답노트 (복습 전용) 상단 독립 페이지. path: /review-notes
 *  - 메인 기능 4개: 오답노트 목록 / 다시 풀기 / 유사문제 풀기 / AI 해설
 *  - 보조 기능: PDF 보기 · 컴퓨터에 저장 · 메모 (메인 카드가 아니라 목록 카드 내부 버튼)
 *  - 상태 분리: loading / error / empty / list (API 실패를 빈 목록으로 표시하지 않는다)
 *  - "API 준비 안 됨" 류 임시 문구는 사용자 화면에 절대 표시하지 않는다.
 */

// 메인 기능 4개 (탭). PDF/메모는 여기에 두지 않는다.
const TABS = [
  { key: 'list', icon: ListChecks, title: '오답노트 목록', desc: '틀린 문제를 자료별로 모아 다시 확인합니다.' },
  { key: 'retry', icon: RotateCcw, title: '다시 풀기', desc: '틀렸던 문제를 다시 풀며 복습합니다.' },
  { key: 'variant', icon: Shuffle, title: '유사문제 풀기', desc: '틀린 문제를 변형한 문제로 다시 연습합니다.' },
  { key: 'ai', icon: Sparkles, title: 'AI 해설', desc: '정답 근거, 오답 원인, 다시 볼 개념을 확인합니다.' },
];

const DIFFICULTY_LABEL = { easy: '쉬움', medium: '보통', normal: '보통', hard: '어려움' };
const VARIANT_LEVELS = [
  { label: '하', value: 'easy' },
  { label: '중', value: 'normal' },
  { label: '상', value: 'hard' },
];

const formatDate = (value) => {
  if (!value) return '-';
  try {
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return String(value);
    return d.toLocaleDateString('ko-KR', { year: 'numeric', month: '2-digit', day: '2-digit' });
  } catch {
    return String(value);
  }
};

const noteId = (n) => n?.id ?? n?.reviewNoteId;
const clean = (v) => sanitizeMarkdownText(v ?? '');

export default function ReviewNotesPage() {
  const [searchParams, setSearchParams] = useSearchParams();

  const [tab, setTab] = useState('list');
  // 목록 상태 4종 분리
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [items, setItems] = useState([]);

  const [selected, setSelected] = useState(null); // 선택된 오답노트(다시풀기/유사문제/AI해설 대상)

  const load = async () => {
    setLoading(true);
    setError('');
    const { ok, items: list, error: err } = await reviewNoteService.listReviewNotes();
    if (!ok) {
      setItems([]);
      setError(err || '오답노트 목록을 불러오지 못했습니다. 다시 시도해주세요.');
    } else {
      setItems(Array.isArray(list) ? list : []);
    }
    setLoading(false);
  };

  useEffect(() => { load(); }, []);

  // 딥링크: /review-notes?note=ID&tab=retry|variant|ai
  useEffect(() => {
    const noteParam = searchParams.get('note');
    const tabParam = searchParams.get('tab');
    if (noteParam && items.length > 0) {
      const found = items.find((n) => String(noteId(n)) === String(noteParam));
      if (found) {
        setSelected(found);
        if (tabParam && TABS.some((t) => t.key === tabParam)) setTab(tabParam);
      }
    }
  }, [searchParams, items]);

  const openTab = (note, nextTab) => {
    setSelected(note);
    setTab(nextTab);
    setSearchParams({ note: String(noteId(note)), tab: nextTab });
  };

  return (
    <div style={{ maxWidth: '1100px', margin: '0 auto', padding: '24px' }}>
      {/* 헤더 */}
      <div style={{ marginBottom: '20px' }}>
        <h1 style={{ fontSize: '24px', fontWeight: 900, color: '#15803D', margin: '0 0 6px 0' }}>오답노트</h1>
        <p style={{ color: '#6B7280', margin: 0, fontSize: '14px' }}>
          틀린 문제를 다시 확인하고, AI 해설과 유사문제로 복습할 수 있습니다.
        </p>
      </div>

      {/* 메인 기능 카드 4개 (탭) */}
      <div
        style={{
          display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
          gap: '14px', marginBottom: '24px',
        }}
      >
        {TABS.map(({ key, icon: Icon, title, desc }) => {
          const active = tab === key;
          return (
            <button
              key={key}
              onClick={() => setTab(key)}
              style={{
                textAlign: 'left', cursor: 'pointer',
                background: active ? '#ECFDF5' : '#fff',
                border: `1px solid ${active ? '#15803D' : '#E5E7EB'}`,
                borderRadius: '12px', padding: '16px',
              }}
            >
              <div style={{
                display: 'inline-flex', padding: '8px', borderRadius: '10px',
                background: active ? '#15803D' : '#ECFDF5', color: active ? '#fff' : '#15803D', marginBottom: '10px',
              }}>
                <Icon size={20} />
              </div>
              <h3 style={{ margin: '0 0 4px 0', fontSize: '15px', fontWeight: 700, color: '#111827' }}>{title}</h3>
              <p style={{ margin: 0, fontSize: '13px', color: '#6B7280', lineHeight: 1.5 }}>{desc}</p>
            </button>
          );
        })}
      </div>

      {/* 본문 영역 */}
      <div style={{ background: '#fff', border: '1px solid #E5E7EB', borderRadius: '12px', padding: '20px' }}>
        {tab === 'list' && (
          <ReviewNoteList
            loading={loading}
            error={error}
            items={items}
            onRetry={load}
            onOpen={openTab}
            onMemoSaved={load}
          />
        )}
        {tab === 'retry' && <RetryPanel note={selected} items={items} onPick={(n) => openTab(n, 'retry')} />}
        {tab === 'variant' && <VariantPanel note={selected} items={items} onPick={(n) => openTab(n, 'variant')} />}
        {tab === 'ai' && <AiExplanationPanel note={selected} items={items} onPick={(n) => openTab(n, 'ai')} />}
      </div>
    </div>
  );
}

/* ---------------- 오답노트 목록 (loading/error/empty/list 분리) ---------------- */
function ReviewNoteList({ loading, error, items, onRetry, onOpen, onMemoSaved }) {
  if (loading) {
    return <p style={{ color: '#6B7280', fontSize: '14px', margin: 0 }}>오답노트를 불러오는 중입니다.</p>;
  }
  if (error) {
    return (
      <div style={{ textAlign: 'center', padding: '32px 16px', color: '#B91C1C' }}>
        <p style={{ margin: '0 0 12px 0', fontSize: '14px' }}>오답노트 목록을 불러오지 못했습니다. 다시 시도해주세요.</p>
        <button onClick={onRetry} style={btnPrimary}>다시 시도</button>
      </div>
    );
  }
  if (!items || items.length === 0) {
    return (
      <div style={{ textAlign: 'center', padding: '40px 16px', color: '#6B7280' }}>
        <StickyNote size={40} style={{ color: '#9CA3AF', marginBottom: '12px' }} />
        <p style={{ margin: 0, fontSize: '14px' }}>
          아직 생성된 오답노트가 없습니다. 퀴즈를 풀고 틀린 문제가 있으면 오답노트를 만들 수 있습니다.
        </p>
      </div>
    );
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
      <h2 style={{ margin: 0, fontSize: '17px', fontWeight: 800, color: '#111827' }}>오답노트 목록</h2>
      {items.map((note) => (
        <ReviewNoteCard key={noteId(note)} note={note} onOpen={onOpen} onMemoSaved={onMemoSaved} />
      ))}
    </div>
  );
}

function ReviewNoteCard({ note, onOpen, onMemoSaved }) {
  const navigate = useNavigate();
  const [showMemo, setShowMemo] = useState(false);
  const [memo, setMemo] = useState(note.memo ?? '');
  const [memoSaving, setMemoSaving] = useState(false);
  // 오답노트는 생성 시 자료보관함(REVIEW_NOTE Material)에 자동 저장됨 → 중복 저장 방지, 보기로 전환
  const savedToArchive = note.archiveMaterialId != null;
  const openInArchive = () => {
    if (savedToArchive) navigate(`/archive/pdf/${note.archiveMaterialId}`);
  };

  const viewPdf = async () => {
    try {
      const data = await reviewNoteService.getDownloadUrl(noteId(note));
      const url = data?.url || data?.downloadUrl || note.pdfUrl;
      if (url) window.open(url, '_blank', 'noopener');
      else alert('이 오답노트에는 아직 PDF가 없습니다.');
    } catch { alert('PDF를 여는 중 문제가 발생했습니다.'); }
  };
  const savePdf = async () => {
    try {
      const data = await reviewNoteService.getDownloadUrl(noteId(note));
      const url = data?.url || data?.downloadUrl || note.pdfUrl;
      if (!url) { alert('이 오답노트에는 아직 PDF가 없습니다.'); return; }
      const a = document.createElement('a');
      a.href = url;
      a.download = `${note.title || 'review-note'}.pdf`;
      document.body.appendChild(a); a.click(); a.remove();
    } catch { alert('PDF 저장 중 문제가 발생했습니다.'); }
  };
  const saveMemo = async () => {
    setMemoSaving(true);
    try {
      await reviewNoteService.updateMemo(noteId(note), memo);
      alert('메모가 저장되었습니다.');
      onMemoSaved?.();
    } catch { alert('메모 저장에 실패했습니다.'); }
    finally { setMemoSaving(false); }
  };

  return (
    <div style={{ border: '1px solid #E5E7EB', borderRadius: '10px', padding: '16px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px' }}>
        <div>
          <h3 style={{ margin: '0 0 4px 0', fontSize: '15px', fontWeight: 700, color: '#111827' }}>
            {note.title || '제목 없는 오답노트'}
          </h3>
          <p style={{ margin: 0, fontSize: '13px', color: '#6B7280' }}>
            원본 자료: {note.sourceName || note.materialTitle || note.originalMaterialTitle || '-'}
          </p>
        </div>
        <div style={{ textAlign: 'right', fontSize: '12.5px', color: '#6B7280' }}>
          <div><span style={{ color: '#DC2626', fontWeight: 700 }}>오답 {note.wrongCount ?? 0}개</span>
            {(note.unansweredCount ?? 0) > 0 && <> · <span style={{ color: '#B45309', fontWeight: 700 }}>미응답 {note.unansweredCount}개</span></>}
          </div>
          <div>복습 필요: {note.reviewCount ?? ((note.wrongCount ?? 0) + (note.unansweredCount ?? 0))}개</div>
          <div>난이도: {DIFFICULTY_LABEL[note.difficulty] || note.difficulty || '-'}</div>
          <div>생성일: {formatDate(note.createdAt)}</div>
        </div>
      </div>

      {/* 메인 액션: 다시 풀기 / 유사문제 / AI 해설 */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginTop: '14px' }}>
        <button style={btnPrimary} onClick={() => onOpen(note, 'retry')}><RotateCcw size={15} /> 다시 풀기</button>
        <button style={btnPrimary} onClick={() => onOpen(note, 'variant')}><Shuffle size={15} /> 유사문제 풀기</button>
        <button style={btnPrimary} onClick={() => onOpen(note, 'ai')}><Sparkles size={15} /> AI 해설</button>
      </div>

      {/* 보조 버튼: PDF 보기 / 컴퓨터에 저장 / 자료보관함에 저장(됨) / 메모 */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginTop: '8px' }}>
        <button style={btn} onClick={viewPdf}><FileText size={15} /> PDF 보기</button>
        <button style={btn} onClick={savePdf}><Download size={15} /> 컴퓨터에 저장</button>
        {savedToArchive ? (
          <button
            style={{ ...btn, border: '1px solid #BBF7D0', background: '#ECFDF5', color: '#15803D', cursor: 'pointer' }}
            onClick={openInArchive}
            title="이미 자료보관함에 저장되어 있습니다. 클릭하면 자료보관함에서 엽니다."
          ><FolderCheck size={15} /> 자료보관함에 저장됨</button>
        ) : (
          <button style={{ ...btn, opacity: 0.6, cursor: 'default' }} disabled><Archive size={15} /> 자료보관함에 저장</button>
        )}
        <button style={btn} onClick={() => setShowMemo((v) => !v)}><StickyNote size={15} /> 메모</button>
      </div>

      {showMemo && (
        <div style={{ marginTop: '12px' }}>
          <textarea
            value={memo}
            onChange={(e) => setMemo(e.target.value)}
            placeholder="이 오답노트에 대한 메모를 입력하세요."
            rows={2}
            style={{
              width: '100%', boxSizing: 'border-box', resize: 'vertical',
              border: '1px solid #D1D5DB', borderRadius: '8px', padding: '8px 10px',
              fontSize: '13px', color: '#374151',
            }}
          />
          <div style={{ marginTop: '8px', textAlign: 'right' }}>
            <button style={{ ...btnPrimary, opacity: memoSaving ? 0.6 : 1 }} disabled={memoSaving} onClick={saveMemo}>
              {memoSaving ? '저장 중…' : '메모 저장'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/* ---------------- 다시 풀기 ---------------- */
function NotePicker({ items, onPick, label }) {
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

function QuestionRunner({ questions }) {
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

function RetryPanel({ note, items, onPick }) {
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
function VariantPanel({ note, items, onPick }) {
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
      setQuestions(Array.isArray(data?.questions) ? data.questions : []);
    } catch {
      setErr('유사문제를 생성하지 못했습니다. 잠시 후 다시 시도해주세요.');
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
function AiExplanationPanel({ note, items, onPick }) {
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

/* ---------------- styles ---------------- */
const btn = {
  display: 'inline-flex', alignItems: 'center', gap: '6px',
  padding: '7px 12px', borderRadius: '8px', fontSize: '13px', fontWeight: 600,
  cursor: 'pointer', border: '1px solid #D1D5DB', background: '#fff', color: '#374151',
};
const btnPrimary = { ...btn, border: 'none', background: '#15803D', color: '#fff' };
const panelTitle = { margin: '0 0 16px 0', fontSize: '17px', fontWeight: 800, color: '#111827' };
const muted = { color: '#6B7280', fontSize: '14px', margin: 0 };
const miniLabel = { display: 'block', fontSize: '12px', fontWeight: 600, color: '#374151', marginBottom: '6px' };
const selectStyle = { padding: '8px 10px', borderRadius: '8px', border: '1px solid #D1D5DB', fontSize: '13px', color: '#374151' };
const aiBox = { background: '#ECFDF5', border: '1px solid #BBF7D0', borderRadius: '10px', padding: '14px' };
const aiBoxTitle = { fontSize: '13px', fontWeight: 800, color: '#15803D', marginBottom: '6px' };
const aiBoxText = { margin: 0, fontSize: '13.5px', color: '#374151', whiteSpace: 'pre-wrap', lineHeight: 1.8 };
