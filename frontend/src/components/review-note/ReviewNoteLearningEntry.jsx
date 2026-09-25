import React from 'react';
import { RotateCcw, Shuffle, Sparkles, ArrowRight } from 'lucide-react';

/**
 * 학습PDF 상세(퀴즈 탭)의 "오답노트 학습" 진입 UI — 설명 전용.
 *  - 여기서는 다시 풀기/유사문제/AI 해설을 직접 실행하지 않는다(요구사항).
 *  - 카드/버튼 클릭 시 자료보관함 REVIEW_NOTE 상세(/archive/reviewNote/{id}?tab=...)로 이동만 한다.
 *  - archiveMaterialId 가 있을 때만 렌더(없으면 진입할 오답노트 자료가 없으므로 호출부에서 숨김).
 */

const CARDS = [
  { key: 'retry', tab: 'retry', icon: RotateCcw, title: '다시 풀기', desc: '틀린 문제를 다시 풀며 복습합니다.' },
  { key: 'similar', tab: 'similar', icon: Shuffle, title: '유사문제 풀기', desc: '틀린 문제를 변형한 문제로 다시 연습합니다.' },
  { key: 'explanation', tab: 'explanation', icon: Sparkles, title: 'AI 해설', desc: '정답 근거, 오답 원인, 다시 볼 개념을 확인합니다.' },
];

export default function ReviewNoteLearningEntry({ archiveMaterialId, navigate }) {
  if (!archiveMaterialId) return null;
  const go = (tab) => navigate(`/archive/reviewNote/${archiveMaterialId}?tab=${tab}`);

  return (
    <div className="glass-panel" style={{ padding: '20px 24px', marginBottom: '24px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px', marginBottom: '14px' }}>
        <div>
          <h3 style={{ margin: '0 0 4px', fontSize: '17px', color: 'var(--color-text-main)' }}>오답노트 학습</h3>
          <p style={{ margin: 0, fontSize: '13px', color: 'var(--color-text-muted)' }}>
            다시 풀기 · 유사문제 · AI 해설은 자료보관함 오답노트 상세에서 실행됩니다. 카드를 선택해 이동하세요.
          </p>
        </div>
        <button
          className="btn-primary"
          style={{ display: 'inline-flex', alignItems: 'center', gap: '6px', padding: '10px 18px', borderRadius: '30px', fontWeight: 'bold', whiteSpace: 'nowrap', width: 'auto' }}
          onClick={() => go('retry')}
        >
          오답노트 학습 시작 <ArrowRight size={16} />
        </button>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '12px' }}>
        {CARDS.map(({ key, tab, icon: Icon, title, desc }) => (
          <button
            key={key}
            onClick={() => go(tab)}
            style={{ textAlign: 'left', cursor: 'pointer', background: '#fff', border: '1px solid #E5E7EB', borderRadius: '12px', padding: '16px' }}
          >
            <div style={{ display: 'inline-flex', padding: '8px', borderRadius: '10px', background: '#ECFDF5', marginBottom: '10px' }}>
              {/* 전역 .lucide{color:muted} 가 인라인 color 를 덮으므로 아이콘에 직접 색 지정 */}
              <Icon size={24} color="#15803D" style={{ color: '#15803D' }} />
            </div>
            <h4 style={{ margin: '0 0 4px', fontSize: '15px', fontWeight: 700, color: '#111827' }}>{title}</h4>
            <p style={{ margin: 0, fontSize: '13px', color: '#6B7280', lineHeight: 1.5 }}>{desc}</p>
          </button>
        ))}
      </div>
    </div>
  );
}
