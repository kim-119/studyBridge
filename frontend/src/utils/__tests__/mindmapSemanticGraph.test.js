// node --test frontend/src/utils/__tests__   (vitest/jest 미도입 — Node 내장 테스트 러너 사용)
// Semantic MindMap 프론트 계층(M1~M5): 개념의 유일한 출처는 AI07(Spring 릴레이) 응답이며, 프론트는 어떤 토큰도 개념으로 만들지 않는다.
import test from 'node:test';
import assert from 'node:assert/strict';
import { convertMindMapToObsidianGraph } from '../graph/mindmapToObsidianGraph.js';
import {
  attachSemanticGraph, buildSemanticAnswers, semanticRequestKey, SEMANTIC_STATUS,
} from '../graph/semanticGraphMerge.js';
import { displayLabelForEdge, EDGE_TYPES, NODE_TYPES } from '../graph/graphTypes.js';

const JUNK = ['JDBC가', 'JDBC의', 'JDBC를', '플랫폼에서의', '있는', '말할'];
const ANSWER = 'JDBC가 뭐냐면, JDBC의 정의는 Java Database Connectivity 이고 JDBC를 통해 플랫폼에서의 SQL 실행이 가능하다고 말할 수 있는 표준입니다.';

const agents = [{ name: '개념 정리 교수' }, { name: '쉬운 풀이 튜터' }, { name: '논점 검증 코치' }];
const messages = [
  { id: 1, sender: 'USER', content: 'JDBC가 뭐야?' },
  { id: 2, sender: 'AI', senderName: '개념 정리 교수', agentIndex: 0, agentId: 10, content: ANSWER, eventId: 'ev-2' },
  { id: 3, sender: 'AI', senderName: '쉬운 풀이 튜터', agentIndex: 1, content: 'JDBC는 자바가 DB와 대화하는 규격이에요. JDBC가 있어야 SQL 실행이 됩니다.' },
];

// Spring /api/mindmap/semantic-graph 정규화 응답(handoff 예시와 동일 구조).
const semanticOk = {
  status: 'OK', degraded: false, degradedReason: null, fingerprint: 'abc', cached: false,
  concepts: [
    { id: 'c1', label: 'JDBC', level: 0, aliases: ['JDBC가', 'JDBC의', 'JDBC를'] },
    { id: 'c2', label: 'Java Database Connectivity', level: 1 },
    { id: 'c3', label: '데이터베이스 연결', level: 1 },
    { id: 'c4', label: 'SQL 실행', level: 1 },
    { id: 'c5', label: 'Connection', level: 2, parentId: 'c1' },
    { id: 'c6', label: 'jdbc', level: 2 }, // 대소문자만 다른 중복 → 병합
  ],
  relations: [
    { from: 'c1', to: 'c2', label: '정의', relationKey: 'DEFINITION' }, { from: 'c1', to: 'c3', label: '목적', relationKey: 'PURPOSE' },
    { from: 'c1', to: 'c4', label: '수행' }, { from: 'c1', to: 'c5', label: '구성 요소' },
  ],
  sources: [{ id: 's1', label: '개념 정리 교수', kind: 'agent' }, { id: 's2', label: '외부 자료', kind: 'material' }],
  provenance: [{ from: 's1', to: 'c1', label: '언급' }, { from: 's2', to: 'c4' }],
};

const base = () => convertMindMapToObsidianGraph({ question: 'JDBC가 뭐야?', agents, messages });
const conceptLabels = (g) => g.nodes.filter((n) => n.type === NODE_TYPES.CONCEPT).map((n) => n.label);

test('G1/M2: base converter emits zero concept nodes and no surface-form/stopword tokens', () => {
  const g = base();
  assert.equal(g.nodes.filter((n) => n.type === NODE_TYPES.CONCEPT).length, 0);
  const labels = g.nodes.map((n) => n.label);
  for (const junk of JUNK) assert.ok(!labels.includes(junk), `junk leaked: ${junk}`);
  assert.equal(g.edges.filter((e) => e.type === EDGE_TYPES.CONTAINS).length, 0, '"포함 개념" 간선 없음');
  // 질문/교수/답변 배치는 그대로 유지
  assert.ok(g.nodes.some((n) => n.type === NODE_TYPES.QUESTION));
  assert.equal(g.nodes.filter((n) => n.type === NODE_TYPES.AGENT).length, 3);
  assert.equal(g.nodes.filter((n) => n.type === NODE_TYPES.ANSWER).length, 2);
});

test('M1/M3: AI07 canonical concepts and relation labels are rendered as-is, hierarchy preserved', () => {
  const g = attachSemanticGraph(base(), semanticOk);
  assert.equal(g.semanticStatus, SEMANTIC_STATUS.OK);
  const labels = conceptLabels(g);
  assert.deepEqual(labels, ['JDBC', 'Java Database Connectivity', '데이터베이스 연결', 'SQL 실행', 'Connection']);
  // Question → Core
  const core = g.edges.filter((e) => e.type === EDGE_TYPES.CORE_CONCEPT);
  assert.equal(core.length, 1);
  assert.equal(core[0].from, g.centerNodeId);
  assert.equal(g.nodes.find((n) => n.id === core[0].to).label, 'JDBC');
  // 의미 관계 라벨 그대로
  const relEdges = g.edges.filter((e) => e.type === EDGE_TYPES.SEMANTIC_RELATION);
  assert.deepEqual(relEdges.map((e) => displayLabelForEdge(e)), ['정의', '목적', '수행', '구성 요소']);
  assert.equal(relEdges[0].metadata.relationKey, 'DEFINITION', 'AI07 relationKey 보존');
  assert.ok(!g.edges.some((e) => e.type === EDGE_TYPES.SEMANTIC_RELATION && displayLabelForEdge(e) === '포함 개념'), '의미 관계를 "포함 개념" 으로 뭉개지 않는다');
  // 계층 메타
  const conn = g.nodes.find((n) => n.label === 'Connection');
  assert.equal(conn.metadata.semanticLevel, 2);
});

test('M2/G3/G4: frontend never fabricates junk concepts; duplicates merged (case-insensitive)', () => {
  const g = attachSemanticGraph(base(), semanticOk);
  const labels = conceptLabels(g);
  for (const junk of JUNK) assert.ok(!labels.includes(junk), `junk leaked: ${junk}`);
  assert.equal(labels.length, new Set(labels.map((l) => l.toLowerCase())).size, 'duplicate concept = 0');
  assert.ok(!labels.includes('jdbc'), 'case-variant duplicate merged');
  // surface form 은 alias 로만 존재
  const jdbc = g.nodes.find((n) => n.label === 'JDBC');
  assert.ok(jdbc.aliases.includes('JDBC가'));
});

test('1.7: agents/sources are a provenance layer, not concepts', () => {
  const g = attachSemanticGraph(base(), semanticOk);
  const labels = conceptLabels(g);
  assert.ok(!labels.includes('개념 정리 교수'));
  assert.ok(!labels.includes('외부 자료'));
  // 이름 일치 교수 → 기존 agent 노드 재사용 + sourced_from 간선
  const agentNode = g.nodes.find((n) => n.type === NODE_TYPES.AGENT && n.agentName === '개념 정리 교수');
  const jdbc = g.nodes.find((n) => n.label === 'JDBC');
  assert.ok(g.edges.some((e) => e.type === EDGE_TYPES.SOURCED_FROM && e.from === agentNode.id && e.to === jdbc.id));
  // 일치하지 않는 출처 → source 노드
  const src = g.nodes.find((n) => n.type === NODE_TYPES.SOURCE);
  assert.equal(src.label, '외부 자료');
  assert.equal(g.nodes.filter((n) => n.type === NODE_TYPES.AGENT).length, 3, 'agent 수 불변');
});

test('M4: FAILED attaches nothing — no token fallback, base graph untouched', () => {
  const b = base();
  const before = JSON.stringify(b.nodes.map((n) => n.id));
  const g = attachSemanticGraph(b, { status: 'FAILED', degradedReason: 'UPSTREAM_ROUTE_NOT_FOUND' });
  assert.equal(g.semanticStatus, SEMANTIC_STATUS.FAILED);
  assert.equal(g.nodes.filter((n) => n.type === NODE_TYPES.CONCEPT).length, 0);
  assert.equal(JSON.stringify(g.nodes.map((n) => n.id)), before);
  assert.equal(JSON.stringify(b.nodes.map((n) => n.id)), before, 'base 는 불변');
  // semantic 자체가 없어도 동일
  assert.equal(attachSemanticGraph(b, null).semanticStatus, SEMANTIC_STATUS.FAILED);
  // OK 라고 하면서 개념이 비어 있으면 FAILED 로 취급
  assert.equal(attachSemanticGraph(b, { status: 'OK', concepts: [] }).semanticStatus, SEMANTIC_STATUS.FAILED);
});

test('DEGRADED is preserved as identifiable status while still rendering concepts', () => {
  const g = attachSemanticGraph(base(), { ...semanticOk, status: 'DEGRADED', degraded: true, degradedReason: 'LLM_TIMEOUT' });
  assert.equal(g.semanticStatus, SEMANTIC_STATUS.DEGRADED);
  assert.equal(conceptLabels(g).length, 5);
});

test('M5: same answers produce the same request key (no repeated LLM call); changed answers differ', () => {
  const a1 = buildSemanticAnswers(messages, agents);
  const a2 = buildSemanticAnswers([...messages].reverse(), agents); // 순서만 다름
  assert.equal(semanticRequestKey(231, 'JDBC가 뭐야?', a1), semanticRequestKey(231, 'JDBC가 뭐야?', a2));
  const a3 = buildSemanticAnswers([...messages, { id: 4, sender: 'AI', senderName: '논점 검증 코치', content: '추가 답변' }], agents);
  assert.notEqual(semanticRequestKey(231, 'JDBC가 뭐야?', a1), semanticRequestKey(231, 'JDBC가 뭐야?', a3));
  assert.notEqual(semanticRequestKey(231, 'JDBC가 뭐야?', a1), semanticRequestKey(232, 'JDBC가 뭐야?', a1), '방이 다르면 다른 키');
});

test('buildSemanticAnswers: only direct AI answers, deduped, with message identity', () => {
  const a = buildSemanticAnswers([
    ...messages,
    { id: 5, sender: 'AI', content: ANSWER },                          // 같은 본문 → 중복 제거
    { id: 6, sender: 'AI', content: '반박', actType: 'REACTION', replyTo: 2 }, // 반박 제외
    { id: 'debate-1', sender: 'AI', nodeType: 'debate', content: '토론 노드' },  // 구조화 노드 제외
    { id: 7, sender: 'AI', content: '   ' },                           // 빈 본문 제외
  ], agents);
  assert.equal(a.length, 2);
  assert.equal(a[0].messageId, 2);
  assert.equal(a[0].eventId, 'ev-2');
  assert.equal(a[0].agentId, 10, 'AI07 answers[].agentId 로 전달되는 교수 id');
  assert.equal(a[1].agentId, null);
  assert.equal(a[0].agentName, '개념 정리 교수');
  assert.equal(a[0].content, ANSWER);
});

test('semantic_relation edge label falls back to generic when AI07 omits label; other edge types unchanged', () => {
  assert.equal(displayLabelForEdge({ type: EDGE_TYPES.SEMANTIC_RELATION, displayLabel: '' }), '의미 관계');
  assert.equal(displayLabelForEdge({ type: EDGE_TYPES.CORE_CONCEPT, displayLabel: '무시됨' }), '핵심 개념');
  assert.equal(displayLabelForEdge({ type: EDGE_TYPES.CONTAINS }), '포함 개념');
});
