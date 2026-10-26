import test from 'node:test';
import assert from 'node:assert/strict';
import {
  appendLiveChatMessage,
  latestServerId,
  mergeChatHistories,
  reconcileChatWithHistory,
  toLiveChatMessage,
} from '../screens/groupstudy/chatMessageModel.js';
import { splitChatHistory } from '../screens/groupstudy/groupStudyModel.js';

function historyMessage(id, senderId, content) {
  return { id: `history-${id}`, serverId: String(id), senderId, senderName: `user-${senderId}`, content };
}

test('서버 id가 있는 실시간 메시지는 두 번 도착해도 한 번만 쌓인다', () => {
  const first = toLiveChatMessage({ id: 11, senderId: '7', content: '안녕' }, 1);
  const duplicate = toLiveChatMessage({ id: 11, senderId: '7', content: '안녕' }, 2);

  const messages = appendLiveChatMessage(appendLiveChatMessage([], first), duplicate);
  assert.equal(messages.length, 1);
  assert.equal(messages[0].id, 'server-11');
});

test('서버 id가 없는 실시간 메시지는 순번 id를 받아 모두 보존된다', () => {
  const first = toLiveChatMessage({ senderId: '7', content: 'ㅋㅋ' }, 1);
  const second = toLiveChatMessage({ senderId: '7', content: 'ㅋㅋ' }, 2);

  const messages = appendLiveChatMessage(appendLiveChatMessage([], first), second);
  assert.deepEqual(messages.map((message) => message.id), ['live-1', 'live-2']);
});

test('재연결 후 받은 이력과 기존 이력은 서버 id 기준으로 합치고 정렬한다', () => {
  const initial = [historyMessage(1, '7', 'a'), historyMessage(2, '8', 'b')];
  const recovered = [historyMessage(2, '8', 'b'), historyMessage(3, '7', 'c'), historyMessage(4, '8', 'd')];

  assert.deepEqual(
    mergeChatHistories(initial, recovered).map((message) => message.serverId),
    ['1', '2', '3', '4']
  );
});

test('이력에 이미 있는 실시간 메시지는 id로 제거하고, 놓친 메시지는 이력에서 채운다', () => {
  const history = [historyMessage(1, '7', 'a'), historyMessage(2, '8', 'missed'), historyMessage(3, '7', 'c')];
  const live = [toLiveChatMessage({ id: 3, senderId: '7', content: 'c' }, 1), toLiveChatMessage({ id: 4, senderId: '8', content: 'd' }, 2)];

  assert.deepEqual(
    reconcileChatWithHistory(history, live).map((message) => message.content),
    ['a', 'missed', 'c', 'd']
  );
});

test('id가 없는 실시간 메시지는 초기 이력 이후에 저장된 같은 내용과만 짝지어 제거한다', () => {
  const initialHistory = [historyMessage(1, '7', 'ㅇㅋ')];
  const recovered = [historyMessage(1, '7', 'ㅇㅋ'), historyMessage(2, '7', 'ㅇㅋ'), historyMessage(3, '8', '놓친 말')];
  const live = [toLiveChatMessage({ senderId: '7', content: 'ㅇㅋ' }, 1)];

  const merged = mergeChatHistories(initialHistory, recovered);
  const timeline = reconcileChatWithHistory(merged, live, { baselineServerId: latestServerId(initialHistory) });

  assert.deepEqual(timeline.map((message) => message.id), ['history-1', 'history-2', 'history-3']);
});

test('아직 이력에 저장되지 않은 실시간 메시지는 이력 뒤에 남는다', () => {
  const history = [historyMessage(1, '7', 'a')];
  const live = [toLiveChatMessage({ senderId: '8', content: '방금 보낸 말' }, 1)];

  const timeline = reconcileChatWithHistory(history, live, { baselineServerId: '1' });
  assert.deepEqual(timeline.map((message) => message.content), ['a', '방금 보낸 말']);
});

test('채팅 이력 항목은 서버 id를 문자열로 보존한다', () => {
  const { chat } = splitChatHistory([{ id: 42, senderId: '7', senderName: '나', content: 'hi' }], '7');
  assert.equal(chat[0].serverId, '42');
  assert.equal(latestServerId(chat), 42);
  assert.equal(latestServerId([]), null);
});
