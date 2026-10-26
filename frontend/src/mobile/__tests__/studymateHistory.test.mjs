import test from 'node:test';
import assert from 'node:assert/strict';
import {
  historyToMessages,
  isUserMessage,
  mindmapSourceMessages,
  reconcileHistory,
  removeFailedTurn,
} from '../screens/studymate/chatMessages.js';

test('서버가 보내는 대문자 sender USER 를 사용자 메시지로 인식한다', () => {
  const messages = historyToMessages([
    { id: 1, sender: 'USER', content: '큐와 스택 차이?', createdAt: '2026-09-01T10:00:00' },
    { id: 2, sender: 'AI', senderName: '개념 정리 교수', agentId: 11, content: '큐는 FIFO 입니다.' },
  ]);

  assert.equal(messages.length, 2);
  assert.equal(isUserMessage(messages[0]), true);
  assert.equal(messages[0].content, '큐와 스택 차이?');
  assert.equal(isUserMessage(messages[1]), false);
  assert.equal(messages[1].senderName, '개념 정리 교수');
  assert.equal(messages[1].agentId, 11);
});

test('소문자 user 도 사용자 메시지로 본다', () => {
  const [message] = historyToMessages([{ id: 1, sender: 'user', content: 'hi' }]);
  assert.equal(isUserMessage(message), true);
  assert.equal(message.sender, 'USER');
});

test('messages 로 감싼 응답도 받는다', () => {
  const messages = historyToMessages({ messages: [{ id: 1, sender: 'USER', content: 'q' }] });
  assert.equal(messages.length, 1);
});

test('다음 질문 뒤에 저장된 답변은 자기 질문 뒤로 옮긴다', () => {
  const messages = historyToMessages([
    { id: 1, sender: 'USER', content: 'q1', requestId: 'r1' },
    { id: 2, sender: 'USER', content: 'q2', requestId: 'r2' },
    { id: 3, sender: 'AI', senderName: 'A', content: 'a1', requestId: 'r1' },
  ]);

  assert.deepEqual(messages.map((message) => message.content), ['q1', 'a1', 'q2']);
});

test('토론 단계가 저장된 턴은 구조화 말풍선 하나로 복원한다', () => {
  const debateStages = [
    { stageType: 'OPENING_STATEMENT', side: 'PRO', agentName: 'A', content: '찬성' },
    { stageType: 'REBUTTAL', side: 'CON', agentName: 'B', content: '반박' },
  ];
  const messages = historyToMessages([
    { id: 1, sender: 'USER', content: '논제', requestId: 'r1' },
    { id: 2, sender: 'AI', senderName: 'A', content: '찬성', requestId: 'r1', processSteps: { debateStages } },
    { id: 3, sender: 'AI', senderName: 'B', content: '반박', requestId: 'r1', processSteps: { debateStages } },
  ]);

  assert.equal(messages.length, 2);
  assert.equal(messages[1].turnKind, 'debate');
  assert.equal(messages[1].stages.length, 2);
  assert.equal(messages[1].stages[0].title, '찬성측 입론');
});

test('기본 모드 processSteps 는 1차 답변 말풍선으로 펼친다', () => {
  const processSteps = {
    initialAnswers: [
      { agentIndex: 2, agentName: 'B', answer: '두 번째' },
      { agentIndex: 1, agentName: 'A', answer: '첫 번째' },
    ],
    validatedAnswers: [{ agentIndex: 1, agentName: 'A', answer: '검증' }],
  };
  const messages = historyToMessages([
    { id: 1, sender: 'USER', content: 'q', requestId: 'r1' },
    { id: 2, sender: 'AI', senderName: 'A', content: 'x', requestId: 'r1', processSteps },
  ]);

  assert.deepEqual(messages.slice(1).map((message) => message.content), ['첫 번째', '두 번째']);
});

test('마인드맵 입력에서는 구조화 턴과 안내 메시지를 뺀다', () => {
  const source = mindmapSourceMessages([
    { id: 1, sender: 'USER', content: 'q' },
    { id: 2, sender: 'AI', content: 'a' },
    { id: 3, sender: 'AI', content: '토론', turnKind: 'debate', stages: [] },
    { id: 4, sender: 'AI', content: '끊김', isNotice: true, isError: true },
  ]);

  assert.deepEqual(source.map((message) => message.id), [1, 2]);
});

test('서버 기록이 더 짧으면 로컬 기록을 유지한다', () => {
  const local = [{ id: 'a' }, { id: 'b' }];
  const server = [{ id: 'a' }];
  assert.equal(reconcileHistory(server, local), local);
  assert.equal(reconcileHistory([...local, { id: 'c' }], local).length, 3);
});

test('다시 시도는 실패 안내와 답변 없던 질문을 지운다', () => {
  const notice = { id: 'r1::stream-notice', parentId: 'r1::notice', sender: 'AI', isNotice: true, isError: true };
  const remaining = removeFailedTurn([{ id: 'r1', sender: 'USER', content: 'q' }, notice], notice);
  assert.deepEqual(remaining, []);
});
