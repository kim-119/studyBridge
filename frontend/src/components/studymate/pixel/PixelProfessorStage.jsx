import React, { useEffect, useRef } from 'react';
import { PROFESSORS, getStateAnim, ACTIVE_VISUAL_STATES, ROLE_TO_AGENT_INDEX, getProfessorSpriteSheetForAgent } from './professorSprites';
import PixelProfessorSprite from './PixelProfessorSprite';
import useAnchoredMenu from './useAnchoredMenu';
import ProfessorActionMenu from './ProfessorActionMenu';
import ProfessorSpeechBubble from './ProfessorSpeechBubble';
import MinuteRecapBubble from './MinuteRecapBubble';
import './pixelProfessor.css';

// 교수님들과 대화 stage. classroom 배경 위에 교수 sprite 3명을 actor로 렌더링한다.
//   · 답변 배열에 절대 push하지 않는 visual consumer. visualStates(시각 상태)만 소비.
//   · 교수 클릭 → selected + 액션 메뉴. 배경 클릭/ESC → 선택 해제.
//   · completed/error 는 잠깐 표시 후 onAutoReset(role)으로 idle 복귀.
export default function PixelProfessorStage({
  visualStates = {},
  agents = [],
  bubbles = {},
  stageStatusMessage = '',
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

  const professorActors = PROFESSORS.map((p) => {
    const agent = agents?.[ROLE_TO_AGENT_INDEX[p.role]];
    const personality = String(
      agent?.personality ||
      agent?.tone ||
      agent?.personalityStyle ||
      agent?.style ||
      ''
    ).trim();

    return {
      ...p,
      sheet: getProfessorSpriteSheetForAgent(agent, p.sheet),
      // 액션 라우팅은 role 기준으로 고정한다.
      // 성격 선택 결과는 sprite sheet와 tagline에만 반영한다.
      tagline: personality ? `${personality} · ${p.tagline}` : p.tagline,
    };
  });

  const selected = professorActors.find((p) => p.role === selectedRole) || null;

  // 표시 상태: 진행 중(걷기/생각/답변/검증/피드백)이면 SSE 애니메이션 유지,
  //   그 외(idle/완료 등)일 때만 선택 포즈(SELECTED)로 덮어쓴다.
  const displayState = (role) => {
    const s = visualStates[role] || 'idle';
    if (selectedRole === role && !ACTIVE_VISUAL_STATES.has(s)) return 'selected';
    return s;
  };

  // 액션 메뉴를 선택 교수 actor rect 기준으로 anchor + 충돌 보정(인치/해상도 분기 없음).
  const stageRef = useRef(null);
  const menuSignature = selected ? `${selected.role}|${selected.name}|${selected.tagline}` : '';
  const { menuRef, pos: menuPos } = useAnchoredMenu({ stageRef, selectedRole, signature: menuSignature });

  return (
    <section
      ref={stageRef}
      className="pixel-professor-stage"
      onClick={() => onSelectRole?.(null)}
      aria-label="교수님들과 대화 픽셀 교실"
    >
      {/* stage 상단 안내문: 상태 기반(stageStatusMessage)이 있으면 우선, 없으면 기본 안내. */}
      <p className="pixel-stage-guide" aria-live="polite">
        {stageStatusMessage || '교수님을 클릭해 액션을 고르거나, 아래 입력창에서 질문을 보내보세요.'}
      </p>

      <div className="pixel-professor-layer">
        {professorActors.map((p) => (
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

      {/* 답변 말풍선 레이어: 교수 sprite와 동일 좌표로 머리 위에 띄운다(presentation only). */}
      <div className="pixel-professor-bubble-layer">
        {professorActors.map((p) => {
          const b = bubbles[p.role];
          if (!b || !b.text) return null;
          return (
            <div
              key={`bubble-${p.role}`}
              className="prof-bubble-anchor"
              style={{ left: `${p.pos.left}%`, bottom: `${p.pos.bottom + 200}px` }}
            >
              <ProfessorSpeechBubble name={b.agentName || p.name} text={b.text} side={p.side} kind={b.kind} targetRole={b.targetRole} />
            </div>
          );
        })}
      </div>

      {selected && (
        // 메뉴 내부 클릭이 stage(배경) deselect로 전파되지 않게 차단.
        <div className="pixel-menu-portal" onClick={(e) => e.stopPropagation()}>
          <ProfessorActionMenu
            role={selected.role}
            name={selected.name}
            tagline={selected.tagline}
            innerRef={menuRef}
            placement={menuPos.placement}
            style={{ left: `${menuPos.left}px`, top: `${menuPos.top}px`, visibility: menuPos.ready ? 'visible' : 'hidden' }}
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
