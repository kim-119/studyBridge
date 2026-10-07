// 입장 준비(PreJoin) 공통 UI 상수 — 아이콘은 lucide-react(번들 포함, 외부 CDN/API 없음)만 사용한다.
//  · size 는 그룹스터디 기존 화면 값(인라인 16 / 하단 내비 24 / 큰 fallback 40)을 재사용하고 strokeWidth 는 프로젝트 기본값(미지정)을 따른다.
export const ICON_SIZE = 16;
export const NAV_ICON_SIZE = 24;
export const AVATAR_FALLBACK_ICON_SIZE = 40;

// 기존 프리조인 화면의 색/간격 값(새 색상 토큰을 추가하지 않는다).
export const PILL_BUTTON_STYLE = {
  display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 14px', borderRadius: '999px',
  border: '1px solid', cursor: 'pointer', fontSize: '13px', fontWeight: 600,
};
export const SELECT_STYLE = {
  width: '100%', appearance: 'none', border: 'none', backgroundColor: 'transparent',
  fontSize: '15px', color: 'var(--color-text-main)', cursor: 'pointer', outline: 'none',
};
export const SELECT_CARET_STYLE = { position: 'absolute', right: 0, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' };
export const SECTION_LABEL_STYLE = { display: 'flex', alignItems: 'center', gap: '8px', color: '#4B5563', marginBottom: '12px' };
export const HINT_STYLE = { fontSize: '12px', color: 'var(--color-text-placeholder)' };
