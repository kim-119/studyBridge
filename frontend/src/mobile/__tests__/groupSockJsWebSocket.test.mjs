import test from 'node:test';
import assert from 'node:assert/strict';
import {
  SOCKJS_FRAME,
  SockJsWebSocket,
  encodeSockJsMessage,
  parseSockJsFrame,
  sockJsWebSocketUrl,
} from '../screens/groupstudy/sockJsWebSocket.js';

test('SockJS 엔드포인트를 info 요청 없이 쓰는 websocket 전송 URL 로 바꾼다', () => {
  assert.equal(
    sockJsWebSocketUrl('https://studybridge.co.kr/ws-group', '123', 'abcd1234'),
    'wss://studybridge.co.kr/ws-group/123/abcd1234/websocket'
  );
  assert.equal(sockJsWebSocketUrl('http://localhost:8080/ws-group/', '001', 's'), 'ws://localhost:8080/ws-group/001/s/websocket');
});

test('SockJS 프레임을 종류별로 해석한다', () => {
  assert.deepEqual(parseSockJsFrame('o'), { type: SOCKJS_FRAME.OPEN });
  assert.deepEqual(parseSockJsFrame('h'), { type: SOCKJS_FRAME.HEARTBEAT });
  assert.deepEqual(parseSockJsFrame('a["CONNECTED\\n\\n\\u0000","MESSAGE"]'), {
    type: SOCKJS_FRAME.MESSAGES,
    messages: ['CONNECTED\n\n\u0000', 'MESSAGE'],
  });
  assert.deepEqual(parseSockJsFrame('m"single"'), { type: SOCKJS_FRAME.MESSAGES, messages: ['single'] });
  assert.deepEqual(parseSockJsFrame('c[3000,"Go away!"]'), { type: SOCKJS_FRAME.CLOSE, code: 3000, reason: 'Go away!' });
  assert.deepEqual(parseSockJsFrame('a[broken'), { type: SOCKJS_FRAME.UNKNOWN });
});

test('보내는 STOMP 프레임은 SockJS 배열로 감싼다', () => {
  assert.equal(encodeSockJsMessage('SEND\n\n\u0000'), '["SEND\\n\\n\\u0000"]');
});

class FakeWebSocket {
  constructor(url) {
    this.url = url;
    this.sent = [];
    this.closed = false;
  }

  send(data) {
    this.sent.push(data);
  }

  close() {
    this.closed = true;
    this.onclose?.({ code: 1000 });
  }
}

test('open 전에는 전송하지 않고, heartbeat 를 활동으로 알리며, 메시지를 STOMP 로 넘긴다', () => {
  let activity = 0;
  const received = [];
  const opened = [];
  const socket = new SockJsWebSocket('wss://host/ws-group/1/s/websocket', {
    onActivity: () => {
      activity += 1;
    },
    WebSocketImpl: FakeWebSocket,
  });
  socket.onopen = () => opened.push(true);
  socket.onmessage = (event) => received.push(event.data);

  socket.send('too early');
  assert.deepEqual(socket.socket.sent, []);

  socket.socket.onmessage({ data: 'o' });
  socket.socket.onmessage({ data: 'h' });
  socket.socket.onmessage({ data: 'a["MESSAGE one","MESSAGE two"]' });
  socket.send('CONNECT');

  assert.equal(opened.length, 1);
  assert.equal(activity, 3);
  assert.deepEqual(received, ['MESSAGE one', 'MESSAGE two']);
  assert.deepEqual(socket.socket.sent, ['["CONNECT"]']);
});

test('서버 close 프레임을 받으면 연결을 닫고 onclose 를 한 번 알린다', () => {
  const closes = [];
  const socket = new SockJsWebSocket('wss://host/x', { WebSocketImpl: FakeWebSocket });
  socket.onclose = (event) => closes.push(event.code);

  socket.socket.onmessage({ data: 'o' });
  socket.socket.onmessage({ data: 'c[3000,"Go away!"]' });

  assert.equal(socket.readyState, 3);
  assert.deepEqual(closes, [1000]);
});
