import test from 'node:test';
import assert from 'node:assert/strict';
import {
  EMPHASIS,
  edgeEmphasis,
  neighborhoodOf,
  nodeEmphasis,
  relationLabelOf,
} from '../screens/mindmap/mindmapSelection.js';

function node(id, title = id) {
  return { id, title, label: title, x: 0, y: 0 };
}

function buildView() {
  const nodes = [node('question', '질문'), node('os', '운영체제'), node('process', '프로세스'), node('memory', '메모리')];
  const byId = new Map(nodes.map((item) => [item.id, item]));
  const edge = (id, from, to, raw) => ({ id, from: byId.get(from), to: byId.get(to), relationLabel: relationLabelOf(raw) });

  return {
    nodes,
    edges: [
      edge('e1', 'question', 'os', { type: 'core_concept', displayLabel: '핵심 개념' }),
      edge('e2', 'os', 'process', { type: 'semantic_relation', relationRole: 'semantic_relation', displayLabel: '수행' }),
      edge('e3', 'memory', 'os', { type: 'semantic_relation', relationRole: 'semantic_relation', displayLabel: '구성 요소' }),
      edge('e4', 'process', 'memory', { type: 'semantic_relation', relationRole: 'semantic_relation', displayLabel: '원인' }),
    ],
  };
}

test('T14 노드를 탭하면 그 노드가 선택 상태가 된다', () => {
  const neighborhood = neighborhoodOf(buildView(), 'os');

  assert.equal(neighborhood.selectedNodeId, 'os');
  assert.equal(nodeEmphasis(neighborhood, 'os'), EMPHASIS.SELECTED);
});

test('T15 직접 연결된 노드는 강조된다', () => {
  const neighborhood = neighborhoodOf(buildView(), 'os');

  assert.equal(nodeEmphasis(neighborhood, 'question'), EMPHASIS.CONNECTED);
  assert.equal(nodeEmphasis(neighborhood, 'process'), EMPHASIS.CONNECTED);
  assert.equal(nodeEmphasis(neighborhood, 'memory'), EMPHASIS.CONNECTED);
});

test('T16 직접 연결된 간선을 강조하고 실제 의미 관계 라벨을 그대로 보여준다', () => {
  const neighborhood = neighborhoodOf(buildView(), 'os');

  assert.deepEqual([...neighborhood.edgeIds].sort(), ['e1', 'e2', 'e3']);
  assert.equal(edgeEmphasis(neighborhood, 'e2'), EMPHASIS.CONNECTED);
  assert.deepEqual(
    neighborhood.relations.map((relation) => [relation.label, relation.direction, relation.neighbor.id]),
    [
      ['핵심 개념', 'incoming', 'question'],
      ['수행', 'outgoing', 'process'],
      ['구성 요소', 'incoming', 'memory'],
    ]
  );
  assert.equal(relationLabelOf({ type: 'semantic_relation', displayLabel: '정의' }), '정의');
  assert.notEqual(relationLabelOf({ type: 'semantic_relation', displayLabel: '비교' }), '포함 개념');
});

test('T17 연결되지 않은 노드와 간선은 흐리게 표시한다', () => {
  const neighborhood = neighborhoodOf(buildView(), 'question');

  assert.equal(nodeEmphasis(neighborhood, 'process'), EMPHASIS.DIMMED);
  assert.equal(nodeEmphasis(neighborhood, 'memory'), EMPHASIS.DIMMED);
  assert.equal(edgeEmphasis(neighborhood, 'e4'), EMPHASIS.DIMMED);
  assert.equal(edgeEmphasis(neighborhood, 'e2'), EMPHASIS.DIMMED);
});

test('T18 선택을 해제하면 모든 노드와 간선이 정상 상태로 돌아간다', () => {
  const view = buildView();
  const cleared = neighborhoodOf(view, null);
  const missing = neighborhoodOf(view, 'deleted-node');

  view.nodes.forEach((item) => assert.equal(nodeEmphasis(cleared, item.id), EMPHASIS.NORMAL));
  view.edges.forEach((item) => assert.equal(edgeEmphasis(cleared, item.id), EMPHASIS.NORMAL));
  assert.equal(nodeEmphasis(missing, 'os'), EMPHASIS.NORMAL);
});
