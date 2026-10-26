import test from 'node:test';
import assert from 'node:assert/strict';
import {
  flushEffects,
  importMobileModule,
  loadRenderer,
  renderElement,
  textOf,
} from './support/componentHarness.mjs';

const ROOM_ID = '5';
const ROOM_AGENTS = [
  { id: 11, agentId: 11, name: '개념 교수' },
  { id: 12, agentId: 12, name: '풀이 튜터' },
];
const FIRST_ANSWER = '### 핵심 정의\n**JDBC**는 자바 DB 연결 표준입니다.\n- `DriverManager` 로 연결';
const FINAL_ANSWER = '> 요약: **ORM**은 매핑을 자동화합니다.\n\n##정리\n1. 엔티티 정의\n2. **매핑** 설정\n---\n| 항목 | 설명 |\n|---|---|\n| JPA | 표준 |';
const RAW_MARKERS = ['**', '###', '##', '```', '|---'];

const { React, act } = await loadRenderer();
const { MemoryRouter, Route, Routes } = await import('react-router-dom');
const api = await importMobileModule('../services/api.js');
const { default: StudyMateChatScreen } = await importMobileModule('screens/studymate/StudyMateChatScreen.jsx');
const { default: MarkdownText } = await importMobileModule('components/MarkdownText.jsx');
const { default: ProfessorAnswerList } = await importMobileModule('screens/studymate/ProfessorAnswerList.jsx');
const { useProfessorStage } = await importMobileModule('screens/studymate/useProfessorStage.js');

const realFetch = globalThis.fetch;

function createControlledSseResponse() {
  const encoder = new TextEncoder();
  let controller;
  const body = new ReadableStream({
    start(streamController) {
      controller = streamController;
    },
  });
  return {
    response: { ok: true, status: 200, body, headers: { get: () => null } },
    push: (event, data) => controller.enqueue(encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`)),
    close: () => controller.close(),
  };
}

function installServer({ history = [] } = {}) {
  const server = { fetchCalls: [], stream: null };
  api.agentService.getAgents = async () => [
    { id: Number(ROOM_ID), roomId: Number(ROOM_ID), roomName: 'JDBC 스터디', learningMode: 'basic', agents: ROOM_AGENTS },
  ];
  api.agentService.getChatHistory = async () => history;
  globalThis.fetch = async (url, init) => {
    server.fetchCalls.push({ url: String(url), init });
    server.stream = createControlledSseResponse();
    return server.stream.response;
  };
  return server;
}

function restoreFetch() {
  globalThis.fetch = realFetch;
}

async function renderChatRoom() {
  const renderer = await renderElement(
    React.createElement(
      MemoryRouter,
      { initialEntries: [`/studymate/${ROOM_ID}`] },
      React.createElement(
        Routes,
        null,
        React.createElement(Route, { path: '/studymate/:roomId', element: React.createElement(StudyMateChatScreen) })
      )
    )
  );
  await flushEffects(5);
  return renderer;
}

async function submitQuestion(renderer, question) {
  const input = renderer.root.findByType('textarea');
  await act(async () => input.props.onChange({ target: { value: question } }));
  const form = renderer.root.findByType('form');
  await act(async () => form.props.onSubmit({ preventDefault() {} }));
  await flushEffects(5);
}

async function pushAndFlush(server, event, data) {
  await act(async () => server.stream.push(event, data));
  await flushEffects(5);
}

function screenText(renderer) {
  return textOf(renderer.toJSON());
}

function assertNoRawMarkdown(text, context) {
  RAW_MARKERS.forEach((marker) => assert.equal(text.includes(marker), false, `${context}: "${marker}" 노출`));
  assert.equal(/>\s?요약/.test(text), false, `${context}: 인용 기호 노출`);
}

function markdownRootsContaining(renderer, snippet) {
  return renderer.root.findAll(
    (instance) => instance.type === 'div' && instance.props.className === 'mobile-md' && textOf(instance.children).includes(snippet)
  );
}

function strongTexts(renderer) {
  return renderer.root.findAllByType('strong').map((instance) => textOf(instance.children));
}

test('T14 실제 SSE fetch 스트림의 청크마다 부분 답변이 완료 전에 먼저 렌더된다', async () => {
  const server = installServer();
  try {
    const renderer = await renderChatRoom();
    await submitQuestion(renderer, 'JDBC가 뭐야?');
    await submitQuestion(renderer, 'JDBC가 뭐야?');

    assert.equal(server.fetchCalls.length, 1, '같은 질문을 연속 전송해도 스트림은 하나만 연다');
    const [call] = server.fetchCalls;
    assert.ok(call.url.endsWith(`/api/agent-rooms/${ROOM_ID}/chat/stream`));
    assert.equal(call.init.method, 'POST');
    assert.equal(call.init.headers.Accept, 'text/event-stream');
    assert.equal(JSON.parse(call.init.body).message, 'JDBC가 뭐야?');

    await pushAndFlush(server, 'turn_start', { mode: 'basic' });
    await pushAndFlush(server, 'agent_start', { agentId: 11, agentIndex: 1, agentName: '개념 교수' });
    assert.ok(screenText(renderer).includes('답변 생성 중'));

    await pushAndFlush(server, 'agent_answer', { agentId: 11, agentIndex: 1, agentName: '개념 교수', content: FIRST_ANSWER });
    const partial = screenText(renderer);
    assert.ok(partial.includes('JDBC는 자바 DB 연결 표준입니다.'), '첫 교수 답변이 완료 전에 보인다');
    assert.ok(partial.includes('답변 작성 중'), '아직 스트림이 진행 중이다');
    assert.equal(partial.includes('ORM'), false, '두 번째 답변은 아직 도착하지 않았다');

    await pushAndFlush(server, 'agent_answer', { agentId: 12, agentIndex: 2, agentName: '풀이 튜터', content: FINAL_ANSWER });
    const secondPartial = screenText(renderer);
    assert.ok(secondPartial.includes('JDBC는 자바') && secondPartial.includes('ORM은 매핑을 자동화합니다.'));
    assert.ok(secondPartial.includes('답변 작성 중'));

    await pushAndFlush(server, 'all_complete', { status: 'SUCCESS' });
    await pushAndFlush(server, 'done', { status: 'success' });
    await act(async () => server.stream.close());
    await flushEffects(10);

    const final = screenText(renderer);
    assert.equal(final.includes('답변 작성 중'), false, '완료 후에는 스트리밍 표시가 사라진다');
    assert.ok(final.includes('JDBC는 자바') && final.includes('ORM은 매핑을 자동화합니다.'));
    assert.equal(server.fetchCalls.length, 1);
    await act(async () => renderer.unmount());
  } finally {
    restoreFetch();
  }
});

test('T15 스트리밍 부분 답변과 최종 답변, 기록 재로딩 답변, 교수 답변 목록이 같은 MarkdownText 로 렌더된다', async () => {
  const server = installServer({
    history: [
      { id: 1, sender: 'USER', content: '이전 질문' },
      { id: 2, sender: 'AI', senderName: '개념 교수', agentId: 11, content: '## 기록 제목\n**기록 강조** 내용' },
    ],
  });
  try {
    const renderer = await renderChatRoom();
    assert.equal(markdownRootsContaining(renderer, '기록 강조 내용').length, 1, '기록 재로딩 답변');

    await submitQuestion(renderer, 'ORM 은?');
    await pushAndFlush(server, 'agent_answer', { agentId: 11, agentIndex: 1, agentName: '개념 교수', content: FIRST_ANSWER });
    assert.equal(markdownRootsContaining(renderer, 'JDBC는 자바').length, 1, '부분 답변');

    await pushAndFlush(server, 'agent_answer', { agentId: 12, agentIndex: 2, agentName: '풀이 튜터', content: FINAL_ANSWER });
    await pushAndFlush(server, 'all_complete', { status: 'SUCCESS' });
    await act(async () => server.stream.close());
    await flushEffects(10);

    assert.equal(markdownRootsContaining(renderer, 'ORM은 매핑을 자동화합니다.').length, 1, '최종 답변');
    assert.ok(strongTexts(renderer).includes('ORM'));
    assert.ok(strongTexts(renderer).includes('기록 강조'));
    await act(async () => renderer.unmount());
  } finally {
    restoreFetch();
  }

  const answers = await renderElement(
    React.createElement(ProfessorAnswerList, {
      roomAgents: ROOM_AGENTS,
      messages: [
        { id: 'u', sender: 'USER', content: '질문' },
        { id: 'a', sender: 'AI', senderName: '풀이 튜터', agentId: 12, parentId: 'u', content: FINAL_ANSWER },
      ],
    })
  );
  assert.equal(markdownRootsContaining(answers, 'ORM은 매핑을 자동화합니다.').length, 1, '교수 답변 목록');
});

test('T16 부분 답변과 최종 답변 화면에 **, ###, 인용, 표 구분선 같은 원시 마크다운이 남지 않는다', async () => {
  const server = installServer();
  try {
    const renderer = await renderChatRoom();
    await submitQuestion(renderer, 'JDBC 정리해줘');

    await pushAndFlush(server, 'agent_answer', { agentId: 11, agentIndex: 1, agentName: '개념 교수', content: FIRST_ANSWER });
    assertNoRawMarkdown(screenText(renderer), '부분 답변');

    await pushAndFlush(server, 'agent_answer', {
      agentId: 12,
      agentIndex: 2,
      agentName: '풀이 튜터',
      actType: 'WRAP',
      content: FINAL_ANSWER,
    });
    await pushAndFlush(server, 'all_complete', { status: 'SUCCESS' });
    await act(async () => server.stream.close());
    await flushEffects(10);
    assertNoRawMarkdown(screenText(renderer), '최종 답변');
    await act(async () => renderer.unmount());
  } finally {
    restoreFetch();
  }
});

test('T16 마크다운 렌더러는 제목·인용·번호 목록·구분선·표·굵게 속 기호를 원시 문자 없이 보여준다', async () => {
  const source = [
    '###핵심 개념',
    '> **주의**: 인용문',
    '1) 첫째 **C++ 포인터**',
    '2) 둘째 `HTTP/1.1`',
    '***',
    '| 개념 | 예 |',
    '| --- | --- |',
    '| C# | .NET |',
    '**끝나지 않은 굵게',
    '## C#',
    '#include 는 제목이 아니다',
  ].join('\n');
  const renderer = await renderElement(React.createElement(MarkdownText, null, source));
  const text = textOf(renderer.toJSON());

  ['**', '###', '> ', '---', '|'].forEach((marker) => assert.equal(text.includes(marker), false, marker));
  ['핵심 개념', '주의: 인용문', 'C++ 포인터', 'HTTP/1.1', 'C# · .NET', '끝나지 않은 굵게', 'C#', '#include 는 제목이 아니다'].forEach(
    (expected) => assert.ok(text.includes(expected), expected)
  );
  assert.equal(renderer.root.findAllByType('blockquote').length, 1);
  assert.equal(renderer.root.findByType('ol').props.start, 1);
});

test('T16 교수 말풍선과 상세 패널 문구도 마크다운 기호 없이 표시된다', async () => {
  let stage = null;
  function StageProbe() {
    stage = useProfessorStage(ROOM_AGENTS);
    return null;
  }
  const renderer = await renderElement(React.createElement(StageProbe));
  await act(async () => {
    stage.showAnswer({ slot: 0, data: { agentName: '개념 교수', content: FIRST_ANSWER }, isForTarget: true });
  });

  const bubble = Object.values(stage.bubbles).find(Boolean);
  assert.ok(bubble.text.includes('JDBC는 자바'));
  assertNoRawMarkdown(bubble.text, '말풍선');
  assertNoRawMarkdown(bubble.fullText, '상세 패널');
  await act(async () => renderer.unmount());
});
