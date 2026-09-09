// node --test frontend/src/utils/__tests__   (vitest/jest 미도입 — Node 내장 테스트 러너 사용)
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  agentIdOf, resolveRoomAgentSlot, resolveMentionTarget, isEventForTarget, hasAgentIdentity,
} from '../agentIdentity.js';

const room = [
  { id: 31, name: '개념 정리 교수' },
  { id: 37, name: '쉬운 풀이 튜터' },
  { id: 42, name: '논점 검증 코치' },
];

test('mention: clicking/typing @2번 교수 resolves to stable id 37 (slot 1)', () => {
  const t = resolveMentionTarget('@쉬운 풀이 튜터 스택이 뭐야?', room);
  assert.equal(t.scope, 'single');
  assert.equal(String(t.agentId), '37');
  assert.equal(t.slot, 1);
  assert.equal(t.agentName, '쉬운 풀이 튜터');
});

test('mention: @모두 or no mention keeps group mode', () => {
  assert.equal(resolveMentionTarget('@모두 스택이 뭐야?', room).scope, 'all');
  assert.equal(resolveMentionTarget('스택이 뭐야?', room).scope, 'all');
  assert.equal(resolveMentionTarget('@쉬운 풀이 튜터 @모두', room).scope, 'all');
});

test('mention: longest matching name wins (prefix names)', () => {
  const r2 = [{ id: 1, name: 'AI 교수' }, { id: 2, name: 'AI 교수 2' }];
  assert.equal(resolveMentionTarget('@AI 교수 2 질문', r2).agentId, 2);
  assert.equal(resolveMentionTarget('@AI 교수 질문', r2).agentId, 1);
});

test('slot: resolves by agentId first (string/number), then name, then legacy 1-based agentIndex', () => {
  assert.equal(resolveRoomAgentSlot(room, { agentId: '37', agentIndex: 1 }), 1);   // filtered-array index ignored
  assert.equal(resolveRoomAgentSlot(room, { agentId: 42, agentIndex: 1 }), 2);
  assert.equal(resolveRoomAgentSlot(room, { agentName: '개념 정리 교수', agentIndex: 3 }), 0);
  assert.equal(resolveRoomAgentSlot(room, { agentIndex: 2 }), 1);                   // legacy 1-based → slot 1
  assert.equal(resolveRoomAgentSlot(room, { agentSlot: 2 }), 2);
  assert.equal(resolveRoomAgentSlot(room, { agentId: 'agent-9', agentName: '없음' }), -1);
  assert.equal(resolveRoomAgentSlot(room, {}), -1);
});

test('slot: identity is independent of array order', () => {
  const reordered = [room[2], room[0], room[1]];
  assert.equal(resolveRoomAgentSlot(reordered, { agentId: 37 }), 2);
  assert.equal(resolveMentionTarget('@쉬운 풀이 튜터 질문', reordered).slot, 2);
});

test('target filter: response from agent B renders on B; A is dropped; unidentified is preserved', () => {
  const target = resolveMentionTarget('@쉬운 풀이 튜터 질문', room);
  assert.equal(isEventForTarget(room, target, { agentId: 37, agentIndex: 1 }), true);
  assert.equal(isEventForTarget(room, target, { agentId: 31, agentIndex: 1 }), false);
  assert.equal(isEventForTarget(room, target, { agentName: '논점 검증 코치' }), false);
  assert.equal(isEventForTarget(room, target, { content: 'no identity' }), true);
  assert.equal(isEventForTarget(room, { scope: 'all' }, { agentId: 31 }), true);
  assert.equal(isEventForTarget(room, null, { agentId: 31 }), true);
});

test('helpers', () => {
  assert.equal(agentIdOf({ id: 5 }), 5);
  assert.equal(agentIdOf({ agentId: '7', id: 5 }), '7');
  assert.equal(agentIdOf(null), null);
  assert.equal(hasAgentIdentity({ agentIndex: 0 }), true);
  assert.equal(hasAgentIdentity({}), false);
});
