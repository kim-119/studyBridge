import React, { useEffect, useRef, useState } from 'react';
import { PROFESSORS, getStateAnim, ACTIVE_VISUAL_STATES, ROLE_TO_AGENT_INDEX, getProfessorSpriteSheetForAgent } from './professorSprites';
import PixelProfessorSprite from './PixelProfessorSprite';
import useAnchoredMenu from './useAnchoredMenu';
import ProfessorActionMenu from './ProfessorActionMenu';
import ProfessorSpeechBubble from './ProfessorSpeechBubble';
import MinuteRecapBubble from './MinuteRecapBubble';
import './pixelProfessor.css';

// 말풍선 kind → 전체보기 패널 헤더에 표시할 답변 종류 라벨.
const bubbleKindLabel = (kind) => ({
  answer: '답변',
  feedback: '피드백',
  rebuttal: '반박',
  evidence: '근거 보강',
  thinking: '생각 중',
  done: '요약',
}[kind] || '답변');

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

  // 말풍선 클릭 → 전체 답변 상세 패널(presentation only, 채팅 append 없음).
  const [expandedBubble, setExpandedBubble] = useState(null);

  // ESC → 전체 답변 패널 닫기(우선순위상 selectedRole ESC보다 위. 둘 중 열린 쪽만 동작).
  useEffect(() => {
    if (!expandedBubble) return undefined;
    const onKey = (e) => { if (e.key === 'Escape') setExpandedBubble(null); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [expandedBubble]);

  const professorActors = PROFESSORS.map((p) => {
    const agentIndex = ROLE_TO_AGENT_INDEX[p.role];
    const agent = agents?.[agentIndex];
    const personality = String(
      agent?.personality ||
      agent?.tone ||
      agent?.personalityStyle ||
      agent?.style ||
      ''
    ).trim();

    // 화면 표시명/멘션명은 항상 실제 agent.name 을 우선한다. 없으면 role 기본명으로 fallback.
    //   내부 role 라우팅(book|theory|ai)은 그대로 유지된다.
    const displayName = agent?.name || p.name;

    return {
      ...p,
      agent,
      agentIndex,
      displayName,
      mentionName: displayName,
      name: displayName,
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
    <>
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

      {/* 답변 말풍선 레이어: 교수 sprite와 동일 좌표로 머리 위에 띄운다(presentation only).
          overlay 우선순위: 액션 메뉴가 열려 있으면(menu mode) 말풍선을 숨겨 화면을 정리한다. */}
      {!selectedRole && (
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
                <ProfessorSpeechBubble
                  name={b.agentName || p.displayName || p.name}
                  text={b.text}
                  fullText={b.fullText}
                  side={p.side}
                  kind={b.kind}
                  targetRole={b.targetRole}
                  onExpand={(detail) => setExpandedBubble({ ...detail, name: b.agentName || p.displayName || p.name })}
                />
              </div>
            );
          })}
        </div>
      )}

      {/* 전체 답변 상세 패널: stage 내부 absolute overlay(레이아웃을 밀지 않음).
          overlay 우선순위 최상위 → backdrop click / 닫기 버튼 / ESC 로 닫는다. */}
      {expandedBubble && (
        <div
          className="pixel-bubble-detail-backdrop"
          onClick={() => setExpandedBubble(null)}
        >
          <article
            className="pixel-bubble-detail-panel"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-label={`${expandedBubble.name || '교수'} 전체 답변`}
          >
            <header className="pixel-bubble-detail-header">
              <div className="pixel-bubble-detail-title">
                <strong>{expandedBubble.name || '교수'}</strong>
                <span className={`pixel-bubble-detail-kind kind-${expandedBubble.kind || 'answer'}`}>
                  {bubbleKindLabel(expandedBubble.kind)}
                </span>
              </div>
              <button
                type="button"
                className="pixel-bubble-detail-close"
                onClick={() => setExpandedBubble(null)}
              >
                닫기
              </button>
            </header>
            <div className="pixel-bubble-detail-body">
              {expandedBubble.fullText || expandedBubble.text}
            </div>
          </article>
        </div>
      )}

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

    </section>

    {/* recap 요약: overlay 우선순위상 stage 내부 floating 금지 → 액션 메뉴가 닫혀 있을 때만,
        stage 바깥 하단에 접힌 chip 형태로 배치한다(교수/책상/말풍선을 가리지 않음). */}
    {!selectedRole && !expandedBubble && (
      <div className="pixel-recap-dock">
        <MinuteRecapBubble recap={recap} agents={agents} onDismiss={onRecapDismiss} />
      </div>
    )}
    </>
  );
}
