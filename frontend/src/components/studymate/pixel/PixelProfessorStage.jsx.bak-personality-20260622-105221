import React, { useEffect } from 'react';
import { PROFESSORS, getStateAnim, ACTIVE_VISUAL_STATES } from './professorSprites';
import PixelProfessorSprite from './PixelProfessorSprite';
import ProfessorActionMenu from './ProfessorActionMenu';
import MinuteRecapBubble from './MinuteRecapBubble';
import './pixelProfessor.css';

// 교수님들과 대화 stage. classroom 배경 위에 교수 sprite 3명을 actor로 렌더링한다.
//   · 답변 배열에 절대 push하지 않는 visual consumer. visualStates(시각 상태)만 소비.
//   · 교수 클릭 → selected + 액션 메뉴. 배경 클릭/ESC → 선택 해제.
//   · completed/error 는 잠깐 표시 후 onAutoReset(role)으로 idle 복귀.
export default function PixelProfessorStage({
  visualStates = {},
  onAutoReset,
  selectedRole,
  onSelectRole,
  recap,
  onRecapDismiss,
  onRefine,
  onAskProfessor,
  onAskAll,
  onCompare,
}) {
  // completed/error 자동 복귀 타이머(transient). 상태 변경/unmount 시 정리.
  useEffect(() => {
    const timers = [];
    PROFESSORS.forEach(({ role }) => {
      const anim = getStateAnim(visualStates[role]);
      if (anim.transient && onAutoReset) {
        timers.push(setTimeout(() => onAutoReset(role), anim.transient));
      }
    });
    return () => timers.forEach((t) => clearTimeout(t));
  }, [visualStates, onAutoReset]);

  // ESC → 선택 해제.
  useEffect(() => {
    if (!selectedRole) return undefined;
    const onKey = (e) => { if (e.key === 'Escape') onSelectRole?.(null); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [selectedRole, onSelectRole]);

  const selected = PROFESSORS.find((p) => p.role === selectedRole) || null;

  // 표시 상태: 진행 중(걷기/생각/답변/검증/피드백)이면 SSE 애니메이션 유지,
  //   그 외(idle/완료 등)일 때만 선택 포즈(SELECTED)로 덮어쓴다.
  const displayState = (role) => {
    const s = visualStates[role] || 'idle';
    if (selectedRole === role && !ACTIVE_VISUAL_STATES.has(s)) return 'selected';
    return s;
  };

  return (
    <section
      className="pixel-professor-stage"
      onClick={() => onSelectRole?.(null)}
      aria-label="교수님들과 대화 픽셀 교실"
    >
      <p className="pixel-stage-guide">
        교수님을 클릭해 액션을 고르거나, 아래 입력창에서 질문을 보내보세요.
      </p>

      <div className="pixel-professor-layer">
        {PROFESSORS.map((p) => (
          <PixelProfessorSprite
            key={p.role}
            role={p.role}
            name={p.name}
            tagline={p.tagline}
            sheet={p.sheet}
            side={p.side}
            pos={p.pos}
            state={displayState(p.role)}
            selected={selectedRole === p.role}
            onSelect={(role) => onSelectRole?.(role === selectedRole ? null : role)}
          />
        ))}
      </div>

      {selected && (
        // 메뉴 내부 클릭이 stage(배경) deselect로 전파되지 않게 차단.
        <div className="pixel-menu-portal" onClick={(e) => e.stopPropagation()}>
          <ProfessorActionMenu
            role={selected.role}
            name={selected.name}
            tagline={selected.tagline}
            side={selected.side}
            onRefine={onRefine}
            onAskProfessor={onAskProfessor}
            onAskAll={onAskAll}
            onCompare={onCompare}
            onClose={() => onSelectRole?.(null)}
          />
        </div>
      )}

      <MinuteRecapBubble recap={recap} onDismiss={onRecapDismiss} />
    </section>
  );
}
