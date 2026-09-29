import React from 'react';
import { normalizeMode } from './modeInteractionProfiles';

// 모드별 교수 인터랙션 타임라인(읽기 전용 visual).
//   · AgentDiscussionThread 와 별개 컴포넌트(기존 트리/말풍선 로직 불변).
//   · 백엔드가 보낸 실제 인터랙션 내용만 표시한다(프론트가 내용을 지어내지 않음).
//   · interactions 가 비면 아무것도 렌더하지 않는다.
const MODE_TAG = {
  basic: { label: '기본', color: '#2563eb' },
  socratic: { label: '소크라테스', color: '#7C3AED' },
  debate: { label: '토론', color: '#DC2626' },
  simulation: { label: '상황극', color: '#059669' },
};

const ROLE_DOT = { theory: '#2563eb', book: '#EA580C', ai: '#7C3AED' };

function InteractionRow({ it }) {
  const fromColor = ROLE_DOT[it.fromRole] || '#9ca3af';
  const targetColor = ROLE_DOT[it.targetRole] || '#9ca3af';
  return (
    <li className="prof-interaction-row">
      <div className="prof-interaction-head">
        {(it.phaseLabel || it.relationLabel) && (
          <span className="prof-interaction-phase">{it.phaseLabel || it.relationLabel}</span>
        )}
        {it.fromName && (
          <span className="prof-interaction-actor">
            <i style={{ background: fromColor }} aria-hidden="true" />
            {it.fromName}
          </span>
        )}
        {it.relationLabel && <span className="prof-interaction-rel">{it.relationLabel}</span>}
        {it.targetName && (
          <span className="prof-interaction-actor">
            <i style={{ background: targetColor }} aria-hidden="true" />
            {it.targetName}
          </span>
        )}
        {it.appliedToFinal === true && <span className="prof-interaction-applied">최종 반영</span>}
        {it.appliedToFinal === false && <span className="prof-interaction-applied is-off">미반영</span>}
      </div>
      {it.content && <p className="prof-interaction-content">{it.content}</p>}
      {Array.isArray(it.sourceRefs) && it.sourceRefs.length > 0 && (
        <div className="prof-interaction-refs">
          {it.sourceRefs.slice(0, 6).map((s, i) => {
            const label = typeof s === 'string' ? s : (s?.title || s?.source || s?.url || '근거');
            const url = typeof s === 'object' ? s?.url : null;
            return url ? (
              <a key={i} href={url} target="_blank" rel="noopener noreferrer" className="prof-interaction-ref">
                {String(label).slice(0, 28)}
              </a>
            ) : (
              <span key={i} className="prof-interaction-ref">{String(label).slice(0, 28)}</span>
            );
          })}
        </div>
      )}
    </li>
  );
}

export default function ProfessorInteractionTimeline({ mode = 'basic', interactions = [] }) {
  if (!Array.isArray(interactions) || interactions.length === 0) return null;
  const m = normalizeMode(mode);
  const tag = MODE_TAG[m] || MODE_TAG.basic;

  return (
    <section className="prof-interaction-timeline" aria-label="교수 상호작용 타임라인">
      <div className="prof-interaction-title">
        <span className="prof-interaction-mode" style={{ background: tag.color }}>{tag.label}</span>
        <strong>교수 상호작용 흐름</strong>
        <span className="prof-interaction-count">{interactions.length}</span>
      </div>
      <ol className="prof-interaction-list">
        {interactions.map((it) => (
          <InteractionRow key={it.key || `${it.phase}-${it.fromRole}-${it.eventId}`} it={it} />
        ))}
      </ol>
    </section>
  );
}
