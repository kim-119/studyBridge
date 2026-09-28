import React from 'react';
import { AlertTriangle, Loader2, Info } from 'lucide-react';

// ─────────────────────────────────────────────────────────────────────────────
// Semantic MindMap 상태 바(loading / DEGRADED / FAILED). OK 는 아무것도 그리지 않는다.
//  · 기존 Obsidian 다크 패널 토큰(#111827/#1f2937/#cbd5e1/#FB923C/#f87171)만 사용. 신규 색상/폰트 없음.
//  · FAILED 는 "개념 구조를 생성하지 못했습니다" 를 명시한다(예전 토큰 그래프로 되돌아가지 않음).
// ─────────────────────────────────────────────────────────────────────────────
const REASON_KO = {
  EMPTY_ANSWER: '아직 교수 답변이 없어 개념 구조를 만들 수 없습니다.',
  NO_ANSWERS: '아직 교수 답변이 없어 개념 구조를 만들 수 없습니다.',
  NO_VALID_CONCEPTS: 'AI 가 이 답변에서 유효한 개념을 찾지 못했습니다.',
  GRAPH_VALIDATION_FAILED: 'AI 가 만든 개념 구조가 검증을 통과하지 못했습니다.',
  INTERNAL_ERROR: 'AI 의미 분석 서버 내부 오류입니다.',
  TIMEOUT: 'AI 의미 분석이 시간 안에 끝나지 않았습니다(504).',
  AI_UPSTREAM_TIMEOUT: 'AI 의미 분석이 시간 안에 끝나지 않았습니다(504).',
  AI_UPSTREAM_UNAVAILABLE: 'AI 의미 분석 서버에 연결할 수 없습니다.',
  UPSTREAM_CONTRACT_REJECTED: 'AI 서버가 요청 형식을 거절했습니다(422).',
  UPSTREAM_ROUTE_NOT_FOUND: 'AI 의미 분석 서버에 마인드맵 경로가 아직 배포되지 않았습니다.',
  UPSTREAM_TIMEOUT: 'AI 의미 분석이 시간 안에 끝나지 않았습니다.',
  UPSTREAM_UNREACHABLE: 'AI 의미 분석 서버에 연결할 수 없습니다.',
  NETWORK_ERROR: '네트워크 오류로 개념 구조를 받지 못했습니다.',
  NO_CONCEPTS: 'AI 가 이 답변에서 개념을 찾지 못했습니다.',
};

export default function SemanticGraphStatus({ state, reason, onRetry }) {
  if (!state || state === 'idle' || state === 'ok') return null;
  const base = {
    display: 'flex', alignItems: 'center', gap: 8, padding: '6px 10px', fontSize: 12.5,
    background: '#111827', borderBottom: '1px solid #1f2937', color: '#cbd5e1', flexWrap: 'wrap',
  };
  if (state === 'loading') {
    return (
      <div className="obsg-semantic-status" role="status" aria-live="polite" style={base}>
        <Loader2 size={14} color="#93C5FD" style={{ animation: 'spin 1.2s linear infinite', flex: 'none' }} />
        <span>AI 가 답변에서 개념 구조를 추출하는 중… (몇 초 걸릴 수 있어요)</span>
      </div>
    );
  }
  if (state === 'degraded') {
    return (
      <div className="obsg-semantic-status" role="status" data-semantic-status="DEGRADED" style={{ ...base, color: '#FB923C' }}>
        <Info size={14} color="#FB923C" style={{ flex: 'none' }} />
        <span>개념 구조가 축약 모드(DEGRADED)로 생성되었습니다{reason ? ` · ${reason}` : ''}.</span>
        {onRetry && <button type="button" className="obsg-btn" onClick={() => onRetry(true)}>다시 생성</button>}
      </div>
    );
  }
  // failed
  return (
    <div className="obsg-semantic-status" role="alert" data-semantic-status="FAILED" style={{ ...base, color: '#f87171' }}>
      <AlertTriangle size={14} color="#f87171" style={{ flex: 'none' }} />
      <span>개념 구조를 생성하지 못했습니다. {REASON_KO[reason] || (reason ? `(${reason})` : '')}</span>
      {onRetry && reason !== 'NO_ANSWERS' && reason !== 'EMPTY_ANSWER' && <button type="button" className="obsg-btn" onClick={() => onRetry(true)}>다시 시도</button>}
    </div>
  );
}
