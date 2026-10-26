import test from 'node:test';
import assert from 'node:assert/strict';
import { flushEffects, importMobileModule, loadRenderer } from './support/componentHarness.mjs';

const CANVAS_SIZE = { width: 360, height: 480 };

globalThis.ResizeObserver = class {
  constructor(callback) {
    this.callback = callback;
  }

  observe() {
    this.callback([{ contentRect: CANVAS_SIZE }]);
  }

  disconnect() {}
};

const { React, TestRenderer, act } = await loadRenderer();
const { buildMindmapView } = await importMobileModule('screens/mindmap/mindmapModel.js');
const { neighborhoodOf, visibleGraphOf } = await importMobileModule('screens/mindmap/mindmapSelection.js');
const { default: MindmapExplorer } = await importMobileModule('screens/mindmap/MindmapExplorer.jsx');

const RELATION_TOGGLE_LABEL = '선택 관계만 보기';
const JDBC_NEIGHBOR_IDS = ['connection', 'database', 'jdbc', 'orm', 'professor', 'question', 'sql'];
const JDBC_EDGE_IDS = ['answer', 'asks', 'compare', 'component', 'performs', 'purpose'];

function semanticEdge(id, from, to, label) {
  return { id, from, to, type: 'semantic_relation', relationRole: 'semantic_relation', displayLabel: label };
}

function buildSemanticGraph() {
  const concept = (id, title, type = 'concept') => ({ id, type, title });
  return {
    centerNodeId: 'jdbc',
    nodes: [
      concept('jdbc', 'JDBC'),
      concept('database', '데이터베이스 연결'),
      concept('orm', 'ORM'),
      concept('sql', 'SQL 실행'),
      concept('connection', 'Connection'),
      concept('question', 'JDBC가 뭐야?', 'question'),
      concept('professor', '개념 정리 교수', 'source'),
      concept('jpa', 'JPA'),
      concept('cpp', 'C++'),
    ],
    edges: [
      semanticEdge('purpose', 'jdbc', 'database', '목적'),
      semanticEdge('compare', 'orm', 'jdbc', '비교'),
      semanticEdge('performs', 'jdbc', 'sql', '수행'),
      semanticEdge('component', 'jdbc', 'connection', '구성 요소'),
      semanticEdge('asks', 'question', 'jdbc', '질문 대상'),
      semanticEdge('answer', 'professor', 'jdbc', '답변 생성'),
      semanticEdge('example', 'jpa', 'orm', '예시'),
      semanticEdge('steps', 'sql', 'connection', '처리 단계'),
    ],
  };
}

function snapshotOf(view) {
  return JSON.stringify({
    nodes: view.nodes,
    edges: view.edges.map((edge) => ({ ...edge, from: edge.from.id, to: edge.to.id })),
    bounds: view.bounds,
  });
}

function createNodeMock() {
  return { getBoundingClientRect: () => ({ left: 0, top: 0, ...CANVAS_SIZE }), focus() {}, style: {} };
}

async function renderExplorer(view) {
  let renderer;
  await act(async () => {
    renderer = TestRenderer.create(React.createElement(MindmapExplorer, { view, fitKey: 'room-1:ready' }), {
      createNodeMock,
    });
  });
  await flushEffects(5);
  return renderer;
}

function renderedNodeIds(renderer) {
  return renderer.root
    .findAll((instance) => instance.type === 'g' && instance.props['data-node-id'] !== undefined)
    .map((instance) => instance.props['data-node-id'])
    .sort();
}

function renderedEdges(renderer) {
  return renderer.root.findAll((instance) => instance.type === 'line' && instance.props['data-edge-id'] !== undefined);
}

function renderedEdgeIds(renderer) {
  return renderedEdges(renderer)
    .map((instance) => instance.props['data-edge-id'])
    .sort();
}

function relationLabels(renderer) {
  return renderer.root
    .findAll((instance) => instance.type === 'text' && instance.props.className === 'mobile-mindmap__relation')
    .map((instance) => instance.props.children)
    .sort();
}

function relationToggle(renderer) {
  return renderer.root.find((instance) => instance.type === 'input' && instance.props.type === 'checkbox');
}

function canvasTransform(renderer) {
  const group = renderer.root.find((instance) => instance.type === 'g' && instance.props.transform);
  return group.props.transform;
}

async function tapNode(renderer, nodeId) {
  const group = renderer.root.find((instance) => instance.type === 'g' && instance.props['data-node-id'] === nodeId);
  await act(async () => {
    group.props.onClick({ stopPropagation() {} });
  });
}

async function tapBackground(renderer) {
  const svg = renderer.root.find(
    (instance) => instance.type === 'svg' && instance.props.className === 'mobile-mindmap__canvas'
  );
  await act(async () => {
    svg.props.onClick({});
  });
}

async function setRelationOnly(renderer, isChecked) {
  await act(async () => {
    relationToggle(renderer).props.onChange({ target: { checked: isChecked } });
  });
  await flushEffects(5);
}

test('T1 선택 관계만 보기가 꺼져 있으면 모든 노드와 간선을 그린다', async () => {
  const view = buildMindmapView(buildSemanticGraph());
  const renderer = await renderExplorer(view);

  assert.equal(renderedNodeIds(renderer).length, view.nodes.length);
  assert.equal(renderedEdgeIds(renderer).length, view.edges.length);
  assert.equal(relationToggle(renderer).props.checked, false);
  assert.equal(relationToggle(renderer).props.disabled, true);
  assert.ok(renderer.root.findAll((instance) => instance.children?.includes(RELATION_TOGGLE_LABEL)).length > 0);

  await tapNode(renderer, 'jdbc');
  assert.equal(relationToggle(renderer).props.disabled, false);
  assert.equal(renderedNodeIds(renderer).length, view.nodes.length);
  const dimmedNodes = renderer.root.findAll((instance) => instance.props['data-node-emphasis'] === 'dimmed');
  assert.deepEqual(dimmedNodes.map((instance) => instance.props['data-node-id']).sort(), ['cpp', 'jpa']);
});

test('T2 노드 선택 후 켜면 선택 노드와 직접 연결 노드만 그린다', async () => {
  const renderer = await renderExplorer(buildMindmapView(buildSemanticGraph()));

  await tapNode(renderer, 'jdbc');
  await setRelationOnly(renderer, true);

  assert.equal(relationToggle(renderer).props.checked, true);
  assert.deepEqual(renderedNodeIds(renderer), JDBC_NEIGHBOR_IDS);
});

test('T3 연결되지 않은 노드는 렌더링에서 빠진다', async () => {
  const renderer = await renderExplorer(buildMindmapView(buildSemanticGraph()));

  await tapNode(renderer, 'jdbc');
  await setRelationOnly(renderer, true);

  const nodeIds = renderedNodeIds(renderer);
  assert.equal(nodeIds.includes('jpa'), false);
  assert.equal(nodeIds.includes('cpp'), false);
});

test('T4 선택 노드에 닿지 않는 간선은 두 끝점이 보여도 빠진다', async () => {
  const renderer = await renderExplorer(buildMindmapView(buildSemanticGraph()));

  await tapNode(renderer, 'jdbc');
  await setRelationOnly(renderer, true);

  assert.deepEqual(renderedEdgeIds(renderer), JDBC_EDGE_IDS);
  assert.equal(renderedEdgeIds(renderer).includes('steps'), false);
  assert.equal(renderedEdgeIds(renderer).includes('example'), false);
});

test('T5 연결이 없는 노드를 선택해도 선택 노드는 항상 남는다', async () => {
  const renderer = await renderExplorer(buildMindmapView(buildSemanticGraph()));

  await tapNode(renderer, 'cpp');
  await setRelationOnly(renderer, true);

  assert.deepEqual(renderedNodeIds(renderer), ['cpp']);
  assert.deepEqual(renderedEdgeIds(renderer), []);
  assert.match(canvasTransform(renderer), /scale\(/);
  assert.doesNotMatch(canvasTransform(renderer), /NaN|Infinity/);
});

test('T6 간선의 source/target 방향을 바꾸지 않는다', async () => {
  const view = buildMindmapView(buildSemanticGraph());
  const renderer = await renderExplorer(view);

  await tapNode(renderer, 'jdbc');
  await setRelationOnly(renderer, true);

  const nodeById = new Map(view.nodes.map((node) => [node.id, node]));
  const lineById = new Map(renderedEdges(renderer).map((instance) => [instance.props['data-edge-id'], instance.props]));
  const purpose = lineById.get('purpose');
  const compare = lineById.get('compare');

  assert.deepEqual([purpose.x1, purpose.y1, purpose.x2, purpose.y2], [
    nodeById.get('jdbc').x, nodeById.get('jdbc').y, nodeById.get('database').x, nodeById.get('database').y,
  ]);
  assert.deepEqual([compare.x1, compare.y1, compare.x2, compare.y2], [
    nodeById.get('orm').x, nodeById.get('orm').y, nodeById.get('jdbc').x, nodeById.get('jdbc').y,
  ]);

  const visible = visibleGraphOf(view, neighborhoodOf(view, 'jdbc'), true);
  const directions = visible.edges.map((edge) => `${edge.from.id}->${edge.to.id}`).sort();
  assert.deepEqual(directions, [
    'jdbc->connection',
    'jdbc->database',
    'jdbc->sql',
    'orm->jdbc',
    'professor->jdbc',
    'question->jdbc',
  ]);
});

test('T7 실제 의미 관계 라벨을 그대로 보여준다', async () => {
  const renderer = await renderExplorer(buildMindmapView(buildSemanticGraph()));

  await tapNode(renderer, 'jdbc');
  await setRelationOnly(renderer, true);

  assert.deepEqual(relationLabels(renderer), ['구성 요소', '답변 생성', '목적', '비교', '수행', '질문 대상'].sort());
});

test('T8 다른 노드를 탭하면 새 선택 기준으로 즉시 다시 계산한다', async () => {
  const renderer = await renderExplorer(buildMindmapView(buildSemanticGraph()));

  await tapNode(renderer, 'jdbc');
  await setRelationOnly(renderer, true);
  const jdbcTransform = canvasTransform(renderer);

  await tapNode(renderer, 'orm');
  await flushEffects(5);

  assert.equal(relationToggle(renderer).props.checked, true);
  assert.deepEqual(renderedNodeIds(renderer), ['jdbc', 'jpa', 'orm']);
  assert.deepEqual(renderedEdgeIds(renderer), ['compare', 'example']);
  assert.notEqual(canvasTransform(renderer), jdbcTransform);
});

test('T9 선택을 해제하면 전체 그래프로 돌아가고 토글도 꺼진다', async () => {
  const view = buildMindmapView(buildSemanticGraph());
  const renderer = await renderExplorer(view);
  const fullTransform = canvasTransform(renderer);

  await tapNode(renderer, 'jdbc');
  await setRelationOnly(renderer, true);
  assert.notEqual(canvasTransform(renderer), fullTransform);

  await tapBackground(renderer);
  await flushEffects(5);

  assert.equal(renderedNodeIds(renderer).length, view.nodes.length);
  assert.equal(renderedEdgeIds(renderer).length, view.edges.length);
  assert.equal(relationToggle(renderer).props.checked, false);
  assert.equal(relationToggle(renderer).props.disabled, true);
  assert.equal(canvasTransform(renderer), fullTransform);

  await tapNode(renderer, 'jdbc');
  assert.equal(relationToggle(renderer).props.checked, false);
  assert.equal(renderedNodeIds(renderer).length, view.nodes.length);
});

test('T9b 토글만 끄면 선택은 유지하고 전체 그래프 기준으로 다시 맞춘다', async () => {
  const view = buildMindmapView(buildSemanticGraph());
  const renderer = await renderExplorer(view);
  const fullTransform = canvasTransform(renderer);

  await tapNode(renderer, 'jdbc');
  await setRelationOnly(renderer, true);
  await setRelationOnly(renderer, false);

  assert.equal(renderedNodeIds(renderer).length, view.nodes.length);
  assert.equal(canvasTransform(renderer), fullTransform);
  const selected = renderer.root.findAll((instance) => instance.props['data-node-emphasis'] === 'selected');
  assert.deepEqual(selected.map((instance) => instance.props['data-node-id']), ['jdbc']);
});

test('T10 필터는 원본 그래프 객체를 바꾸지 않는다', async () => {
  const view = buildMindmapView(buildSemanticGraph());
  const originalNodes = view.nodes;
  const originalEdges = view.edges;
  const before = snapshotOf(view);
  const renderer = await renderExplorer(view);

  await tapNode(renderer, 'jdbc');
  await setRelationOnly(renderer, true);
  await tapNode(renderer, 'orm');
  await tapBackground(renderer);

  const visible = visibleGraphOf(view, neighborhoodOf(view, 'jdbc'), true);
  assert.notEqual(visible, view);
  assert.equal(view.nodes, originalNodes);
  assert.equal(view.edges, originalEdges);
  assert.equal(view.nodes.length, 9);
  assert.equal(view.edges.length, 8);
  assert.equal(snapshotOf(view), before);
  assert.equal(visibleGraphOf(view, neighborhoodOf(view, 'jdbc'), false), view);
  assert.equal(visibleGraphOf(view, neighborhoodOf(view, null), true), view);
});
