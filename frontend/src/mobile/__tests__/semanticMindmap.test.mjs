import test from 'node:test';
import assert from 'node:assert/strict';
import { convertMindMapToObsidianGraph } from '../../utils/graph/mindmapToObsidianGraph.js';
import { buildSemanticAnswers } from '../../utils/graph/semanticGraphMerge.js';
import { NODE_TYPES } from '../../utils/graph/graphTypes.js';
import { withSemanticConcepts } from '../screens/mindmap/semanticGraphModel.js';

const GARBAGE_TOKENS = ['JDBC가', 'JDBC의', 'JDBC를', 'ORM의', '쓰는', '자동으로', '있는', '말할'];
const ANSWER =
  'JDBC가 뭐냐면 JDBC의 정의는 Java Database Connectivity 이고 JDBC를 쓰는 대신 ORM의 매핑으로 자동으로 SQL 을 만들 수 있는 방식이라고 말할 수 있습니다.';

const agents = [{ name: '개념 정리 교수' }, { name: '쉬운 풀이 튜터' }];
const mobileMessages = [
  { id: 'u1', sender: 'USER', content: 'JDBC가 뭐야?' },
  { id: 'a1', sender: 'AI', senderName: '개념 정리 교수', agentIndex: 0, content: ANSWER },
];

const semanticOk = {
  status: 'OK',
  concepts: [
    { id: 'c1', label: 'JDBC', level: 0, aliases: ['JDBC가', 'JDBC의', 'JDBC를'] },
    { id: 'c2', label: 'ORM', level: 1, aliases: ['ORM의'] },
    { id: 'c3', label: 'SQL 생성', level: 1 },
  ],
  relations: [{ from: 'c2', to: 'c3', label: '자동 수행' }],
  sources: [],
  provenance: [],
};

function baseGraph() {
  return convertMindMapToObsidianGraph({ question: 'JDBC가 뭐야?', agents, messages: mobileMessages });
}

function conceptLabels(graph) {
  return graph.nodes.filter((node) => node.type === NODE_TYPES.CONCEPT).map((node) => node.label);
}

test('기본 그래프는 답변 토큰으로 개념 노드를 만들지 않는다', () => {
  assert.deepEqual(conceptLabels(baseGraph()), []);
});

test('Semantic OK 응답이면 AI07 개념만 붙고 조사 붙은 토큰은 노드가 되지 않는다', () => {
  const graph = withSemanticConcepts(baseGraph(), 'ok', semanticOk);
  const labels = conceptLabels(graph);

  assert.deepEqual(labels.sort(), ['JDBC', 'ORM', 'SQL 생성']);
  GARBAGE_TOKENS.forEach((token) => assert.equal(labels.includes(token), false, token));
  assert.equal(graph.semanticStatus, 'OK');
  assert.ok(graph.edges.some((edge) => edge.type === 'semantic_relation' && edge.displayLabel === '자동 수행'));
});

test('Semantic FAILED 이면 예전 토큰 그래프로 되돌아가지 않고 개념 없이 FAILED 를 표시한다', () => {
  const graph = withSemanticConcepts(baseGraph(), 'failed', null);

  assert.deepEqual(conceptLabels(graph), []);
  assert.equal(graph.semanticStatus, 'FAILED');
});

test('Semantic 요청 중에는 LOADING 상태이고 개념 노드가 없다', () => {
  const graph = withSemanticConcepts(baseGraph(), 'loading', null);

  assert.deepEqual(conceptLabels(graph), []);
  assert.equal(graph.semanticStatus, 'LOADING');
});

test('모바일 채팅 메시지에서 AI07 에 보낼 답변은 교수 답변만 담는다', () => {
  const answers = buildSemanticAnswers(mobileMessages, agents);

  assert.equal(answers.length, 1);
  assert.equal(answers[0].agentName, '개념 정리 교수');
  assert.equal(answers[0].content, ANSWER);
});

test('base 그래프가 없으면 그래프를 만들지 않는다', () => {
  assert.equal(withSemanticConcepts(null, 'ok', semanticOk), null);
});
