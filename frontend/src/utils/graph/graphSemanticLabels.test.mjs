// 회귀 테스트 — semanticRole/relationRole 기반 표시 라벨(spec 58·60).
//  실행: node frontend/src/utils/graph/graphSemanticLabels.test.mjs
//  (어댑터 자체는 Vite extensionless import 라 Node 단독 실행 불가 → 매핑 단일 출처를 검증한다.
//   어댑터의 노드/간선 생성은 build + 수동 검증으로 확인.)
import {
  displayLabelForNode, displayLabelForEdge, relationLabelForEdgeType,
  NODE_LABEL_KO, EDGE_RELATION_LABEL,
} from './graphTypes.js';

let pass = 0; let fail = 0;
const ok = (name, cond) => { if (cond) pass += 1; else { fail += 1; console.error('  ✗', name); } };

// ── 노드 displayLabel: semanticRole 기반 ─────────────────────────────────────
ok('question→질문', displayLabelForNode({ type: 'question' }) === '질문');
ok('answer→답변', displayLabelForNode({ type: 'answer' }) === '답변');
ok('validation→검증', displayLabelForNode({ type: 'validation' }) === '검증');
ok('rebuttal→반박', displayLabelForNode({ type: 'rebuttal' }) === '반박');
ok('example→예시', displayLabelForNode({ type: 'example' }) === '예시');
ok('source→자료', displayLabelForNode({ type: 'source' }) === '자료');
ok('room→방', NODE_LABEL_KO.room === '방');
// concept 는 실제 개념명, agent 는 교수명.
ok('concept→실제 개념명', displayLabelForNode({ type: 'concept', title: 'WebRTC', shortLabel: 'WebRTC' }) === 'WebRTC');
ok('agent→교수명', displayLabelForNode({ type: 'agent', agentName: '개념 정리 교수' }) === '개념 정리 교수');
// semanticRole 이 type 보다 우선.
ok('semanticRole 우선', displayLabelForNode({ type: 'concept', semanticRole: 'rebuttal' }) === '반박');

// ── 간선 displayLabel: relationRole 기반([질문]/[답변]/[검증]/[반박]/[자료 출처]/[관련 개념]) ──
ok('answered_by→답변', displayLabelForEdge({ type: 'answered_by' }) === '답변');
ok('validated_by→검증', displayLabelForEdge({ type: 'validated_by' }) === '검증');
ok('rebutted_by→반박', displayLabelForEdge({ type: 'rebutted_by' }) === '반박');
ok('exemplified_by→예시', displayLabelForEdge({ type: 'exemplified_by' }) === '예시');
ok('sourced_from→자료 출처', displayLabelForEdge({ type: 'sourced_from' }) === '자료 출처');
ok('related_to→관련 개념', displayLabelForEdge({ type: 'related_to' }) === '관련 개념');
ok('relationRole 우선', displayLabelForEdge({ type: 'related_to', relationRole: 'validated_by' }) === '검증');

// ── 본문 스니펫 동사 라벨("작성"·"포함")이 매핑 어디에도 없어야 한다(spec 59) ──
const allMapped = [...Object.values(NODE_LABEL_KO), ...Object.values(EDGE_RELATION_LABEL)];
ok('"작성" 매핑 없음', !allMapped.includes('작성'));
ok('"포함" 매핑(정확히) 없음', !allMapped.includes('포함'));
ok('produced→답변 생성', relationLabelForEdgeType('produced') === '답변 생성');
ok('contains→포함 개념', relationLabelForEdgeType('contains') === '포함 개념');

console.log(`\ngraphSemanticLabels 테스트: ${pass} passed, ${fail} failed`);
process.exit(fail === 0 ? 0 : 1);
