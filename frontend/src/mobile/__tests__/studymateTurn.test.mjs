import test from 'node:test';
import assert from 'node:assert/strict';
import {
  applyAgentAnswer,
  applyAgentStart,
  applyAllComplete,
  applyDebateSection,
  applyModeGuard,
  createTurnState,
  isModeGuardPayload,
} from '../screens/studymate/turnAccumulator.js';
import { resolveTurnTarget } from '../screens/studymate/streamPayload.js';

const agents = [
  { id: 1, name: 'A 교수' },
  { id: 2, name: 'B 교수' },
];

function newTurn({ mode = 'basic', message = '질문' } = {}) {
  return createTurnState({
    parentId: 'req-1',
    requestId: 'req-1',
    roomAgents: agents,
    target: resolveTurnTarget(message, agents, null),
    mode,
    fallbackAgentName: 'A 교수',
  });
}

test('대기 카드는 같은 교수의 실제 답변으로 교체된다', () => {
  const turn = newTurn();
  applyAgentStart(turn, { agentId: 1, agentIndex: 1, agentName: 'A 교수' });
  const messages = applyAgentAnswer(turn, { agentId: 1, agentIndex: 1, agentName: 'A 교수', content: '답변입니다' });

  assert.equal(messages.length, 1);
  assert.equal(messages[0].content, '답변입니다');
  assert.equal(messages[0].isPending, false);
  assert.equal(messages[0].parentId, 'req-1');
  assert.equal(messages[0].agentSlot, 0);
  assert.equal(messages[0].mode, 'basic');
});

test('한 교수를 지정하면 다른 교수의 답변은 카드로 만들지 않는다', () => {
  const turn = newTurn({ message: '@B 교수 알려줘' });
  assert.equal(applyAgentAnswer(turn, { agentId: 1, agentName: 'A 교수', content: '끼어들기' }), null);

  const messages = applyAgentAnswer(turn, { agentId: 2, agentName: 'B 교수', content: 'B 답변' });
  assert.deepEqual(messages.map((message) => message.senderName), ['B 교수']);
});

test('빈 답변과 내부 진단 문구는 실패 안내로 바꾼다', () => {
  const turn = newTurn();
  const [message] = applyAgentAnswer(turn, { agentId: 1, agentName: 'A 교수', content: "'qwen3' 모델이 빈 응답을 반환했습니다" });
  assert.equal(message.isError, true);
  assert.equal(message.content, '응답 생성에 실패했습니다. 다시 시도해 주세요.');
});

test('토론 단계는 하나의 구조화 말풍선에 모인다', () => {
  const turn = newTurn({ mode: 'debate' });
  applyDebateSection(turn, { stageType: 'OPENING_STATEMENT', side: 'PRO', agentName: 'A 교수', content: '찬성' });
  const messages = applyDebateSection(turn, { stageType: 'OPENING_STATEMENT', side: 'CON', agentName: 'B 교수', content: '반대' });

  assert.equal(messages.length, 1);
  assert.equal(messages[0].turnKind, 'debate');
  assert.deepEqual(messages[0].stages.map((stage) => stage.title), ['찬성측 입론', '반대측 입론']);
});

test('all_complete 에 아무 답변도 없으면 answers 로 카드를 만든다', () => {
  const turn = newTurn();
  const messages = applyAllComplete(turn, { answers: [{ agentId: 2, agentName: 'B 교수', answer: '최종' }] });
  assert.equal(messages[0].content, '최종');
  assert.equal(messages[0].agentSlot, 1);
  assert.equal(applyAllComplete(turn, {}), null);
});

test('all_complete 에도 내용이 없으면 실패 안내를 보여준다', () => {
  const [message] = applyAllComplete(newTurn(), {});
  assert.equal(message.isError, true);
});

test('모드 가드 응답은 안내 상태로 렌더한다', () => {
  const guard = { code: 'NON_LEARNING_INPUT', status: 'BLOCKED' };
  assert.equal(isModeGuardPayload(guard), true);

  const [message] = applyModeGuard(newTurn({ mode: 'debate' }), guard);
  assert.equal(message.isNotice, true);
  assert.equal(message.isError, false);
  assert.match(message.content, /^\[토론 모드\]/);
});
