import test from 'node:test';
import assert from 'node:assert/strict';
import {
  buildStreamPayload,
  captureConversationState,
  consumeSimulationChoice,
  nextRegenerateAttempt,
  resolveActiveLearningMode,
  resolveTurnTarget,
  sanitizeQuestion,
  selectSimulationChoice,
} from '../screens/studymate/streamPayload.js';

const agents = [
  { id: 101, name: '개념 정리 교수' },
  { id: 102, name: '쉬운 풀이 튜터' },
  { id: 103, name: '논점 검증 코치' },
];

function payloadFor({ message = '질문', room = { learningMode: 'basic', agents }, conversationState = {}, pinned = null, attempt = 1 } = {}) {
  const mode = resolveActiveLearningMode(room.learningMode, message);
  const target = resolveTurnTarget(message, room.agents, pinned);
  return buildStreamPayload({ message, room, mode, target, conversationState, requestId: 'req-1', regenerateAttempt: attempt });
}

test('기본 모드는 mode 를 생략하고 단계 정책 플래그를 보낸다', () => {
  const payload = payloadFor();

  assert.equal(payload.message, '질문');
  assert.equal(payload.learningMode, 'basic');
  assert.equal('mode' in payload, false);
  assert.equal(payload.rounds, 1);
  assert.equal(payload.stagePolicy, 'full');
  assert.equal(payload.enableDeepening, true);
  assert.equal(payload.enablePeerFeedback, true);
  assert.equal(payload.enableHallucinationValidation, true);
  assert.equal(payload.messageId, 'req-1');
  assert.equal(payload.regenerateAttempt, 1);
  assert.equal(payload.forceRegenerate, false);
});

test('기본 방에서 소크라테스식 요청을 하면 소크라테스로 승격한다', () => {
  assert.equal(resolveActiveLearningMode('basic', '질문으로 유도해서 알려줘'), 'socratic');
  assert.equal(resolveActiveLearningMode('debate', '소크라테스 방식으로'), 'debate');
});

test('소크라테스 방은 방 설정과 세션 상태를 싣는다', () => {
  const payload = payloadFor({
    message: '내 생각엔 스택이야',
    room: { learningMode: 'socratic', agents, socraticConfig: { questionIntensity: 'intensive', hintPolicy: 'step' } },
    conversationState: { mode: 'socratic', sessionId: 's-1', socraticState: { step: 2 } },
  });

  assert.equal(payload.mode, 'socratic');
  assert.equal(payload.userAttempt, '내 생각엔 스택이야');
  assert.deepEqual(payload.socraticConfig, { questionIntensity: 'intensive', hintPolicy: 'step' });
  assert.equal(payload.sessionId, 's-1');
  assert.deepEqual(payload.socraticState, { step: 2 });
  assert.equal(payload.stagePolicy, undefined);
});

test('토론 방은 강도와 멀티턴 상태를 싣는다', () => {
  const payload = payloadFor({
    room: { learningMode: 'debate', agents, debateConfig: { debateStrength: 'deep' } },
    conversationState: { mode: 'debate', debateState: 'REBUTTAL', selectedTopic: 'AI 규제', debateSessionId: 'd-1', turnIndex: 2 },
  });

  assert.equal(payload.mode, 'debate');
  assert.deepEqual(payload.debateConfig, { debateStrength: 'deep' });
  assert.equal(payload.debateStrength, 'deep');
  assert.equal(payload.debateState, 'REBUTTAL');
  assert.equal(payload.selectedTopic, 'AI 규제');
  assert.equal(payload.debateSessionId, 'd-1');
  assert.equal(payload.turnIndex, 2);
});

test('다른 모드에서 캡처한 상태는 버린다', () => {
  const payload = payloadFor({
    room: { learningMode: 'debate', agents },
    conversationState: { mode: 'simulation', scenarioId: 'x', turnIndex: 5 },
  });

  assert.equal(payload.turnIndex, undefined);
  assert.equal(payload.scenarioId, undefined);
  assert.deepEqual(payload.debateConfig, { debateStrength: 'normal' });
});

test('상황극 선택지는 이번 요청에 싣고 다음 턴 이전 선택으로 옮긴다', () => {
  const room = { learningMode: 'simulation', agents, simulationConfig: { scenarioType: 'interview', difficulty: 'hard', choiceCount: '4' } };
  const chosen = selectSimulationChoice({ mode: 'simulation', scenarioId: 'sc-1', turnIndex: 0 }, { choiceId: 'B', label: 'B' });
  const payload = payloadFor({ room, conversationState: chosen });

  assert.deepEqual(payload.simulationConfig, { scenarioType: 'interview', difficulty: 'hard', choiceCount: 4 });
  assert.deepEqual(payload.selectedChoice, { choiceId: 'B', label: 'B' });
  assert.equal(payload.scenarioId, 'sc-1');

  const next = consumeSimulationChoice(chosen, 'simulation');
  assert.equal(next.selectedChoice, null);
  assert.deepEqual(next.previousChoices, [{ choiceId: 'B', label: 'B' }]);
  assert.equal(next.turnIndex, 1);
});

test('한 교수를 멘션하면 그 교수만 대상으로 지정한다', () => {
  const payload = payloadFor({ message: '@쉬운 풀이 튜터 설명해줘' });

  assert.equal(payload.askScope, 'single');
  assert.equal(payload.targetAgentId, '102');
  assert.equal(payload.targetAgentIndex, 1);
  assert.equal(payload.targetAgentName, '쉬운 풀이 튜터');
  assert.equal(payload.targetProfessorRole, 'book');
  assert.equal(payload.targetAgentKey, 'agent2');
});

test('@모두 는 전체 대상이다', () => {
  const payload = payloadFor({ message: '@모두 @쉬운 풀이 튜터 설명해줘' });
  assert.equal(payload.askScope, undefined);
  assert.equal(payload.targetAgentId, undefined);
});

test('같은 질문을 다시 보내면 재생성 시도 횟수를 올린다', () => {
  assert.equal(nextRegenerateAttempt(null, 'q'), 1);
  assert.equal(nextRegenerateAttempt({ question: 'q', attempt: 1 }, 'q'), 2);
  assert.equal(nextRegenerateAttempt({ question: 'q', attempt: 3 }, 'other'), 1);
  assert.equal(payloadFor({ attempt: 2 }).forceRegenerate, true);
});

test('SSE 이벤트의 멀티턴 상태를 camelCase/snake_case 모두 캡처한다', () => {
  const first = captureConversationState({}, { debate_state: 'OPENING', selected_topic: 'T', turn_index: 1 }, 'debate');
  const second = captureConversationState(first, { simulationState: { sessionId: 'sim-9' }, scenarioId: '', turnIndex: 2 }, 'debate');

  assert.equal(second.mode, 'debate');
  assert.equal(second.debateState, 'OPENING');
  assert.equal(second.selectedTopic, 'T');
  assert.equal(second.sessionId, 'sim-9');
  assert.equal(second.turnIndex, 2);
  assert.equal('scenarioId' in second, false);
});

test('질문 정제는 공백만 정리하고 내용은 보존한다', () => {
  assert.equal(sanitizeQuestion('  ls -al  \n\n\n\n```code```  '), 'ls -al\n\n```code```');
});
