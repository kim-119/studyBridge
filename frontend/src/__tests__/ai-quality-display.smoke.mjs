// 품질 게이트 표시 경계 smoke test (의존성 0, 러너 불필요)
//   실행:  node src/__tests__/ai-quality-display.smoke.mjs   (frontend 디렉토리에서)
//   서버(Spring)가 승인 판정의 권위다. 여기서는 서버 회귀 시에도 미승인 본문을 그리지 않는 2차 경계와,
//   게이트 OFF(표식 없음)에서 기존 동작(ai07 자체 qualityStatus 'PARTIAL' 등)을 막지 않는 것을 확인한다.
import assert from 'node:assert/strict';
import {
  isGatedFrame, isDisplayableStreamBody, toQualityError, filterAllComplete, isDisplayableAiPayload, QUALITY_GATE_MODE,
} from '../utils/aiQualityDisplay.js';

let n = 0;
const t = (name, fn) => { fn(); n += 1; console.log('PASS', name); };

t('게이트 OFF: ai07 PARTIAL 답변도 기존처럼 표시', () => {
  assert.equal(isDisplayableStreamBody('agent_answer', { answer: 'x', qualityStatus: 'PARTIAL' }, false), true);
});
t('게이트 표식 인식', () => {
  assert.equal(isGatedFrame({ qualityGateMode: QUALITY_GATE_MODE }), true);
  assert.equal(isGatedFrame({ qualityGateMode: 'other' }), false);
  assert.equal(isGatedFrame(null), false);
});
t('게이트 ON: APPROVED 만 표시, 그 외/누락은 차단', () => {
  assert.equal(isDisplayableStreamBody('agent_answer', { answer: 'x', qualityStatus: 'APPROVED' }, true), true);
  assert.equal(isDisplayableStreamBody('agent_answer', { answer: 'x', qualityStatus: 'PARTIAL' }, true), false);
  assert.equal(isDisplayableStreamBody('agent_answer', { answer: 'x' }, true), false);
  assert.equal(isDisplayableStreamBody('socratic_step', { question: 'q' }, true), false);
  assert.equal(isDisplayableStreamBody('turn_start', { turnId: 't' }, true), true, '진행 이벤트는 통과');
});
t('차단 시 본문 없는 agent_error 로 변환(식별자 유지)', () => {
  const e = toQualityError({ answer: 'CANARY 본문', content: 'CANARY', agentIndex: 2, eventId: 'e1', turnId: 't1' });
  assert.equal(e.code, 'QUALITY_REJECTED');
  assert.equal(e.agentIndex, 2);
  assert.equal(e.eventId, 'e1');
  assert.equal(JSON.stringify(e).includes('CANARY'), false);
});
t('all_complete: 게이트 ON 이면 승인 항목만', () => {
  const d = { answers: [{ answer: 'a', qualityStatus: 'APPROVED' }, { answer: 'b' }], messages: [{ content: 'm', qualityStatus: 'REJECTED' }] };
  const f = filterAllComplete(d, true);
  assert.deepEqual(f.answers.map((a) => a.answer), ['a']);
  assert.equal(f.messages.length, 0);
  assert.equal(filterAllComplete(d, false), d, '게이트 OFF 는 원본 그대로');
});
t('JSON 응답: success/verified/qualityStatus 규칙', () => {
  assert.equal(isDisplayableAiPayload({ overview: 'x' }), true, '게이트 OFF 응답(필드 없음)');
  assert.equal(isDisplayableAiPayload({ overview: 'x', qualityStatus: 'APPROVED', verified: true }), true);
  assert.equal(isDisplayableAiPayload({ overview: 'x', qualityStatus: 'REJECTED' }), false);
  assert.equal(isDisplayableAiPayload({ overview: 'x', verified: false }), false);
  assert.equal(isDisplayableAiPayload({ success: false, errorCode: 'AI_QUALITY_REJECTED' }), false);
  assert.equal(isDisplayableAiPayload(null), false);
});
console.log(`ai-quality-display smoke: ${n} passed`);
