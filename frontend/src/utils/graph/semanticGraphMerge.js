// ─────────────────────────────────────────────────────────────────────────────
// AI07 Semantic Graph(Spring /api/mindmap/semantic-graph 정규화 응답) → Obsidian 그래프 병합.
//  · 개념(concept) 노드의 유일한 출처. 답변 본문 토큰화/불용어/빈도 추출은 어디에도 없다.
//  · 계층 보존: Question → Core(level 0) → Primary(level 1) → Secondary(level 2).
//  · 교수/에이전트는 concept 가 아니라 source 레이어(sources/provenance) — 이름이 일치하는 기존 agent 노드에 붙이고,
//    없으면 NODE_TYPES.SOURCE 노드로 둔다.
//  · FAILED 이면 아무것도 얹지 않는다(호출측이 명시적 실패 상태를 표시). 순수 함수 — React/DOM 의존 없음.
// ─────────────────────────────────────────────────────────────────────────────
import {
  NODE_TYPES, EDGE_TYPES, colorForNode, displayLabelForNode, relationLabelForEdgeType,
} from './graphTypes.js';
import { normalizeObsidianName, makeShortLabel, normalizeTags, buildAliases } from './obsidianName.js';

export const SEMANTIC_STATUS = Object.freeze({ OK: 'OK', DEGRADED: 'DEGRADED', FAILED: 'FAILED' });

const text = (v) => String(v ?? '').trim();
const asArray = (v) => (Array.isArray(v) ? v : []);

/**
 * 마인드맵 메시지(채팅 히스토리/토론 확장 결과)에서 AI07 에 보낼 답변 목록을 만든다.
 *  · USER/구조화(debate/socratic/simulation) 노드 제외, 빈 본문 제외, 같은 본문 중복 제거.
 * @param {any[]} messages
 * @param {any[]} [agents]
 * @returns {{messageId:(number|null), eventId:(string|null), agentId:(number|null), agentName:string, agentRole:string, content:string}[]}
 */
export function buildSemanticAnswers(messages, agents = []) {
  const seen = new Set();
  const out = [];
  const agentList = asArray(agents);
  asArray(messages).forEach((m, idx) => {
    if (!m || m.sender === 'USER') return;
    if (m.nodeType && ['debate', 'socratic', 'simulation'].includes(m.nodeType)) return;
    if (m.actType && m.actType !== 'DIRECT_ANSWER') return; // 반박/보충은 provenance 가 아니라 rebuttal 노드가 담당
    const content = text(m.content ?? m.answer);
    if (!content) return;
    const key = content.toLowerCase();
    if (seen.has(key)) return;
    seen.add(key);
    const agent = Number.isInteger(m.agentIndex) ? agentList[m.agentIndex] : null;
    const numericId = typeof m.id === 'number' || (typeof m.id === 'string' && /^\d+$/.test(m.id)) ? Number(m.id) : null;
    const agentIdRaw = m.agentId ?? agent?.id ?? null;
    out.push({
      messageId: numericId,
      eventId: m.eventId ? String(m.eventId) : null,
      agentId: agentIdRaw != null && /^\d+$/.test(String(agentIdRaw)) ? Number(agentIdRaw) : null,
      agentName: text(m.senderName || agent?.name || ''),
      agentRole: text(m.agentRole || agent?.role || ''),
      content,
    });
    void idx;
  });
  return out;
}

/**
 * 클라이언트 측 재요청 억제용 지문(서버 fingerprint 와 별개, 같은 화면 재렌더에서 같은 값).
 * @returns {string}
 */
export function semanticRequestKey(roomId, question, answers) {
  const parts = asArray(answers).map((a) => `${a.agentName || ''}\u0002${a.content}`).sort();
  return `${roomId ?? 'none'}|${text(question)}|${parts.join('\u0001')}`;
}

const levelOf = (c) => {
  const n = Number(c?.level);
  if (!Number.isFinite(n)) return 0;
  return Math.max(0, Math.min(2, Math.round(n)));
};

/**
 * base 그래프(question/agent/answer/...) 위에 semantic 개념 계층을 얹는다. base 는 변경하지 않고 새 그래프를 돌려준다.
 * @param {{nodes:object[], edges:object[], centerNodeId:string, stats?:object, warnings?:string[]}} base
 * @param {{status?:string, degraded?:boolean, concepts?:object[], relations?:object[], sources?:object[], provenance?:object[]}} semantic
 * @returns {{nodes:object[], edges:object[], centerNodeId:string, stats:{nodeCount:number,edgeCount:number}, warnings:string[], semanticStatus:string}}
 */
export function attachSemanticGraph(base, semantic) {
  const nodes = asArray(base?.nodes).map((n) => ({ ...n }));
  const edges = asArray(base?.edges).map((e) => ({ ...e }));
  const warnings = [...asArray(base?.warnings)];
  const centerNodeId = base?.centerNodeId || (nodes[0] && nodes[0].id) || null;
  const status = text(semantic?.status).toUpperCase() || SEMANTIC_STATUS.FAILED;

  const finish = (semanticStatus) => ({
    nodes, edges, centerNodeId,
    stats: { nodeCount: nodes.length, edgeCount: edges.length },
    warnings,
    semanticStatus,
  });

  if (!semantic || status === SEMANTIC_STATUS.FAILED) {
    // FAILED: 개념 계층 없음. 예전 토큰 그래프로도 되돌아가지 않는다.
    return finish(SEMANTIC_STATUS.FAILED);
  }

  const nodeIds = new Set(nodes.map((n) => n.id));
  const usedNames = new Set(nodes.map((n) => String(n.obsidianName || '').toLowerCase()).filter(Boolean));
  const nowIso = new Date().toISOString();

  const pushNode = (n) => {
    if (nodeIds.has(n.id)) return nodes.find((x) => x.id === n.id);
    let obsidianName = normalizeObsidianName(n.title || n.label || '');
    let cand = obsidianName; let k = 2;
    while (usedNames.has(cand.toLowerCase())) { cand = `${obsidianName} (${k})`; k += 1; }
    usedNames.add(cand.toLowerCase());
    obsidianName = cand;
    const label = n.label || n.title || obsidianName;
    const shortLabel = makeShortLabel(label, 22);
    const node = {
      id: n.id, type: n.type, semanticRole: n.semanticRole || n.type,
      displayLabel: '', label, shortLabel, title: n.title || label,
      body: n.body || '', markdownBody: n.markdownBody || n.body || '',
      obsidianName, aliases: buildAliases(label, shortLabel, n.aliases || []),
      tags: normalizeTags(n.tags || []),
      sourceId: n.sourceId != null ? n.sourceId : 'ai07-semantic',
      sourceType: n.sourceType || 'semantic_graph',
      agentName: n.agentName || '', agentRole: n.agentRole || '',
      confidence: n.confidence != null ? n.confidence : 1,
      position: null, clusterId: null, degree: 0,
      importance: n.importance != null ? n.importance : 1,
      createdAt: nowIso, color: colorForNode(n.type), metadata: n.metadata || {},
    };
    node.displayLabel = displayLabelForNode(node);
    nodes.push(node);
    nodeIds.add(node.id);
    return node;
  };

  const edgeSeen = new Set(edges.map((e) => e.id));
  const pushEdge = (from, to, type, extra = {}) => {
    if (!from || !to || from === to || !nodeIds.has(from) || !nodeIds.has(to)) return;
    let id = `edge-${type}-${from}-${to}`;
    let n = 2;
    while (edgeSeen.has(id)) { id = `edge-${type}-${from}-${to}-${n}`; n += 1; }
    edgeSeen.add(id);
    const relationLabel = extra.displayLabel || relationLabelForEdgeType(type);
    edges.push({
      id, from, to, type, relationRole: type,
      displayLabel: relationLabel, label: relationLabel, shortLabel: makeShortLabel(relationLabel, 12),
      direction: extra.direction || 'forward',
      weight: extra.weight != null ? extra.weight : 1,
      confidence: extra.confidence != null ? extra.confidence : 1,
      metadata: extra.metadata || {},
    });
  };

  // 1) 개념 노드(AI07 canonical 라벨 그대로). 같은 라벨(대소문자 무시)은 하나로 합친다(중복 개념 0).
  const conceptIdMap = new Map();   // AI07 concept id → graph node id
  const labelToNodeId = new Map();
  const concepts = asArray(semantic.concepts).filter((c) => c && text(c.label));
  concepts.forEach((c) => {
    const label = text(c.label);
    const lk = label.toLowerCase();
    const level = levelOf(c);
    if (labelToNodeId.has(lk)) { conceptIdMap.set(String(c.id), labelToNodeId.get(lk)); return; }
    const nodeId = `concept-${text(c.id) || `${conceptIdMap.size + 1}`}`;
    const importance = level === 0 ? 3.2 : level === 1 ? 2.2 : 1.5;
    pushNode({
      id: nodeId, type: NODE_TYPES.CONCEPT, title: label, label, body: text(c.description) || label,
      aliases: asArray(c.aliases).map(text).filter(Boolean),
      importance, tags: ['concept', `level-${level}`],
      metadata: {
        semanticLevel: level, levelName: c.levelName ?? null, semanticId: c.id ?? null, parentId: c.parentId ?? null,
        aliases: asArray(c.aliases), surfaceForms: asArray(c.surfaceForms), mentions: c.mentions ?? null,
      },
    });
    conceptIdMap.set(String(c.id), nodeId);
    labelToNodeId.set(lk, nodeId);
  });
  if (conceptIdMap.size === 0) {
    warnings.push('semantic graph 에 개념이 없음');
    return finish(SEMANTIC_STATUS.FAILED);
  }

  // 2) 계층 간선: core → question 에서, primary/secondary → parent(없으면 상위 레벨 첫 개념) 에서.
  const byLevel = [[], [], []];
  concepts.forEach((c) => {
    const nodeId = conceptIdMap.get(String(c.id));
    if (nodeId && !byLevel[levelOf(c)].includes(nodeId)) byLevel[levelOf(c)].push(nodeId);
  });
  if (byLevel[0].length === 0) {
    // core 가 없으면 가장 낮은 레벨을 core 로 승격(질문과 끊기지 않게).
    const first = byLevel[1].length ? 1 : 2;
    byLevel[0] = byLevel[first]; byLevel[first] = [];
  }
  byLevel[0].forEach((id) => pushEdge(centerNodeId, id, EDGE_TYPES.CORE_CONCEPT, { weight: 1 }));
  const relationPairs = new Set();
  asArray(semantic.relations).forEach((r) => {
    const from = conceptIdMap.get(String(r?.from));
    const to = conceptIdMap.get(String(r?.to));
    if (from && to) relationPairs.add(`${from}|${to}`);
  });
  concepts.forEach((c) => {
    const level = levelOf(c);
    if (level === 0) return;
    const nodeId = conceptIdMap.get(String(c.id));
    if (!nodeId || byLevel[0].includes(nodeId)) return;
    const parent = c.parentId != null ? conceptIdMap.get(String(c.parentId)) : null;
    const fallbackParent = (byLevel[level - 1][0]) || byLevel[0][0];
    const target = parent || fallbackParent;
    if (!target || target === nodeId) return;
    // 같은 쌍에 의미 관계가 있으면 계층 간선은 생략(중복 선 방지).
    if (relationPairs.has(`${target}|${nodeId}`) || relationPairs.has(`${nodeId}|${target}`)) return;
    pushEdge(target, nodeId, EDGE_TYPES.CONTAINS, { weight: 0.6 });
  });

  // 3) 의미 관계 간선(AI07 라벨 그대로 표시).
  asArray(semantic.relations).forEach((r) => {
    const from = conceptIdMap.get(String(r?.from));
    const to = conceptIdMap.get(String(r?.to));
    if (!from || !to) return;
    pushEdge(from, to, EDGE_TYPES.SEMANTIC_RELATION, {
      displayLabel: text(r.label) || relationLabelForEdgeType(EDGE_TYPES.SEMANTIC_RELATION),
      weight: 0.8, metadata: { relationType: r.type ?? null, relationKey: r.relationKey ?? null },
    });
  });

  // 4) 출처 레이어: 교수 이름이 일치하는 agent 노드 재사용, 없으면 source 노드.
  const agentByName = new Map();
  nodes.forEach((n) => { if (n.type === NODE_TYPES.AGENT && n.agentName) agentByName.set(String(n.agentName).toLowerCase(), n.id); });
  const sourceIdMap = new Map();
  asArray(semantic.sources).forEach((s) => {
    if (!s) return;
    const label = text(s.label || s.agentName);
    const hit = label ? agentByName.get(label.toLowerCase()) : null;
    if (hit) { sourceIdMap.set(String(s.id), hit); return; }
    const nodeId = `source-${text(s.id) || `${sourceIdMap.size + 1}`}`;
    pushNode({
      id: nodeId, type: NODE_TYPES.SOURCE, title: label || '출처', label: label || '출처', body: label,
      agentName: text(s.agentName), agentRole: text(s.agentRole), importance: 1.4, tags: ['source', text(s.kind) || 'agent'],
      metadata: { kind: s.kind ?? null },
    });
    sourceIdMap.set(String(s.id), nodeId);
  });
  asArray(semantic.provenance).forEach((p) => {
    const from = sourceIdMap.get(String(p?.from));
    const to = conceptIdMap.get(String(p?.to));
    if (!from || !to) return;
    pushEdge(from, to, EDGE_TYPES.SOURCED_FROM, { weight: 0.4, direction: 'forward', metadata: { provenanceLabel: p.label ?? null, relationKey: p.relationKey ?? 'SOURCE' } });
  });

  // 5) degree 재계산.
  const degree = new Map();
  edges.forEach((e) => {
    degree.set(e.from, (degree.get(e.from) || 0) + 1);
    degree.set(e.to, (degree.get(e.to) || 0) + 1);
  });
  nodes.forEach((n) => { n.degree = degree.get(n.id) || 0; });

  return finish(status === SEMANTIC_STATUS.DEGRADED || semantic.degraded ? SEMANTIC_STATUS.DEGRADED : SEMANTIC_STATUS.OK);
}
