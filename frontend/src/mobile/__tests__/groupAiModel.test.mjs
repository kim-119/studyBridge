import test from 'node:test';
import assert from 'node:assert/strict';
import {
  applyGroupAiFrame,
  buildGroupAiRequestBody,
  captureConversationState,
} from '../screens/groupstudy/groupAiModel.js';

const REQUEST_ID = 'req-1';

function frame(parsed, event = 'message') {
  return { event, parsed };
}

test('요청 본문은 웹 그룹스터디 AI 계약과 같다', () => {
  const body = buildGroupAiRequestBody('TCP 설명해줘', { selectedTopic: '주제' });

  assert.equal(body.message, 'TCP 설명해줘');
  assert.equal(body.source, 'group_study');
  assert.equal(body.mode, 'multi_agent_discussion');
  assert.equal(body.learningMode, 'basic');
  assert.equal(body.rounds, 3);
  assert.equal(body.showFinalSynthesis, true);
  assert.deepEqual(body.agents, []);
  assert.equal(body.selectedTopic, '주제');
});

test('같은 에이전트의 조각은 한 말풍선으로 이어 붙인다', () => {
  let messages = [];
  messages = applyGroupAiFrame(messages, frame({ agentName: '튜터', content: '안' }), REQUEST_ID);
  messages = applyGroupAiFrame(messages, frame({ agentName: '검색봇', content: '결과' }), REQUEST_ID);
  messages = applyGroupAiFrame(messages, frame({ agentName: '튜터', content: '녕' }), REQUEST_ID);

  assert.deepEqual(
    messages.map((message) => [message.senderName, message.content]),
    [
      ['튜터', '안녕'],
      ['검색봇', '결과'],
    ]
  );
});

test('error 이벤트는 삼키지 않고 오류 말풍선으로 보여준다', () => {
  const messages = applyGroupAiFrame([], frame({ errorMessage: '지원하지 않는 AI 봇입니다.' }, 'error'), REQUEST_ID);

  assert.equal(messages.length, 1);
  assert.equal(messages[0].isError, true);
  assert.equal(messages[0].content, '지원하지 않는 AI 봇입니다.');
});

test('스트리밍 없이 all_complete 로만 온 답변도 표시한다', () => {
  const completed = frame({ replies: [{ agentName: 'AI 튜터', answer: '정리된 답변' }] }, 'all_complete');
  const messages = applyGroupAiFrame([], completed, REQUEST_ID);
  assert.deepEqual(messages.map((message) => message.content), ['정리된 답변']);

  const streamed = applyGroupAiFrame([], frame({ agentName: 'AI 튜터', content: '스트림' }), REQUEST_ID);
  assert.equal(applyGroupAiFrame(streamed, completed, REQUEST_ID).length, 1);
});

test('라우팅 안내와 토론 섹션을 처리한다', () => {
  let messages = applyGroupAiFrame([], frame({ type: 'route_notice', message: '학습 질문으로 답합니다.' }), REQUEST_ID);
  messages = applyGroupAiFrame(messages, frame({ type: 'debate_section', section: 'pro', items: [{ content: '찬성 근거' }] }), REQUEST_ID);
  messages = applyGroupAiFrame(messages, frame({ type: 'debate_section', section: 'debateSummary', content: '요약' }), REQUEST_ID);

  assert.equal(messages.length, 2);
  assert.equal(messages[0].isNotice, true);
  assert.equal(messages[1].content, '찬성 근거\n\n요약');
});

test('토론/상황극 진행 상태를 다음 요청에 되돌려 보낼 수 있게 저장한다', () => {
  const state = captureConversationState({}, { debate_state: { step: 2 }, turn_index: 3, scenarioId: '' });
  assert.deepEqual(state, { debateState: { step: 2 }, turnIndex: 3 });
});
