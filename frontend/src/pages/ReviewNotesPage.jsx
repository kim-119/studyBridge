import React, { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { ListChecks, RotateCcw, Shuffle, Sparkles, FileText, Download, StickyNote, Lightbulb, CalendarPlus } from 'lucide-react';
import { reviewNoteService, learningLoopService } from '../services/api';
import {
  RetryPanel, VariantPanel, AiExplanationPanel,
  noteId, formatDate, DIFFICULTY_LABEL, btn, btnPrimary,
} from '../components/review-note/ReviewNotePanels';

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
                background: active ? '#15803D' : '#ECFDF5', marginBottom: '10px',
              }}>
                {/* 전역 .lucide{color:muted} 가 인라인 color 를 덮으므로, 아이콘에 직접 style color 를 줘 대비 확보 */}
                <Icon size={24} color={active ? '#FFFFFF' : '#15803D'} style={{ color: active ? '#FFFFFF' : '#15803D' }} />
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
  const [showMemo, setShowMemo] = useState(false);
  const [memo, setMemo] = useState(note.memo ?? '');
  const [memoSaving, setMemoSaving] = useState(false);

  // 복습 필요 분석(AI) — 결과 캐싱(재클릭 토글), 로딩/에러 분리, 중복 호출 방지
  const [rnOpen, setRnOpen] = useState(false);
  const [rnText, setRnText] = useState('');
  const [rnLoading, setRnLoading] = useState(false);
  const [rnError, setRnError] = useState('');
  const handleReviewNeeded = async () => {
    if (rnText) { setRnOpen((v) => !v); return; } // 이미 생성됨 → 표시 토글(재호출 안 함)
    if (rnLoading) return;                          // 중복 클릭 방지
    setRnOpen(true);
    setRnLoading(true);
    setRnError('');
    try {
      const data = await reviewNoteService.reviewNeeded(noteId(note));
      const text = data?.reviewNeededText || '';
      if (text) setRnText(text);
      else setRnError('복습 필요 분석을 생성하지 못했습니다. 잠시 후 다시 시도해 주세요.');
    } catch {
      setRnError('복습 필요 분석을 생성하지 못했습니다. 잠시 후 다시 시도해 주세요.');
    } finally {
      setRnLoading(false);
    }
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

  // 학습 왕복 루프: 복습 추천일 계산 → 플래너(주간일정)에 등록
  const [schedLoading, setSchedLoading] = useState(false);
  const [schedDone, setSchedDone] = useState('');
  const handleRegisterReview = async () => {
    if (schedLoading) return;
    setSchedLoading(true);
    setSchedDone('');
    try {
      const wrongCount = (note.wrongCount ?? 0) + (note.unansweredCount ?? 0);
      const rec = await learningLoopService.recommendReview({
        wrongNoteId: noteId(note),
        materialId: note.sourceMaterialId,
        difficulty: note.difficulty,
        wrongCount,
      });
      const res = await learningLoopService.registerReviewSchedule({
        wrongNoteId: noteId(note),
        materialId: note.sourceMaterialId,
        title: `[복습] ${note.sourceName || note.title || '오답'} 오답 복습`,
        scheduledDate: rec?.recommendedReviewDate,
        reason: rec?.reviewReason,
      });
      setSchedDone(`${res?.scheduledDate || rec?.recommendedReviewDate} 주간 일정에 복습이 등록되었습니다.`);
    } catch {
      setSchedDone('복습 일정 등록에 실패했습니다. 잠시 후 다시 시도해 주세요.');
    } finally {
      setSchedLoading(false);
    }
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

      {/* 메인 액션: 다시 풀기 / 유사문제 / AI 해설 / 복습 필요 */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginTop: '14px' }}>
        <button style={btnPrimary} onClick={() => onOpen(note, 'retry')}><RotateCcw size={15} /> 다시 풀기</button>
        <button style={btnPrimary} onClick={() => onOpen(note, 'variant')}><Shuffle size={15} /> 유사문제 풀기</button>
        <button style={btnPrimary} onClick={() => onOpen(note, 'ai')}><Sparkles size={15} /> AI 해설</button>
        <button style={{ ...btnPrimary, opacity: rnLoading ? 0.6 : 1 }} disabled={rnLoading} onClick={handleReviewNeeded}>
          <Lightbulb size={15} /> {rnLoading ? '분석 중…' : '복습 필요'}
        </button>
        <button style={{ ...btnPrimary, opacity: schedLoading ? 0.6 : 1 }} disabled={schedLoading} onClick={handleRegisterReview}>
          <CalendarPlus size={15} /> {schedLoading ? '등록 중…' : '복습 일정 등록'}
        </button>
      </div>

      {/* 복습 일정 등록 결과 안내 */}
      {schedDone && (
        <div style={{ marginTop: '10px', fontSize: '13px', color: '#15803D', fontWeight: 600 }}>
          {schedDone}
        </div>
      )}

      {/* 복습 필요 분석 결과 (로딩/에러/결과 분리) */}
      {rnOpen && (
        <div style={{ marginTop: '12px', border: '1px solid #BBF7D0', background: '#F0FDF4', borderRadius: '10px', padding: '14px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px', color: '#15803D', fontWeight: 700, fontSize: '14px' }}>
            <Lightbulb size={16} /> 복습 필요 분석
          </div>
          {rnLoading && <p style={{ margin: 0, fontSize: '13px', color: '#6B7280' }}>AI가 복습이 필요한 개념을 분석 중입니다…</p>}
          {!rnLoading && rnError && <p style={{ margin: 0, fontSize: '13px', color: '#B91C1C' }}>{rnError}</p>}
          {!rnLoading && !rnError && rnText && (
            <p style={{ margin: 0, fontSize: '13.5px', lineHeight: 1.65, color: '#374151', whiteSpace: 'pre-wrap' }}>{rnText}</p>
          )}
        </div>
      )}

      {/* 보조 버튼: PDF 보기 / 컴퓨터에 저장 / 메모 */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginTop: '8px' }}>
        <button style={btn} onClick={viewPdf}><FileText size={15} /> PDF 보기</button>
        <button style={btn} onClick={savePdf}><Download size={15} /> 컴퓨터에 저장</button>
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
