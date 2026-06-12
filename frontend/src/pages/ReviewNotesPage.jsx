import React, { useEffect, useState } from 'react';
import { FileText, Download, RotateCcw, StickyNote, ListChecks } from 'lucide-react';
import { reviewNoteService } from '../services/api';

/**
 * 오답노트 (복습 전용) 탭.
 *  - 자료보관함 내부 탭이 아니라 상단 네비게이션의 독립 페이지다.
 *  - 백엔드(/api/review-notes)가 아직 없을 수 있으므로, 실패 시 404/500을 터뜨리지 않고
 *    빈 상태 + "API 미준비" 안내를 보여준다(reviewNoteService 가 안전하게 흡수).
 *  - MVP 기능 4개: 목록 보기 / PDF 보기·다운로드 / 다시 풀기 / 메모.
 */

// 상단 기능 안내 카드 4종
const FEATURE_CARDS = [
  { icon: ListChecks, title: '오답노트 목록', desc: '틀린 문제를 자료별로 모아 다시 확인합니다.' },
  { icon: FileText, title: 'PDF 보기/다운로드', desc: '오답노트 PDF를 열람하고 내 컴퓨터에 저장합니다.' },
  { icon: RotateCcw, title: '다시 풀기', desc: '틀렸던 문제만 다시 풀며 복습합니다.' },
  { icon: StickyNote, title: '메모', desc: '오답노트별로 나만의 메모를 남기고 관리합니다.' },
];

const DIFFICULTY_LABEL = { easy: '쉬움', medium: '보통', hard: '어려움' };

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

export default function ReviewNotesPage() {
  const [items, setItems] = useState([]);
  const [apiReady, setApiReady] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // 메모 편집 상태: { [id]: text }
  const [memoDraft, setMemoDraft] = useState({});
  const [memoSaving, setMemoSaving] = useState('');

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const { items: list, apiReady: ready } = await reviewNoteService.getReviewNotes();
      setItems(list);
      setApiReady(ready);
    } catch (e) {
      // 예기치 못한 오류도 화면을 깨지 않고 빈 상태로 처리
      console.error('오답노트 목록 조회 실패:', e);
      setItems([]);
      setApiReady(false);
      setError('오답노트를 불러오는 중 문제가 발생했습니다.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const handleViewPdf = async (note) => {
    try {
      const data = await reviewNoteService.getDownloadUrl(note.id);
      const url = data?.url || data?.downloadUrl || note.pdfUrl;
      if (url) window.open(url, '_blank', 'noopener');
      else alert('이 오답노트에는 아직 PDF가 없습니다.');
    } catch (e) {
      console.error('PDF 보기 실패:', e);
      alert('PDF를 여는 중 문제가 발생했습니다.');
    }
  };

  const handleDownloadPdf = async (note) => {
    try {
      const data = await reviewNoteService.getDownloadUrl(note.id);
      const url = data?.url || data?.downloadUrl || note.pdfUrl;
      if (!url) { alert('이 오답노트에는 아직 PDF가 없습니다.'); return; }
      const a = document.createElement('a');
      a.href = url;
      a.download = `${note.title || 'review-note'}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
    } catch (e) {
      console.error('PDF 다운로드 실패:', e);
      alert('PDF 저장 중 문제가 발생했습니다.');
    }
  };

  const handleRetry = async (note) => {
    try {
      await reviewNoteService.retry(note.id);
      alert('다시 풀기를 시작합니다. (틀린 문제를 다시 표시합니다)');
    } catch (e) {
      console.error('다시 풀기 실패:', e);
      alert('다시 풀기를 시작할 수 없습니다. 잠시 후 다시 시도해 주세요.');
    }
  };

  const handleMemoSave = async (note) => {
    const memo = memoDraft[note.id] ?? note.memo ?? '';
    setMemoSaving(note.id);
    try {
      await reviewNoteService.updateMemo(note.id, memo);
      setItems((prev) => prev.map((n) => (n.id === note.id ? { ...n, memo } : n)));
      alert('메모가 저장되었습니다.');
    } catch (e) {
      console.error('메모 저장 실패:', e);
      alert('메모 저장에 실패했습니다.');
    } finally {
      setMemoSaving('');
    }
  };

  const btn = {
    display: 'inline-flex', alignItems: 'center', gap: '6px',
    padding: '7px 12px', borderRadius: '8px', fontSize: '13px', fontWeight: 600,
    cursor: 'pointer', border: '1px solid #D1D5DB', background: '#fff', color: '#374151',
  };
  const btnPrimary = { ...btn, border: 'none', background: '#15803D', color: '#fff' };

  return (
    <div className="container-main" style={{ maxWidth: '1100px', margin: '0 auto', padding: '24px' }}>
      {/* 헤더 */}
      <div style={{ marginBottom: '20px' }}>
        <h1 style={{ fontSize: '24px', fontWeight: 900, color: '#15803D', margin: '0 0 6px 0' }}>오답노트</h1>
        <p style={{ color: '#6B7280', margin: 0, fontSize: '14px' }}>
          틀린 문제를 다시 확인하고, AI 해설과 PDF 오답노트를 관리할 수 있습니다.
        </p>
      </div>

      {/* 기능 안내 카드 4종 */}
      <div
        style={{
          display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
          gap: '14px', marginBottom: '24px',
        }}
      >
        {FEATURE_CARDS.map(({ icon: Icon, title, desc }) => (
          <div
            key={title}
            style={{
              background: '#fff', border: '1px solid #E5E7EB', borderRadius: '12px',
              padding: '16px',
            }}
          >
            <div style={{
              display: 'inline-flex', padding: '8px', borderRadius: '10px',
              background: '#ECFDF5', color: '#15803D', marginBottom: '10px',
            }}>
              <Icon size={20} />
            </div>
            <h3 style={{ margin: '0 0 4px 0', fontSize: '15px', fontWeight: 700, color: '#111827' }}>{title}</h3>
            <p style={{ margin: 0, fontSize: '13px', color: '#6B7280', lineHeight: 1.5 }}>{desc}</p>
          </div>
        ))}
      </div>

      {/* API 미준비 안내 배너 */}
      {!loading && !apiReady && (
        <div style={{
          background: '#FFFBEB', border: '1px solid #FDE68A', color: '#92400E',
          borderRadius: '10px', padding: '14px 16px', marginBottom: '20px', fontSize: '13.5px',
        }}>
          오답노트 API가 아직 준비되지 않았습니다. 퀴즈 풀이 후 생성된 오답노트가 이곳에 표시됩니다.
        </div>
      )}

      {/* 목록 영역 */}
      <div style={{ background: '#fff', border: '1px solid #E5E7EB', borderRadius: '12px', padding: '20px' }}>
        <h2 style={{ margin: '0 0 16px 0', fontSize: '17px', fontWeight: 800, color: '#111827' }}>
          오답노트 목록
        </h2>

        {loading ? (
          <p style={{ color: '#6B7280', fontSize: '14px', margin: 0 }}>불러오는 중…</p>
        ) : items.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '40px 16px', color: '#6B7280' }}>
            <StickyNote size={40} style={{ color: '#9CA3AF', marginBottom: '12px' }} />
            <p style={{ margin: 0, fontSize: '14px' }}>
              아직 생성된 오답노트가 없습니다. 퀴즈를 푼 뒤 틀린 문제가 있으면 오답노트를 만들 수 있습니다.
            </p>
            {error && <p style={{ margin: '8px 0 0 0', fontSize: '12.5px', color: '#9CA3AF' }}>{error}</p>}
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
            {items.map((note) => (
              <div
                key={note.id}
                style={{
                  border: '1px solid #E5E7EB', borderRadius: '10px', padding: '16px',
                }}
              >
                {/* 메타 정보 */}
                <div style={{ display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px' }}>
                  <div>
                    <h3 style={{ margin: '0 0 4px 0', fontSize: '15px', fontWeight: 700, color: '#111827' }}>
                      {note.title || '제목 없는 오답노트'}
                    </h3>
                    <p style={{ margin: 0, fontSize: '13px', color: '#6B7280' }}>
                      원본 자료: {note.sourceName || note.materialName || '-'}
                    </p>
                  </div>
                  <div style={{ textAlign: 'right', fontSize: '12.5px', color: '#6B7280' }}>
                    <div>오답 {note.wrongCount ?? note.wrong_count ?? 0}개</div>
                    <div>난이도: {DIFFICULTY_LABEL[note.difficulty] || note.difficulty || '-'}</div>
                    <div>생성일: {formatDate(note.createdAt || note.created_at)}</div>
                  </div>
                </div>

                {/* 액션 버튼 */}
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginTop: '14px' }}>
                  <button style={btn} onClick={() => handleViewPdf(note)}>
                    <FileText size={15} /> PDF 보기
                  </button>
                  <button style={btn} onClick={() => handleDownloadPdf(note)}>
                    <Download size={15} /> 컴퓨터에 저장
                  </button>
                  <button style={btnPrimary} onClick={() => handleRetry(note)}>
                    <RotateCcw size={15} /> 다시 풀기
                  </button>
                </div>

                {/* 메모 */}
                <div style={{ marginTop: '14px' }}>
                  <label style={{ display: 'block', fontSize: '12.5px', fontWeight: 600, color: '#374151', marginBottom: '6px' }}>
                    메모
                  </label>
                  <textarea
                    value={memoDraft[note.id] ?? note.memo ?? ''}
                    onChange={(e) => setMemoDraft((p) => ({ ...p, [note.id]: e.target.value }))}
                    placeholder="이 오답노트에 대한 메모를 입력하세요."
                    rows={2}
                    style={{
                      width: '100%', boxSizing: 'border-box', resize: 'vertical',
                      border: '1px solid #D1D5DB', borderRadius: '8px', padding: '8px 10px',
                      fontSize: '13px', color: '#374151',
                    }}
                  />
                  <div style={{ marginTop: '8px', textAlign: 'right' }}>
                    <button
                      style={{ ...btnPrimary, opacity: memoSaving === note.id ? 0.6 : 1 }}
                      disabled={memoSaving === note.id}
                      onClick={() => handleMemoSave(note)}
                    >
                      {memoSaving === note.id ? '저장 중…' : '메모 저장'}
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
