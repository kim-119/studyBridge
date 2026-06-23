// ─────────────────────────────────────────────────────────────────────────────
// 기존 StudyMate 마인드맵 입력(question/agents/messages/interactions)을
// 표준 Obsidian GraphNode/GraphEdge 로 변환하는 adapter.
//  · SSE/응답 데이터 계약은 건드리지 않는다. 이 계층에서만 정규화한다.
//  · 반환: { nodes, edges, centerNodeId, stats, warnings }
// ─────────────────────────────────────────────────────────────────────────────
import { NODE_TYPES, EDGE_TYPES, colorForNode } from './graphTypes';
import { normalizeObsidianName, dedupeObsidianName, makeShortLabel, normalizeTags, buildAliases } from './obsidianName';

const ROLE_ORDER = ['theory', 'book', 'ai'];
const ROLE_KO = { theory: '개념 정리 교수', book: '쉬운 풀이 튜터', ai: '논점 검증 코치' };

const slotToRole = (slot) => ROLE_ORDER[((Number(slot) || 0) % 3 + 3) % 3];

// 개념 추출용 경량 불용어(한국어/영어 혼합). 코드 토큰은 보존한다.
const STOPWORDS = new Set([
  '그리고', '그러나', '하지만', '또한', '이런', '저런', '그런', '있다', '없다', '한다', '된다', '입니다',
  '에서', '으로', '하는', '하고', '에게', '까지', '부터', '대한', '대해', '경우', '때문', '통해', '위해',
  'the', 'and', 'for', 'with', 'that', 'this', 'are', 'was', 'has', 'have', 'from', 'into', 'your', 'you',
]);

const isMeaningfulToken = (t) => {
  if (!t) return false;
  if (t.length < 2) return false;
  if (STOPWORDS.has(t.toLowerCase())) return false;
  if (/^\d+$/.test(t)) return false;
  return true;
};

// 답변 본문에서 상위 빈도 키워드를 개념 후보로 뽑는다(노이즈 방지: 최대 limit개).
function extractConcepts(text, limit) {
  const tokens = String(text || '')
    .replace(/[^\p{L}\p{N}_/.+#-]+/gu, ' ')
    .split(/\s+/)
    .filter(isMeaningfulToken);
  const freq = new Map();
  for (const raw of tokens) {
    const t = raw.replace(/[.]+$/, '');
    if (!isMeaningfulToken(t)) continue;
    freq.set(t, (freq.get(t) || 0) + 1);
  }
  return Array.from(freq.entries())
    .sort((a, b) => b[1] - a[1] || b[0].length - a[0].length)
    .slice(0, limit)
    .map(([term]) => term);
}

const relationFromLabel = (rawLabel = '') => {
  const s = String(rawLabel);
  if (/재?반박/.test(s)) return EDGE_TYPES.REBUTTED_BY;
  if (/검증/.test(s)) return EDGE_TYPES.VALIDATED_BY;
  if (/보완|동의|합의|피드백/.test(s)) return EDGE_TYPES.RELATED_TO;
  return EDGE_TYPES.RELATED_TO;
};

/**
 * @param {{question?:string, agents?:any[], messages?:any[], interactions?:any[], sourceId?:string|number, sourceType?:string, extractConceptsEnabled?:boolean}} input
 * @returns {{nodes:object[], edges:object[], centerNodeId:string, stats:{nodeCount:number,edgeCount:number}, warnings:string[]}}
 */
export function convertMindMapToObsidianGraph(input) {
  const {
    question = '', agents = [], messages = [], interactions = [],
    sourceId = 'session', sourceType = 'multi_agent_chat',
    extractConceptsEnabled = true,
  } = input || {};

  const warnings = [];
  const nodes = [];
  const edges = [];
  const usedNames = new Set();
  const nowIso = new Date().toISOString();

  const pushNode = (n) => {
    const obsidianName = dedupeObsidianName(normalizeObsidianName(n.title || n.label || ''), usedNames);
    const label = n.label || n.title || obsidianName;
    const shortLabel = makeShortLabel(label);
    const node = {
      id: n.id,
      type: n.type,
      label,
      shortLabel,
      title: n.title || label,
      body: n.body || '',
      markdownBody: n.markdownBody || n.body || '',
      obsidianName,
      aliases: buildAliases(label, shortLabel, n.aliases || []),
      tags: normalizeTags(n.tags || []),
      sourceId: n.sourceId != null ? n.sourceId : sourceId,
      sourceType: n.sourceType || sourceType,
      agentName: n.agentName || '',
      agentRole: n.agentRole || '',
      confidence: n.confidence != null ? n.confidence : 1,
      position: null,
      clusterId: n.clusterId || null,
      degree: 0,
      importance: n.importance != null ? n.importance : 1,
      createdAt: nowIso,
      color: colorForNode(n.type),
      metadata: n.metadata || {},
    };
    nodes.push(node);
    return node;
  };

  const edgeSeen = new Set();
  const pushEdge = (from, to, type, extra = {}) => {
    if (!from || !to || from === to) return;
    let id = `edge-${type}-${from}-${to}`;
    let n = 2;
    while (edgeSeen.has(id)) { id = `edge-${type}-${from}-${to}-${n}`; n += 1; }
    edgeSeen.add(id);
    edges.push({
      id, from, to, type,
      label: extra.label || '',
      shortLabel: makeShortLabel(extra.label || '', 12),
      direction: extra.direction || 'forward',
      weight: extra.weight != null ? extra.weight : 1,
      confidence: extra.confidence != null ? extra.confidence : 1,
      metadata: extra.metadata || {},
    });
  };

  // 1) 중심 질문 노드.
  const qText = String(question || '').trim() || '질문을 입력하면 교수들이 답변합니다.';
  const centerNodeId = `question-${sourceId}`;
  pushNode({
    id: centerNodeId, type: NODE_TYPES.QUESTION,
    title: '질문', label: makeShortLabel(qText, 40), body: qText,
    importance: 5, tags: ['question'],
  });

  // 2) 답변 메시지 정규화.
  const answerMsgs = (Array.isArray(messages) ? messages : []).filter((m) => {
    if (!m || m.sender === 'USER') return false;
    if (m.nodeType && ['debate', 'socratic', 'simulation'].includes(m.nodeType)) return false;
    return true;
  });

  const agentList = Array.isArray(agents) ? agents : [];
  const nameToSlot = new Map();
  agentList.forEach((ag, i) => { if (ag?.name) nameToSlot.set(String(ag.name), i); });
  const resolveRole = (m, idx) => {
    if (m.agentRole && ROLE_ORDER.includes(m.agentRole)) return m.agentRole;
    if (Number.isInteger(m.agentIndex)) return slotToRole(m.agentIndex);
    if (m.senderName && nameToSlot.has(String(m.senderName))) return slotToRole(nameToSlot.get(String(m.senderName)));
    return slotToRole(idx);
  };

  // role별 최신 DIRECT 답변 1개.
  const byRole = new Map();
  const agentIdToRole = new Map();
  answerMsgs.forEach((m, i) => {
    const role = resolveRole(m, i);
    if (m.agentId != null) agentIdToRole.set(String(m.agentId), role);
    const text = String(m.content ?? m.answer ?? '').trim();
    const isDirect = !m.actType || m.actType === 'DIRECT_ANSWER';
    const prev = byRole.get(role);
    if (!prev) byRole.set(role, { msg: m, role, text, direct: isDirect });
    else if (isDirect && !prev.direct) byRole.set(role, { msg: m, role, text, direct: true });
    else if (isDirect === prev.direct && text) byRole.set(role, { msg: m, role, text, direct: isDirect });
  });

  const slotCount = Math.max(agentList.length, byRole.size, 3);
  const roles = [];
  for (let i = 0; i < Math.min(slotCount, 3); i += 1) roles.push(slotToRole(i));
  const uniqueRoles = Array.from(new Set([...roles, ...byRole.keys()])).slice(0, 3);

  const roleToAgentId = new Map();
  const roleToAnswerId = new Map();
  const globalConceptByName = new Map(); // 중복 개념 병합

  uniqueRoles.forEach((role, i) => {
    const hit = byRole.get(role);
    const ag = agentList[i] || {};
    const m = hit?.msg || {};
    const name = m.senderName || ag.name || ROLE_KO[role] || `교수 ${i + 1}`;
    const badge = String(m.role || ag.personality || ag.tone || ag.personalityStyle || ag.style || '').trim();
    const answerText = (hit?.text || '').trim();

    // agent 노드.
    const agentId = `agent-${role}`;
    pushNode({
      id: agentId, type: NODE_TYPES.AGENT,
      title: name, label: name, body: badge ? `역할: ${badge}` : name,
      agentName: name, agentRole: badge || role, importance: 3,
      tags: ['agent', role],
    });
    roleToAgentId.set(role, agentId);
    pushEdge(centerNodeId, agentId, EDGE_TYPES.ASKED_TO, { label: '질문' });

    if (!answerText) {
      warnings.push(`role=${role} 답변 비어있음`);
      return;
    }

    // answer 노드.
    const answerId = `answer-${role}`;
    pushNode({
      id: answerId, type: NODE_TYPES.ANSWER,
      title: `${name}의 답변`, label: makeShortLabel(answerText, 28),
      body: answerText, markdownBody: answerText,
      agentName: name, agentRole: badge || role, importance: 2.5,
      tags: ['answer', role],
      metadata: { references: [{ sourceType, sourceId, agentId: m.agentId ?? null }] },
    });
    roleToAnswerId.set(role, answerId);
    pushEdge(agentId, answerId, EDGE_TYPES.PRODUCED, { label: '작성' });
    pushEdge(centerNodeId, answerId, EDGE_TYPES.ANSWERED_BY, { label: '답변', weight: 0.6 });

    // concept 노드(경량 추출, 중복 병합).
    if (extractConceptsEnabled) {
      const concepts = extractConcepts(answerText, 5);
      concepts.forEach((term) => {
        const key = normalizeObsidianName(term).toLowerCase();
        let conceptId = globalConceptByName.get(key);
        if (!conceptId) {
          conceptId = `concept-${globalConceptByName.size + 1}`;
          globalConceptByName.set(key, conceptId);
          pushNode({
            id: conceptId, type: NODE_TYPES.CONCEPT,
            title: term, label: makeShortLabel(term, 20), body: term,
            importance: 1.5, tags: ['concept'],
            metadata: { references: [] },
          });
        } else {
          const cn = nodes.find((x) => x.id === conceptId);
          if (cn) cn.importance += 0.5; // 공통 개념일수록 중심에 가깝게
        }
        pushEdge(answerId, conceptId, EDGE_TYPES.CONTAINS, { label: '포함', weight: 0.4 });
      });
    }
  });

  // 3) REACTION(보충·반박) → rebuttal 노드 + 간선.
  let rebuttalIdx = 0;
  answerMsgs.forEach((m, i) => {
    if (m.actType !== 'REACTION' || m.replyTo == null) return;
    const fromRole = resolveRole(m, i);
    const toRole = agentIdToRole.get(String(m.replyTo));
    const fromAnswer = roleToAnswerId.get(fromRole);
    const toAnswer = roleToAnswerId.get(toRole);
    if (!fromAnswer || !toAnswer || fromRole === toRole) return;
    const body = String(m.content ?? m.answer ?? '').trim();
    if (!body) return;
    rebuttalIdx += 1;
    const rid = `rebuttal-${rebuttalIdx}`;
    pushNode({
      id: rid, type: NODE_TYPES.REBUTTAL,
      title: `반박 - ${ROLE_KO[toRole] || toRole}`, label: '반박',
      body, markdownBody: body, importance: 1.8, tags: ['rebuttal'],
    });
    pushEdge(toAnswer, rid, EDGE_TYPES.REBUTTED_BY, { label: '반박' });
    pushEdge(fromAnswer, rid, EDGE_TYPES.RELATED_TO, { label: '보충', direction: 'none' });
  });

  // 4) interactions → 검증/관련 노드·간선.
  let validationIdx = 0;
  (Array.isArray(interactions) ? interactions : []).forEach((it) => {
    const fromRole = it?.fromRole;
    const targetRole = it?.targetRole;
    const rel = relationFromLabel(it?.relationLabel || it?.phaseLabel);
    const body = String(it?.content || '').trim();
    const fromAnswer = roleToAnswerId.get(fromRole);
    if (rel === EDGE_TYPES.VALIDATED_BY && fromAnswer && body) {
      validationIdx += 1;
      const vid = `validation-${validationIdx}`;
      pushNode({
        id: vid, type: NODE_TYPES.VALIDATION,
        title: `검증 - ${ROLE_KO[fromRole] || fromRole}`, label: '검증',
        body, markdownBody: body, importance: 1.8, tags: ['validation'],
      });
      pushEdge(fromAnswer, vid, EDGE_TYPES.VALIDATED_BY, { label: '검증' });
    } else if (fromAnswer && roleToAnswerId.get(targetRole) && fromRole !== targetRole) {
      pushEdge(fromAnswer, roleToAnswerId.get(targetRole), EDGE_TYPES.RELATED_TO, {
        label: it?.relationLabel || '관련', direction: 'none',
      });
    }
  });

  // 5) degree 계산 + importance 보정.
  const degree = new Map();
  edges.forEach((e) => {
    degree.set(e.from, (degree.get(e.from) || 0) + 1);
    degree.set(e.to, (degree.get(e.to) || 0) + 1);
  });
  nodes.forEach((n) => {
    n.degree = degree.get(n.id) || 0;
    if (n.type === NODE_TYPES.CONCEPT) n.importance += Math.min(2, n.degree * 0.3);
  });

  return {
    nodes, edges, centerNodeId,
    stats: { nodeCount: nodes.length, edgeCount: edges.length },
    warnings,
  };
}
