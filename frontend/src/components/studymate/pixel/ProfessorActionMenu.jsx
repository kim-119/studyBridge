import React from 'react';

// 교수 클릭 시 뜨는 액션 메뉴. 교수 얼굴(하단)을 가리지 않게 stage 상단(칠판 쪽)에 배치한다.
//   · 버튼은 기존 질문 submit flow와 충돌하지 않게 "입력창 프리필/포커스" 또는 기존 안전 동작에만 연결.
//   · 자동 전송 없음. 위치는 side(left/center/right) 클래스(CSS)로 clamp.
const MENU_ITEMS = [
  { key: 'refine', label: '질문 정제', icon: '✏️' },
  { key: 'askOne', label: '이 교수에게 질문', icon: '🎯' },
  { key: 'askAll', label: '모두에게 질문', icon: '👥' },
  { key: 'compare', label: '답변 비교', icon: '⚖️' },
];

export default function ProfessorActionMenu({ role, name, tagline, side, onRefine, onAskProfessor, onAskAll, onCompare, onClose }) {
  const handlers = {
    refine: onRefine,
    askOne: onAskProfessor,
    askAll: onAskAll,
    compare: onCompare,
  };
  return (
    <div className={`professor-action-menu action-menu-${side}`} role="menu" aria-label={`${name} 액션 메뉴`}>
      <div className="professor-action-menu-head">
        <strong>{name}</strong>
        {tagline ? <span>{tagline}</span> : null}
      </div>
      <div className="professor-action-menu-grid">
        {MENU_ITEMS.map((item) => (
          <button
            key={item.key}
            type="button"
            role="menuitem"
            className={`professor-action-menu-btn act-${item.key}`}
            onClick={() => handlers[item.key]?.(role)}
          >
            <span aria-hidden="true">{item.icon}</span> {item.label}
          </button>
        ))}
      </div>
      <button type="button" className="professor-action-menu-close" onClick={onClose}>닫기</button>
    </div>
  );
}
