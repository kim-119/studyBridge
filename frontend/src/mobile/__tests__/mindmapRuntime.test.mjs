import test from 'node:test';
import assert from 'node:assert/strict';
import { flushEffects, importMobileModule, loadRenderer, textOf } from './support/componentHarness.mjs';

globalThis.ResizeObserver = class {
  observe() {}
  disconnect() {}
};

const ROOM_ID = 9;
const ROOM_AGENTS = [
  { id: 21, name: '개념 정리 교수', role: 'theory' },
  { id: 22, name: '쉬운 풀이 튜터', role: 'book' },
  { id: 23, name: '논점 검증 코치', role: 'ai' },
];
const ROOM_HISTORY = [
  { id: 100, sender: 'USER', content: 'JDBC가 뭐야?', requestId: 'r1' },
  { id: 101, sender: 'AI', senderName: '개념 정리 교수', agentId: 21, requestId: 'r1', content: 'JDBC 는 자바 DB 연결 표준입니다.' },
  { id: 102, sender: 'AI', senderName: '쉬운 풀이 튜터', agentId: 22, requestId: 'r1', content: '드라이버로 SQL 을 보냅니다.' },
  { id: 103, sender: 'USER', content: 'ORM 과 비교하면?', requestId: 'r2' },
  { id: 104, sender: 'AI', senderName: '개념 정리 교수', agentId: 21, requestId: 'r2', actType: 'DIRECT_ANSWER', content: 'ORM 은 객체와 테이블을 자동으로 매핑합니다.' },
  { id: 105, sender: 'AI', senderName: '쉬운 풀이 튜터', agentId: 22, requestId: 'r2', actType: 'REACTION', replyTo: 21, content: '보충: JPA 가 대표 구현입니다.' },
  { id: 106, sender: 'AI', senderName: '논점 검증 코치', agentId: 23, requestId: 'r2', actType: 'DIRECT_ANSWER', content: 'ORM 도 내부적으로 JDBC 를 씁니다.' },
  { id: 107, sender: 'AI', senderName: '정리', agentId: 23, requestId: 'r2', actType: 'WRAP', content: '### 정리\n- 자동으로 쓰는 답변' },
];
const SEMANTIC_RESPONSE = {
  status: 'OK',
  concepts: [
    { id: 'c1', label: '**JDBC**', level: 0 },
    { id: 'c2', label: '### ORM', level: 1, parentId: 'c1' },
    { id: 'c3', label: '`SQL`', level: 1, parentId: 'c1' },
    { id: 'c4', label: '- JPA', level: 2, parentId: 'c2' },
    { id: 'c5', label: 'C++', level: 2, parentId: 'c3' },
  ],
  relations: [
    { from: 'c2', to: 'c1', label: '내부적으로 사용', type: 'USES' },
    { from: 'c4', to: 'c2', label: '표준 구현', type: 'IMPLEMENTS' },
  ],
  sources: [],
  provenance: [],
};
const GARBAGE_LABELS = ['자동으로', '쓰는', 'JDBC가', 'ORM의', '정리'];

const { React, TestRenderer, act } = await loadRenderer();
const { MemoryRouter } = await import('react-router-dom');
const api = await importMobileModule('../services/api.js');
const { clearSemanticMindmapCache } = await importMobileModule('../hooks/useSemanticMindmap.js');
const { buildSemanticAnswers } = await importMobileModule('../utils/graph/semanticGraphMerge.js');
const { historyToMessages, mindmapSourceMessages, latestUserQuestion } = await importMobileModule(
  'screens/studymate/chatMessages.js'
);
const { cleanNodeLabel } = await importMobileModule('screens/mindmap/nodeLabel.js');
const { default: RoomMindmapTab } = await importMobileModule('screens/studymate/RoomMindmapTab.jsx');
const { default: MindmapScreen } = await importMobileModule('screens/mindmap/MindmapScreen.jsx');
const { default: MoreScreen } = await importMobileModule('screens/MoreScreen.jsx');

function createNodeMock() {
  return { getBoundingClientRect: () => ({ left: 0, top: 0, width: 360, height: 480 }), focus() {}, style: {} };
}

async function render(element) {
  let renderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(MemoryRouter, null, element), { createNodeMock });
  });
  await flushEffects(5);
  return renderer;
}

function installSemanticServer(response = SEMANTIC_RESPONSE) {
  clearSemanticMindmapCache();
  const requests = [];
  api.mindmapService.getSemanticGraph = async (payload) => {
    requests.push(payload);
    return response;
  };
  return requests;
}

async function renderRoomMindmap() {
  const messages = historyToMessages(ROOM_HISTORY);
  return render(React.createElement(RoomMindmapTab, { roomId: ROOM_ID, roomAgents: ROOM_AGENTS, messages, interactions: [] }));
}

function nodeGroups(renderer) {
  return renderer.root.findAll((instance) => instance.type === 'g' && instance.props['data-node-id'] != null);
}

function nodeGroupByLabel(renderer, label) {
  return nodeGroups(renderer).find((group) => textOf(group.children) === label);
}

function emphasisByNodeLabel(renderer) {
  return Object.fromEntries(nodeGroups(renderer).map((group) => [textOf(group.children), group.props['data-node-emphasis']]));
}

function edgeLines(renderer) {
  return renderer.root.findAll((instance) => instance.type === 'line' && instance.props['data-edge-id'] != null);
}

function canvas(renderer) {
  return renderer.root.find((instance) => instance.type === 'svg' && instance.props.className === 'mobile-mindmap__canvas');
}

async function tapNode(renderer, label) {
  await act(async () => nodeGroupByLabel(renderer, label).props.onClick({ stopPropagation() {} }));
}

function touch(x, y) {
  return { touches: [{ clientX: x, clientY: y }] };
}

test('T17 마인드맵 노드는 semantic-graph API 응답의 개념만 쓰고 답변 토큰 노드는 만들지 않는다', async () => {
  const requests = installSemanticServer();
  const renderer = await renderRoomMindmap();

  assert.equal(requests.length, 1);
  const labels = nodeGroups(renderer).map((group) => textOf(group.children));
  ['JDBC', 'ORM', 'SQL', 'JPA', 'C++'].forEach((label) => assert.ok(labels.includes(label), label));
  GARBAGE_LABELS.forEach((label) => assert.equal(labels.includes(label), false, label));
  const conceptNodes = nodeGroups(renderer).filter((group) => String(group.props['data-node-id']).startsWith('concept-'));
  assert.equal(conceptNodes.length, SEMANTIC_RESPONSE.concepts.length);
});

test('T17 semantic-graph 실패 시 예전 토큰 그래프 없이 실패 상태만 보여준다', async () => {
  clearSemanticMindmapCache();
  api.mindmapService.getSemanticGraph = async () => {
    const error = new Error('bad gateway');
    error.response = { status: 502, data: { code: 'INTERNAL_ERROR' } };
    throw error;
  };
  const renderer = await renderRoomMindmap();

  const conceptNodes = nodeGroups(renderer).filter((group) => String(group.props['data-node-id']).startsWith('concept-'));
  assert.equal(conceptNodes.length, 0);
  assert.ok(textOf(renderer.toJSON()).includes('개념 구조를 생성하지 못했습니다'));
  GARBAGE_LABELS.slice(0, 2).forEach((label) =>
    assert.equal(nodeGroups(renderer).some((group) => textOf(group.children) === label), false, label)
  );
});

test('모바일 방 마인드맵 요청 payload 는 같은 방 기록에 대해 웹과 같은 질문과 답변 목록을 보낸다', async () => {
  const requests = installSemanticServer();
  await renderRoomMindmap();

  const webAnswers = buildSemanticAnswers(ROOM_HISTORY, ROOM_AGENTS);
  const mobileMessages = mindmapSourceMessages(historyToMessages(ROOM_HISTORY));
  const [request] = requests;

  assert.equal(request.roomId, ROOM_ID);
  assert.equal(request.question, 'ORM 과 비교하면?');
  assert.equal(request.question, latestUserQuestion(historyToMessages(ROOM_HISTORY)));
  assert.deepEqual(request.answers, webAnswers);
  assert.deepEqual(buildSemanticAnswers(mobileMessages, ROOM_AGENTS), webAnswers);
  assert.deepEqual(
    request.answers.map((answer) => [answer.messageId, answer.agentId, answer.agentName]),
    [
      [101, 21, '개념 정리 교수'],
      [102, 22, '쉬운 풀이 튜터'],
      [104, 21, '개념 정리 교수'],
      [106, 23, '논점 검증 코치'],
    ]
  );
  assert.equal(request.answers[2].content, ROOM_HISTORY[4].content);
});

test('T18 노드를 탭하면 선택되고 선택 카드가 열린다', async () => {
  installSemanticServer();
  const renderer = await renderRoomMindmap();

  await tapNode(renderer, 'ORM');
  assert.equal(emphasisByNodeLabel(renderer).ORM, 'selected');
  const card = renderer.root.find((instance) => instance.props['data-selected-node'] != null);
  assert.equal(textOf(card.findByType('h3').children), 'ORM');
});

test('T19 선택한 노드와 연결된 노드만 강조되고 나머지는 흐려진다', async () => {
  installSemanticServer();
  const renderer = await renderRoomMindmap();

  await tapNode(renderer, 'ORM');
  const emphasis = emphasisByNodeLabel(renderer);
  assert.equal(emphasis.JDBC, 'connected');
  assert.equal(emphasis.JPA, 'connected');
  assert.equal(emphasis.SQL, 'dimmed');
  assert.equal(emphasis['C++'], 'dimmed');
});

test('T20 선택 노드에 연결된 간선만 강조되고 더 두껍게 그려진다', async () => {
  installSemanticServer();
  const renderer = await renderRoomMindmap();

  await tapNode(renderer, 'ORM');
  const ormId = nodeGroupByLabel(renderer, 'ORM').props['data-node-id'];
  const lines = edgeLines(renderer);
  const connected = lines.filter((line) => line.props['data-edge-emphasis'] === 'connected');
  const dimmed = lines.filter((line) => line.props['data-edge-emphasis'] === 'dimmed');

  assert.ok(connected.length >= 2);
  connected.forEach((line) => {
    assert.ok(line.props['data-edge-id'].includes(ormId));
    assert.ok(line.props.style.strokeWidth > 2);
  });
  assert.ok(dimmed.length > 0);
  dimmed.forEach((line) => {
    assert.equal(line.props['data-edge-id'].includes(ormId), false);
    assert.ok(line.props.style.strokeWidth < connected[0].props.style.strokeWidth);
  });
});

test('T21 선택 카드는 서버 관계 라벨과 방향을 그대로 보여준다', async () => {
  installSemanticServer();
  const renderer = await renderRoomMindmap();

  await tapNode(renderer, 'ORM');
  const card = renderer.root.find((instance) => instance.props['data-selected-node'] != null);
  const relationText = textOf(card.children);

  assert.ok(relationText.includes('ORM → [내부적으로 사용] JDBC'), relationText);
  assert.ok(relationText.includes('JPA → [표준 구현] ORM'), relationText);
  assert.equal(relationText.includes('JDBC → [포함 개념] ORM'), false, '서버 관계를 포함 개념으로 덮지 않는다');
  assert.equal(relationText.includes('ORM → [포함 개념] JPA'), false);
});

test('T22 빈 공간을 탭하거나 선택 해제를 누르면 강조가 모두 풀린다', async () => {
  installSemanticServer();
  const renderer = await renderRoomMindmap();

  await tapNode(renderer, 'ORM');
  await act(async () => canvas(renderer).props.onClick({}));
  assert.ok(Object.values(emphasisByNodeLabel(renderer)).every((value) => value === 'normal'));
  assert.ok(edgeLines(renderer).every((line) => line.props['data-edge-emphasis'] === 'normal'));

  await tapNode(renderer, 'JDBC');
  const clear = renderer.root.find((instance) => instance.type === 'button' && textOf(instance.children) === '선택 해제');
  await act(async () => clear.props.onClick({}));
  assert.ok(Object.values(emphasisByNodeLabel(renderer)).every((value) => value === 'normal'));
});

test('T18 안드로이드 터치: 짧은 탭은 선택하고 끌기(팬) 뒤의 click 은 선택으로 보지 않는다', async () => {
  installSemanticServer();
  const renderer = await renderRoomMindmap();
  const svg = () => canvas(renderer);

  await act(async () => svg().props.onTouchStart(touch(100, 100)));
  await act(async () => svg().props.onTouchMove(touch(160, 140)));
  await act(async () => svg().props.onTouchEnd({ touches: [] }));
  await tapNode(renderer, 'ORM');
  assert.equal(emphasisByNodeLabel(renderer).ORM, 'normal', '팬 제스처 뒤 click 은 무시');

  await act(async () => svg().props.onTouchStart(touch(100, 100)));
  await act(async () => svg().props.onTouchMove(touch(103, 102)));
  await act(async () => svg().props.onTouchEnd({ touches: [] }));
  await tapNode(renderer, 'ORM');
  assert.equal(emphasisByNodeLabel(renderer).ORM, 'selected', '손떨림 수준 이동은 탭');

  const hitCircle = nodeGroupByLabel(renderer, 'ORM').findAll((instance) => instance.props.className === 'mobile-mindmap__hit');
  assert.equal(hitCircle.length, 1);
  assert.ok(hitCircle[0].props.r >= 22);
});

test('마인드맵 라벨 정리는 표시용 마크다운만 걷어내고 기술 용어는 보존한다', () => {
  const preserved = ['C++', 'C#', '.NET', 'HTTP/1.1', 'SQL', 'JDBC', 'A/B', 'β-amyloid', 'A/B 테스트', 'Node.js'];
  preserved.forEach((label) => assert.equal(cleanNodeLabel(label), label, label));

  assert.equal(cleanNodeLabel('**C++**'), 'C++');
  assert.equal(cleanNodeLabel('### C#'), 'C#');
  assert.equal(cleanNodeLabel('`.NET`'), '.NET');
  assert.equal(cleanNodeLabel('- HTTP/1.1'), 'HTTP/1.1');
  assert.equal(cleanNodeLabel('> **JDBC** 드라이버'), 'JDBC 드라이버');
  assert.equal(cleanNodeLabel('1. SQL 조인'), 'SQL 조인');
  assert.equal(cleanNodeLabel('*β-amyloid*'), 'β-amyloid');
  assert.equal(cleanNodeLabel('[A/B 테스트](https://example.com)'), 'A/B 테스트');
  assert.equal(cleanNodeLabel('__JPA__'), 'JPA');
});

test('T23 저장된 마인드맵 탭은 없고 학습메이트 방 마인드맵만 남는다', async () => {
  installSemanticServer();
  api.agentService.getAgents = async () => [{ id: ROOM_ID, roomName: 'JDBC 방', agents: ROOM_AGENTS }];
  api.agentService.getChatHistory = async () => ROOM_HISTORY;
  const materialCalls = [];
  api.materialService.getMaterials = async (...args) => {
    materialCalls.push(args);
    return [];
  };

  const mindmap = await render(React.createElement(MindmapScreen));
  const mindmapText = textOf(mindmap.toJSON());
  assert.equal(mindmapText.includes('저장된 마인드맵'), false);
  assert.equal(mindmap.root.findAll((instance) => instance.props.role === 'tab').length, 0);
  assert.ok(mindmapText.includes('학습메이트 방'));
  assert.equal(mindmap.root.findByType('select').props.id, 'mindmap-room');
  assert.ok(nodeGroups(mindmap).some((group) => textOf(group.children) === 'ORM'));
  assert.equal(materialCalls.length, 0, '저장본 목록 API 를 부르지 않는다');

  const more = await render(React.createElement(MoreScreen));
  const moreText = textOf(more.toJSON());
  assert.equal(moreText.includes('저장된 마인드맵'), false);
  assert.ok(moreText.includes('마인드맵'));

  const roomTab = await renderRoomMindmap();
  assert.equal(textOf(roomTab.toJSON()).includes('저장된 마인드맵'), false);
});
