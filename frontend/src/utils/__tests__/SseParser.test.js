// node --test frontend/src/utils/__tests__   (vitest/jest 미도입 — Node 내장 테스트 러너 사용)
import test from 'node:test';
import assert from 'node:assert/strict';
import { createSseParser } from '../sse/sseParser.js';

const collect = () => {
  const frames = [];
  const p = createSseParser((f) => frames.push(f));
  return { p, frames };
};

test('TCP chunk boundary inside a frame and inside a multibyte Korean char is reassembled', () => {
  const { p, frames } = collect();
  const full = 'event: agent_answer\ndata: {"content":"혼잡제어는 네트워크"}\n\n';
  const bytes = Buffer.from(full, 'utf8');
  // 바이트 단위로 쪼개 디코딩(TextDecoder stream:true 와 동일하게 문자 경계에서만 push)
  const dec = new TextDecoder();
  for (let i = 0; i < bytes.length; i += 7) {
    p.push(dec.decode(bytes.subarray(i, Math.min(i + 7, bytes.length)), { stream: true }));
  }
  p.push(dec.decode());
  p.flush();
  assert.equal(frames.length, 1);
  assert.equal(frames[0].event, 'agent_answer');
  assert.equal(JSON.parse(frames[0].data).content, '혼잡제어는 네트워크');
});

test('multi-line data is joined with newline (JSON with code block)', () => {
  const { p, frames } = collect();
  p.push('event: agent_answer\ndata: {"content":"line1\ndata: line2\ndata: ```js\ndata: x\ndata: ```"}\n\n');
  assert.equal(frames.length, 1);
  assert.equal(frames[0].data, '{"content":"line1\nline2\n```js\nx\n```"}');
});

test('CRLF and lone CR line endings are standard-normalized; comment frames are control only', () => {
  const { p, frames } = collect();
  p.push(':hb\r\n\r\nevent: heartbeat\r\ndata: {"a":1}\r\n\r\n');
  p.push(':hb\r\r');
  assert.equal(frames.length, 3);
  assert.equal(frames[0].control, true);
  assert.equal(frames[0].comment, 'hb');
  assert.equal(frames[0].event, null);
  assert.equal(frames[1].event, 'heartbeat');
  assert.equal(frames[2].control, true);
});

test('default event name is message; id/retry/unknown fields handled per spec; empty control frame', () => {
  const { p, frames } = collect();
  p.push('data: {"x":1}\n\n');
  p.push('id: 42\nretry: 3000\nfoo: bar\nevent: custom\ndata:no-space\n\n');
  p.push('event: only_name\n\n');
  assert.equal(frames[0].event, 'message');
  assert.equal(frames[1].event, 'custom');
  assert.equal(frames[1].data, 'no-space');
  assert.equal(frames[1].id, '42');
  assert.equal(p.lastEventId, '42');
  assert.equal(frames[2].control, true, 'data 없는 프레임은 메시지가 아니다');
});

test('trailing frame without terminating blank line is flushed at end of stream; BOM ignored', () => {
  const { p, frames } = collect();
  p.push('﻿event: done\ndata: {"status":"done"}');
  assert.equal(frames.length, 0, '종결 빈 줄 전에는 대기');
  p.flush();
  assert.equal(frames.length, 1);
  assert.equal(frames[0].event, 'done');
  assert.equal(p.pending, 0);
});

test('one malformed frame does not break the next frame', () => {
  const { p, frames } = collect();
  p.push('event: agent_answer\ndata: {not json\n\nevent: all_complete\ndata: {"ok":true}\n\n');
  assert.equal(frames.length, 2);
  assert.throws(() => JSON.parse(frames[0].data));
  assert.equal(JSON.parse(frames[1].data).ok, true);
});
