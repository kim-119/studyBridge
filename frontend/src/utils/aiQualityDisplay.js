// AI 응답 품질 표시 경계(2차 점검). 승인 판정의 권위는 Spring 서버(AiResponseQualityGate/QualityStreamGate)이며,
// 이 모듈은 서버 회귀·우회로 미승인 본문이 내려와도 화면에 그리지 않기 위한 방어선이다(프런트 검사만으로 보안을 보장하지 않는다).
//
// 규칙(EC2 canonical):
//  · SSE: 게이트를 거친 프레임은 qualityGateMode='spring-v1' 을 갖는다. 한 턴에서 이 표식을 한 번이라도 보면
//    그 턴의 본문 이벤트는 qualityStatus==='APPROVED' 일 때만 그린다. 게이트 OFF(표식 없음)는 기존 동작 그대로
//    (ai07 자체 qualityStatus 'PARTIAL' 등은 게이트 판정이 아니므로 막지 않는다).
//  · JSON: qualityStatus 가 있으면 'APPROVED' 여야 하고, verified===false 또는 success===false 면 본문을 그리지 않는다.

export const QUALITY_GATE_MODE = 'spring-v1';

// 본문(생성 텍스트)을 싣는 SSE 이벤트 — api.js streamMessage 디스패치와 같은 이름.
export const BODY_EVENTS = new Set([
  'agent_answer', 'stage_complete', 'agent_stage_complete', 'debate_section', 'socratic_step', 'socratic_answer',
  'simulation_stage', 'follow_up_suggestions', 'direct_reply', 'route_pipeline',
]);

export const QUALITY_BLOCKED_MESSAGE = 'AI가 만든 답변이 품질 기준을 통과하지 못해 표시하지 않았습니다. 다시 시도해 주세요.';

export function isGatedFrame(data) {
  return !!data && typeof data === 'object' && data.qualityGateMode === QUALITY_GATE_MODE;
}

/** 게이트 모드 턴에서 이 본문 이벤트를 그려도 되는가. */
export function isDisplayableStreamBody(event, data, gated) {
  if (!gated || !BODY_EVENTS.has(event)) return true;
  return !!data && data.qualityStatus === 'APPROVED';
}

/** 미승인 본문을 agent_error 형태로 바꾼다(본문 텍스트는 버리고 식별자만 남김). */
export function toQualityError(data) {
  const d = data && typeof data === 'object' ? data : {};
  const out = { type: 'agent_error', code: 'QUALITY_REJECTED', status: 'FAILED', retryable: true, degraded: true,
    message: QUALITY_BLOCKED_MESSAGE };
  for (const k of ['agentId', 'agentIndex', 'agentName', 'eventId', 'turnId', 'requestId', 'displayOrder', 'stage']) {
    if (d[k] !== undefined) out[k] = d[k];
  }
  return out;
}

/** 게이트 모드 all_complete 에서 승인되지 않은 answers/messages 항목을 제거한다. */
export function filterAllComplete(data, gated) {
  if (!gated || !data || typeof data !== 'object') return data;
  const keep = (list) => (Array.isArray(list) ? list.filter((a) => a && a.qualityStatus === 'APPROVED') : list);
  return { ...data, answers: keep(data.answers), messages: keep(data.messages) };
}

/** JSON 응답(요약·퀴즈 등) 본문을 그려도 되는가. */
export function isDisplayableAiPayload(payload) {
  if (!payload || typeof payload !== 'object') return false;
  if (payload.success === false) return false;
  if (payload.verified === false) return false;
  if (payload.qualityStatus != null && payload.qualityStatus !== 'APPROVED') return false;
  return true;
}
