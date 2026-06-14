import React, { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { ArrowLeft, Trash2, RotateCcw, Shuffle, Sparkles, Edit3 } from 'lucide-react';
import { reviewNoteService, materialService } from '../../services/api';
import { RetryPanel, VariantPanel, AiExplanationPanel } from './ReviewNotePanels';

/**
 * 자료보관함 REVIEW_NOTE(오답노트) 상세 — 실제 복습 기능 실행 화면.
 *  - 상단바: 기존 학습PDF 상세와 동일한 스타일(목록/오답노트 badge/제목 + 뷰어너비 + pill 탭 + 삭제).
 *  - 좌측: A4 오답노트 PDF 뷰어, 우측: 선택 탭 패널(다시 풀기/유사문제/AI 해설/메모).
 *  - reviewNoteId는 archiveMaterialId 역참조로 해결한다(materialId → ReviewNote).
 *  - ?tab=retry|similar|explanation|memo 딥링크 지원. PDF 상세의 안내 카드가 여기로 진입시킨다.
 */

const TABS = [
  { key: 'retry', label: '다시 풀기', icon: RotateCcw },
  { key: 'similar', label: '유사문제 풀기', icon: Shuffle },
  { key: 'explanation', label: 'AI 해설', icon: Sparkles },
  { key: 'memo', label: '메모', icon: Edit3 },
];
const VALID_TABS = TABS.map((t) => t.key);

export default function ReviewNoteArchiveDetail({ material, leftWidth, setLeftWidth, onDelete, onBack }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const queryTab = searchParams.get('tab');
  const [tab, setTab] = useState(VALID_TABS.includes(queryTab) ? queryTab : 'retry');

  const [note, setNote] = useState(null);
  const [noteLoading, setNoteLoading] = useState(true);
  const [noteError, setNoteError] = useState('');

  const [memoText, setMemoText] = useState('');
  const [memoSaving, setMemoSaving] = useState(false);

  const fileUrl = material?.s3PresignedUrl || '';
  const isDocx = (material?.originalFileName || '').toLowerCase().endsWith('.docx');

  // reviewNoteId 해결: 전체 오답노트 목록에서 archiveMaterialId === 현재 materialId 인 노트를 찾는다.
  useEffect(() => {
    let alive = true;
    (async () => {
      setNoteLoading(true); setNoteError('');
      try {
        const { items } = await reviewNoteService.getReviewNotes();
        const found = (items || []).find((n) => String(n.archiveMaterialId) === String(material.materialId));
        if (!alive) return;
        setNote(found || null);
        if (!found) setNoteError('이 오답노트의 학습 데이터를 찾지 못했습니다. PDF는 좌측에서 확인할 수 있습니다.');
      } catch (e) {
        if (alive) setNoteError('오답노트 학습 데이터를 불러오지 못했습니다. 잠시 후 다시 시도해주세요.');
      } finally {
        if (alive) setNoteLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [material.materialId]);

  // 메모는 REVIEW_NOTE material 기준으로 저장(학습 PDF 메모와 별개 materialId라 충돌 없음).
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const m = await materialService.getMemo(material.materialId);
        if (alive) setMemoText(m?.content || '');
      } catch { /* 메모 없음은 정상 */ }
    })();
    return () => { alive = false; };
  }, [material.materialId]);

  const selectTab = (key) => {
    setTab(key);
    const next = new URLSearchParams(searchParams);
    next.set('tab', key);
    setSearchParams(next, { replace: true });
  };

  const saveMemo = async () => {
    setMemoSaving(true);
    try {
      await materialService.saveMemo(material.materialId, memoText || '');
      alert('메모가 저장되었습니다.');
    } catch (e) {
      console.error('메모 저장 실패:', e);
      alert('메모 저장 중 오류가 발생했습니다.');
    } finally {
      setMemoSaving(false);
    }
  };

  const renderRightPanel = () => {
    if (tab === 'memo') {
      return (
        <div className="glass-panel" style={{ padding: '24px' }}>
          <label style={{ display: 'block', fontWeight: 700, marginBottom: '10px', fontSize: '17px', color: '#111827' }}>메모</label>
          <textarea
            value={memoText}
            onChange={(e) => setMemoText(e.target.value)}
            placeholder="이 오답노트에 대한 메모를 작성하세요."
            style={{ width: '100%', minHeight: '220px', padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)', resize: 'vertical', fontFamily: 'inherit', lineHeight: 1.6, boxSizing: 'border-box' }}
          />
          <div style={{ marginTop: '10px', textAlign: 'right' }}>
            <button className="btn-primary" style={{ width: 'auto', padding: '9px 22px', borderRadius: '10px', opacity: memoSaving ? 0.6 : 1 }} disabled={memoSaving} onClick={saveMemo}>
              {memoSaving ? '저장 중…' : '메모 저장'}
            </button>
          </div>
        </div>
      );
    }
    if (noteLoading) {
      return <div className="glass-panel" style={{ padding: '24px' }}><p style={{ color: 'var(--color-text-muted)', margin: 0 }}>오답노트 학습 데이터를 불러오는 중입니다.</p></div>;
    }
    if (!note) {
      return <div className="glass-panel" style={{ padding: '24px' }}><p style={{ color: '#B91C1C', margin: 0 }}>{noteError || '오답노트 학습 데이터를 찾지 못했습니다.'}</p></div>;
    }
    return (
      <div className="glass-panel" style={{ padding: '24px' }}>
        {tab === 'retry' && <RetryPanel note={note} items={[]} onPick={() => {}} />}
        {tab === 'similar' && <VariantPanel note={note} items={[]} onPick={() => {}} />}
        {tab === 'explanation' && <AiExplanationPanel note={note} items={[]} onPick={() => {}} />}
      </div>
    );
  };

  return (
    <div className="archive-detail-container animate-fade-in">
      {/* 상단바 — 학습PDF 상세와 동일 스타일 */}
      <div className="archive-action-bar" style={{ padding: '16px 24px', borderBottom: '1px solid var(--color-border)', backgroundColor: 'white', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px', flex: 1, minWidth: 0 }}>
          <button className="btn-outline" style={{ width: 'auto', padding: '8px 16px', border: 'none', flexShrink: 0 }} onClick={onBack}>
            <ArrowLeft size={18} /> 목록
          </button>
          <span style={{ fontSize: '12px', fontWeight: 700, color: '#991B1B', background: '#FEE2E2', padding: '3px 10px', borderRadius: '12px', flexShrink: 0 }}>오답노트</span>
          <span style={{ fontWeight: '600', fontSize: '18px', color: 'var(--color-text-main)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }} title={material.title || material.originalFileName}>
            {material.title || material.originalFileName}
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexShrink: 0 }}>
          <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
            <span style={{ fontSize: '12px', color: 'var(--color-text-muted)', marginRight: '4px' }}>뷰어 너비:</span>
            {[30, 50, 70].map((pct) => (
              <button key={pct} onClick={() => setLeftWidth(pct)} style={{ padding: '4px 8px', fontSize: '11px', borderRadius: '4px', border: '1px solid var(--color-border)', backgroundColor: leftWidth === pct ? 'var(--color-primary)' : 'white', color: leftWidth === pct ? 'white' : 'var(--color-text-main)', cursor: 'pointer', fontWeight: leftWidth === pct ? 'bold' : 'normal' }}>{pct}%</button>
            ))}
          </div>
          {/* 기능 pill 탭 — 학습PDF 상세의 archive-action-btn 스타일 재사용 */}
          <div style={{ display: 'flex', gap: '8px' }}>
            {TABS.map(({ key, label, icon: Icon }) => (
              <button key={key} className={`archive-action-btn ${tab === key ? 'active' : ''}`} onClick={() => selectTab(key)}>
                <Icon size={16} /> {label}
              </button>
            ))}
          </div>
          <button className="btn-outline" style={{ width: 'auto', padding: '8px 16px', border: 'none', color: '#EF4444' }} onClick={onDelete}>
            <Trash2 size={18} /> 삭제
          </button>
        </div>
      </div>

      {/* 좌: A4 오답노트 뷰어 / 우: 선택 탭 패널 */}
      <div className="archive-split-view">
        <div className="archive-left-panel" style={{ width: `${leftWidth}%`, flex: 'none', overflowY: 'auto' }}>
          {fileUrl && !isDocx ? (
            <iframe src={fileUrl} title="오답노트 PDF" style={{ width: '100%', height: '100%', border: 'none' }} />
          ) : (
            <div className="glass-panel" style={{ padding: '32px', height: '100%' }}>
              <h3 style={{ marginTop: 0 }}>오답노트 자료</h3>
              <p style={{ color: 'var(--color-text-muted)', fontSize: '14px' }}>
                {isDocx ? 'DOCX 문서는 미리보기를 제공하지 않습니다.' : '이 오답노트에는 미리볼 PDF가 없습니다. 우측 기능으로 복습할 수 있습니다.'}
              </p>
            </div>
          )}
        </div>
        <div style={{ width: '1px', backgroundColor: 'var(--color-border)', zIndex: 10 }} />
        <div className="archive-right-panel" style={{ width: `${100 - leftWidth}%`, flex: 'none', overflowY: 'auto', padding: '24px' }}>
          {renderRightPanel()}
        </div>
      </div>
    </div>
  );
}
