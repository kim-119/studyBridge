// 회귀 테스트 — graphLabelLayout 충돌 회피.
//  실행: node frontend/src/utils/graph/graphLabelLayout.test.mjs
//  (이 프로젝트엔 별도 테스트 러너가 없어 node 로 직접 구동한다. eslint --ext js,jsx 대상 아님.)
import {
  rectsOverlap, circleRectOverlap, resolveEdgeLabelPosition,
  edgeLabelVisibleAtZoom, computeLabelLayout, LABEL_PRIORITY, nodeLabelBox, edgeLabelSize,
} from './graphLabelLayout.js';

let pass = 0;
let fail = 0;
function ok(name, cond) {
  if (cond) { pass += 1; } else { fail += 1; console.error('  ✗ FAIL:', name); }
}

// helper: 두 박스(center)가 안 겹치는지(라벨끼리 padding 0 기준).
const noOverlap = (a, b) => !rectsOverlap(a, b, 0);

// ── geometry helpers ─────────────────────────────────────────────────────────
ok('rectsOverlap: 같은 위치는 겹침', rectsOverlap({ x: 0, y: 0, w: 10, h: 10 }, { x: 0, y: 0, w: 10, h: 10 }, 0));
ok('rectsOverlap: 멀리 떨어지면 안 겹침', !rectsOverlap({ x: 0, y: 0, w: 10, h: 10 }, { x: 100, y: 0, w: 10, h: 10 }, 0));
ok('circleRectOverlap: 중심 포함 시 겹침', circleRectOverlap({ x: 0, y: 0, r: 8 }, { x: 0, y: 0, w: 4, h: 4 }, 0));
ok('circleRectOverlap: 먼 사각형은 안 겹침', !circleRectOverlap({ x: 0, y: 0, r: 8 }, { x: 50, y: 0, w: 4, h: 4 }, 0));

// ── [22단계] "작성/반박" 재현 시나리오 ────────────────────────────────────────
// 노드 "작성"(점+라벨) 근처에 간선 "반박" 라벨이 mid 로 떨어지는 상황.
// 노드: (0,0) r=8 → 라벨 box center ≈ (0, 0+8+12+7.5=27.5)
// 간선: source(-40,40) target(40,40) → mid (0,40) — 노드 라벨과 매우 가까움.
{
  const nodes = [{
    id: 'writeNode', x: 0, y: 0, r: 8, haloR: 0,
    text: '작성', showLabel: true, priority: LABEL_PRIORITY.NODE,
  }];
  const edges = [{
    id: 'rebut', sx: -40, sy: 40, tx: 40, ty: 40,
    text: '반박', candidate: true, boosted: false, priority: LABEL_PRIORITY.LOCAL_EDGE,
  }];
  const { nodeLabels, edgeLabels } = computeLabelLayout({ nodes, edges });
  const nl = nodeLabels.get('writeNode');
  const el = edgeLabels.get('rebut');
  ok('작성: 노드 라벨 표시됨', nl && !nl.hidden);
  ok('반박: 간선 라벨 배치됨(숨김 아님)', el && !el.hidden);
  ok('작성 vs 반박: 라벨 박스가 겹치지 않음', noOverlap(nl.box, { x: el.x, y: el.y, w: el.w, h: el.h }));
  ok('반박: 노드 점 위에 안 올라옴', !circleRectOverlap({ x: 0, y: 0, r: 8 }, { x: el.x, y: el.y, w: el.w, h: el.h }, 0));
  ok('반박: 법선으로 밀려남(offset!=0)', el.offset !== 0);
}

// ── selected node label 위에 edge label 안 올라옴 ─────────────────────────────
{
  const nodes = [{
    id: 'sel', x: 0, y: 0, r: 10, haloR: 18,
    text: '선택노드', showLabel: true, priority: LABEL_PRIORITY.SELECTED_NODE,
  }];
  const edges = [{
    id: 'e', sx: -30, sy: 28, tx: 30, ty: 28,
    text: '검증', candidate: true, boosted: true, priority: LABEL_PRIORITY.SELECTED_EDGE,
  }];
  const { nodeLabels, edgeLabels } = computeLabelLayout({ nodes, edges });
  const nl = nodeLabels.get('sel');
  const el = edgeLabels.get('e');
  ok('선택 노드 라벨은 항상 표시', nl && !nl.hidden);
  if (el && !el.hidden) {
    ok('selected node label 위에 edge label 안 겹침', noOverlap(nl.box, { x: el.x, y: el.y, w: el.w, h: el.h }));
  } else {
    ok('selected node label 보호 → 충돌 시 edge label 숨김', el && el.hidden);
  }
}

// ── zoom < 0.6 → 일반 edge label 숨김 ─────────────────────────────────────────
{
  const v = edgeLabelVisibleAtZoom(
    { selected: false, hovered: false, focus: false, oneHop: false },
    0.4,
    { mode: 'local', edgeLabelsOn: true, alwaysOn: false },
  );
  ok('zoom 0.4: 일반 edge label 숨김', v === false);
  const vSel = edgeLabelVisibleAtZoom(
    { selected: true, hovered: false, focus: false, oneHop: true },
    0.4,
    { mode: 'local', edgeLabelsOn: true, alwaysOn: false },
  );
  ok('zoom 0.4: 선택 노드 1-hop edge label 은 표시', vSel === true);
}

// ── 충돌 해결 실패 시 edge label 숨김 ─────────────────────────────────────────
{
  // 노드 점들을 mid 주변 법선 방향으로 촘촘히 깔아 모든 offset 후보를 막는다.
  const blockers = [];
  for (let off = -80; off <= 80; off += 8) {
    blockers.push({ x: 0, y: off, r: 12 });
  }
  const occupied = { circles: blockers, rects: [] };
  const res = resolveEdgeLabelPosition(
    { sx: -50, sy: 0, tx: 50, ty: 0, boosted: true },
    edgeLabelSize('반박'),
    occupied,
    {},
  );
  ok('모든 offset 충돌 → edge label hidden', res.hidden === true);
}

// ── 1-hop edge label 은 충돌 없는 위치에 배치 ─────────────────────────────────
{
  const nodes = [
    { id: 'c', x: 0, y: 0, r: 10, haloR: 16, text: '중심', showLabel: true, priority: LABEL_PRIORITY.SELECTED_NODE },
    { id: 'n', x: 120, y: 0, r: 8, haloR: 0, text: '이웃', showLabel: true, priority: LABEL_PRIORITY.NODE },
  ];
  const edges = [{
    id: 'h', sx: 0, sy: 0, tx: 120, ty: 0, text: '답변',
    candidate: true, boosted: true, priority: LABEL_PRIORITY.SELECTED_EDGE,
  }];
  const { edgeLabels } = computeLabelLayout({ nodes, edges });
  const el = edgeLabels.get('h');
  ok('1-hop edge label 배치됨', el && !el.hidden);
  ok('1-hop edge label 이 양 끝 점과 안 겹침',
    !circleRectOverlap({ x: 0, y: 0, r: 10 }, { x: el.x, y: el.y, w: el.w, h: el.h }, 0)
    && !circleRectOverlap({ x: 120, y: 0, r: 8 }, { x: el.x, y: el.y, w: el.w, h: el.h }, 0));
}

// ── nodeLabelBox / edgeLabelSize sanity ───────────────────────────────────────
{
  const b = nodeLabelBox(0, 0, 8, '작성');
  ok('nodeLabelBox: 점 아래에 위치', b.y > 8);
  const s = edgeLabelSize('자료 출처');
  ok('edgeLabelSize: 최소/최대 폭 클램프', s.w >= 24 && s.w <= 84);
}

console.log(`\ngraphLabelLayout 테스트: ${pass} passed, ${fail} failed`);
process.exit(fail === 0 ? 0 : 1);
