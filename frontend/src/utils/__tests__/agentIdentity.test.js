// node --test frontend/src/utils/__tests__   (vitest/jest 미도입 — Node 내장 테스트 러너 사용)
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  agentIdOf, resolveRoomAgentSlot, resolveMentionTarget, isEventForTarget, hasAgentIdentity,
  applyMentionPrefill,
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

// ── 동명이인(같은 이름 교수 2명) 방어: 클릭으로 지정한 stable id 가 이름 매칭보다 우선한다 ──
//    이름은 identity 가 아니다. 이름이 같으면 이름 매칭은 항상 배열의 첫 번째(=1번 교수)를 고르므로,
//    "2번 교수를 클릭했는데 1번이 답한다" 가 재현된다.
const dupRoom = [
  { id: 31, name: 'AI 교수' },
  { id: 37, name: 'AI 교수' },
  { id: 42, name: '논점 검증 코치' },
];

test('mention: pinned agentId wins over duplicate display names', () => {
  const byNameOnly = resolveMentionTarget('@AI 교수 스택이 뭐야?', dupRoom);
  assert.equal(String(byNameOnly.agentId), '31'); // 이름만으로는 첫 번째로 붕괴(기존 동작)

  const pinned = resolveMentionTarget('@AI 교수 스택이 뭐야?', dupRoom, 37);
  assert.equal(pinned.scope, 'single');
  assert.equal(String(pinned.agentId), '37');
  assert.equal(pinned.slot, 1);
});

test('mention: stale pin is ignored when its mention is no longer in the text', () => {
  // 1번 → 2번 → 3번으로 빠르게 바꿔도 마지막에 실제로 멘션된 교수만 대상이 된다.
  const t = resolveMentionTarget('@논점 검증 코치 질문', dupRoom, 37);
  assert.equal(String(t.agentId), '42');
  // 다른 방(핀이 존재하지 않는 방)에서도 핀은 무시된다.
  assert.equal(String(resolveMentionTarget('@쉬운 풀이 튜터 질문', room, 999).agentId), '37');
  // @모두 는 여전히 전체 협업 모드.
  assert.equal(resolveMentionTarget('@모두 질문', dupRoom, 37).scope, 'all');
});

// ── 1번 → 2번 → 3번 연속 전환(stale target 없음) ────────────────────────────
// "이 교수에게 질문" 클릭은 draft 의 맨 앞 멘션을 교체하고(applyMentionPrefill) 그 교수의 stable id 를
// 핀으로 남긴다. 각 전송 시점의 대상은 그때 입력창에 있는 멘션 + 핀으로 결정된다.
test('rapid switching 1 → 2 → 3 always targets the last clicked professor', () => {
  const clicks = [];
  let draft = '';
  let pin = null;
  const clickProfessor = (slot) => {
    const ag = room[slot];
    draft = applyMentionPrefill(draft, `@${ag.name} `, room);
    pin = ag.id;
  };
  const send = (typed) => {
    const text = `${draft}${typed}`;
    const t = resolveMentionTarget(text, room, pin);
    clicks.push({ text, agentId: t.agentId, slot: t.slot, scope: t.scope });
    draft = '';           // 전송 후 입력창 비움
    return t;
  };

  clickProfessor(0); send('스택이 뭐야?');
  clickProfessor(1); send('더 쉽게 설명해줘');
  clickProfessor(2); send('반박해줘');

  assert.deepEqual(clicks.map((c) => String(c.agentId)), ['31', '37', '42']);
  assert.deepEqual(clicks.map((c) => c.slot), [0, 1, 2]);
  assert.ok(clicks.every((c) => c.scope === 'single'));
  // 이전 교수 멘션이 문장에 남아 있지 않다(대상 2명 동시 지목 불가).
  assert.ok(!clicks[1].text.includes('@개념 정리 교수'));
  assert.ok(!clicks[2].text.includes('@쉬운 풀이 튜터'));
});

test('prefill replaces only the leading mention and keeps the typed body', () => {
  const draft = applyMentionPrefill('@개념 정리 교수 스택이 뭐야?', '@쉬운 풀이 튜터 ', room);
  assert.equal(draft, '@쉬운 풀이 튜터 스택이 뭐야?');
  assert.equal(applyMentionPrefill('스택이 뭐야?', '@모두 ', room), '@모두 스택이 뭐야?');
  assert.equal(String(resolveMentionTarget(draft, room, 31).agentId), '37'); // 멘션에 없는 핀은 무시
});
