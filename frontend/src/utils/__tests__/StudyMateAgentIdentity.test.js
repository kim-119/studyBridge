// node --test frontend/src/utils/__tests__
import test from 'node:test';
import assert from 'node:assert/strict';
import { resolveRoomAgentSlot, isEventForTarget, agentIdOf, isVirtualAuthor } from '../agentIdentity.js';
import { neutralizeErrorText, classifyFailure, DEFAULT_STREAM_ERROR } from '../studymate/errorText.js';

const room = [
  { id: 31, name: '김교수' },
  { id: 37, name: '김교수' },        // 동명이인
  { id: 42, name: '논점 검증 코치' },
];

test('duplicate names: agentId decides the slot, never the name', () => {
  assert.equal(resolveRoomAgentSlot(room, { agentId: 37, agentName: '김교수' }), 1);
  assert.equal(resolveRoomAgentSlot(room, { agentId: '31', agentName: '김교수' }), 0);
  assert.equal(resolveRoomAgentSlot(room, { agentId: 42, agentName: '김교수' }), 2, '이름이 틀려도 id 가 identity');
});

test('name-only legacy event resolves to first match; unknown id does not fall back to first agent', () => {
  assert.equal(resolveRoomAgentSlot(room, { agentName: '논점 검증 코치' }), 2);
  assert.equal(resolveRoomAgentSlot(room, { agentId: 999 }), -1);
});

test('virtual author (debate-consensus) has identity but no slot; target filter must not drop it', () => {
  const consensus = { agentId: 'debate-consensus', agentName: '최종 결론 (합의)' };
  assert.equal(resolveRoomAgentSlot(room, consensus), -1);
  assert.equal(String(agentIdOf({ id: 37 })), '37');
  // single-target 필터: 대상 교수 37 에게 질문. 37 의 답변은 통과, 31 은 드롭, 가상 작성자는 통과해야 한다.
  const target = { scope: 'single', slot: 1, agentId: '37' };
  assert.equal(isEventForTarget(room, target, { agentId: 37 }), true);
  assert.equal(isEventForTarget(room, target, { agentId: 31 }), false);
  assert.equal(isVirtualAuthor(consensus), true);
  assert.equal(isVirtualAuthor({ agentId: '37' }), false);
  assert.equal(isEventForTarget(room, target, consensus), true, '가상 작성자는 특정 교수가 아니므로 대상 필터에서 제외하지 않는다');
});

test('error text is neutral: internal metadata never reaches the bubble; failure classification', () => {
  assert.equal(neutralizeErrorText('LLM timeout http://127.0.0.1:11434 qwen3 num_ctx=8192'), DEFAULT_STREAM_ERROR);
  assert.equal(neutralizeErrorText('Traceback (most recent call last) ...'), DEFAULT_STREAM_ERROR);
  assert.equal(neutralizeErrorText('이 교수의 답변을 받지 못했어요.'), '이 교수의 답변을 받지 못했어요.');
  assert.deepEqual(classifyFailure({ code: 'LLM_TIMEOUT', degraded: true }), { code: 'LLM_TIMEOUT', retryable: true, degraded: true, category: 'timeout' });
  assert.deepEqual(classifyFailure({ failureCode: 'AI_CONTRACT_FAILURE', retryable: false }), { code: 'AI_CONTRACT_FAILURE', retryable: false, degraded: false, category: 'rejected' });
});
