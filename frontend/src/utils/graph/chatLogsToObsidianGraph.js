// ─────────────────────────────────────────────────────────────────────────────
// 학습메이트 방(AI 룸)의 채팅 히스토리 → Obsidian GraphNode/GraphEdge 변환 adapter.
//  · 옵시디언 페이지가 source of truth 로 사용하는 단일 진입점.
//  · 방 1개의 로그만 받아 그래프를 만든다(방 섞임 금지는 호출측 requestSeq 가드가 담당).
//  · 검증/반박은 AI 메시지의 processSteps(validatedAnswers/peerFeedback)에서 best-effort 로 뽑는다.
//  · 실제 노드/간선 생성은 검증된 convertMindMapToObsidianGraph 를 재사용한다.
// ─────────────────────────────────────────────────────────────────────────────
import { convertMindMapToObsidianGraph } from './mindmapToObsidianGraph';
import { EDGE_TYPES } from './graphTypes';

const ROLE_ORDER = ['theory', 'book', 'ai'];
const slotToRole = (slot) => ROLE_ORDER[((Number(slot) || 0) % 3 + 3) % 3];

const asArray = (v) => (Array.isArray(v) ? v : []);
const text = (v) => String(v ?? '').trim();

// 피드백 1건의 semantic relationRole 판정.
//  · 분류 우선순위(spec): roleType → feedbackType → stage → messageType → agentRole → content.
//  · 끝까지 애매하면 검증으로 두고 needsReview=true(상세 패널에 "분류 검토 필요").
const REBUT_RE = /반박|하지만|다만|오히려|틀린 점|틀렸|보완해야|한계|문제는|허점|반대|오류/;
const VALIDATE_RE = /검증|타당|근거|확인|정확성|논리적으로|논리적|평가/;
const EXAMPLE_RE = /예시|예를 들어|가령|비유하면|비유/;

// 토큰(roleType/feedbackType/messageType 값)을 relationRole 로 매핑.
const tokenToRelation = (raw) => {
  const s = String(raw ?? '').toLowerCase();
  if (!s) return null;
  if (/rebut|counter|반박/.test(s)) return EDGE_TYPES.REBUTTED_BY;
  if (/valid|check|검증/.test(s)) return EDGE_TYPES.VALIDATED_BY;
  if (/example|예시/.test(s)) return EDGE_TYPES.EXEMPLIFIED_BY;
  return null;
};

function classifyFeedback(row, content) {
  const md = (row && typeof row.metadata === 'object' && row.metadata) ? row.metadata : (row || {});
  // 1) roleType, 2) feedbackType, (intent 보조)
  let rel = tokenToRelation(md.roleType ?? row?.roleType)
    || tokenToRelation(md.feedbackType ?? row?.feedbackType);
  if (!rel) {
    const intent = String(md.intent ?? row?.intent ?? '').toLowerCase();
    if (intent === 'counterargument') rel = EDGE_TYPES.REBUTTED_BY;
    else if (intent === 'check') rel = EDGE_TYPES.VALIDATED_BY;
  }
  if (rel) return { relationRole: rel };
  // 3) stage
  const stage = String(md.stage ?? row?.stage ?? '').toUpperCase();
  if (stage === 'VALIDATION') return { relationRole: EDGE_TYPES.VALIDATED_BY };
  // 4) messageType
  rel = tokenToRelation(md.messageType ?? row?.messageType);
  if (rel) return { relationRole: rel };
  // 6) content pattern (5의 agentRole 은 아래에서 보조 판정)
  if (REBUT_RE.test(content)) return { relationRole: EDGE_TYPES.REBUTTED_BY };
  if (EXAMPLE_RE.test(content)) return { relationRole: EDGE_TYPES.EXEMPLIFIED_BY };
  if (VALIDATE_RE.test(content)) return { relationRole: EDGE_TYPES.VALIDATED_BY };
  // 5) agentRole 이 검증/비판 코치면 기본 검증.
  const agentRole = String(md.agentRole ?? row?.agentRole ?? '').toLowerCase();
  if (/검증|비판|논점|critic|review/.test(agentRole)) return { relationRole: EDGE_TYPES.VALIDATED_BY };
  // 끝까지 애매 → 검증 + 분류 검토 필요.
  return { relationRole: EDGE_TYPES.VALIDATED_BY, needsReview: true };
}

// processSteps 안의 검증/상호평가 로그를 convert 가 읽는 interactions 형태로 변환한다.
function extractInteractions(aiMessages, nameToSlot) {
  const interactions = [];
  const roleOf = (row, fallbackName) => {
    if (Number.isInteger(row?.agentIndex)) return slotToRole(row.agentIndex);
    const nm = row?.agentName || fallbackName;
    if (nm && nameToSlot.has(String(nm))) return slotToRole(nameToSlot.get(String(nm)));
    return null;
  };

  aiMessages.forEach((m) => {
    const ps = m?.processSteps;
    if (!ps || typeof ps !== 'object') return;

    // 검증 단계: validatedAnswers[*] → fromRole 이 자기 답변을 검증한 노드(stage=VALIDATION).
    asArray(ps.validatedAnswers).forEach((row) => {
      const fromRole = roleOf(row, m.senderName);
      const content = text(row.validation || row.content || row.feedback || row.answer);
      if (fromRole && content) {
        interactions.push({
          fromRole, targetRole: fromRole, relationRole: EDGE_TYPES.VALIDATED_BY, content,
        });
      }
    });

    // 상호평가: peerFeedback[*] → metadata 우선으로 반박/검증/예시 분류.
    asArray(ps.peerFeedback || ps.peerFeedbacks).forEach((row) => {
      const fromRole = roleOf(row, row?.fromAgentName);
      const targetRole = roleOf(
        { agentIndex: row?.toAgentIndex, agentName: row?.toAgentName },
        row?.toAgentName,
      );
      const content = text(row.content || row.feedback);
      if (fromRole && targetRole && content) {
        const { relationRole, needsReview } = classifyFeedback(row, content);
        interactions.push({ fromRole, targetRole, relationRole, needsReview, content });
      }
    });
  });

  return interactions;
}

/**
 * 방 + 채팅 히스토리 → Obsidian 그래프.
 * @param {{title?:string, agents?:any[]}} room
 * @param {Array} chatLogs  학습메이트 getChatHistory 응답(메시지 배열)
 * @returns {{nodes:object[], edges:object[], centerNodeId:string, stats:object}|null}
 *   변환할 로그가 없으면 null(호출측이 빈/오류 상태로 처리 — 자동 legacy 금지).
 */
export function convertChatLogsToObsidianGraph(room, chatLogs) {
  const messages = asArray(chatLogs);
  if (messages.length === 0) return null;

  // 가장 최근 사용자 질문을 중심 노드로 사용(없으면 첫 메시지).
  const lastUser = [...messages].reverse().find((m) => m && m.sender === 'USER');
  const question = text(lastUser?.content) || text(messages.find((m) => m?.content)?.content);

  const agents = asArray(room?.agents);
  const nameToSlot = new Map();
  agents.forEach((ag, i) => { if (ag?.name) nameToSlot.set(String(ag.name), i); });

  const aiMessages = messages.filter((m) => m && m.sender !== 'USER');
  if (aiMessages.length === 0) return null; // 질문만 있고 답변이 없으면 그래프 없음

  const interactions = extractInteractions(aiMessages, nameToSlot);

  const graph = convertMindMapToObsidianGraph({
    question,
    agents,
    messages: aiMessages,
    interactions,
    sourceId: 'studymate-room',
    sourceType: 'multi_agent_chat',
  });

  if (!graph || !Array.isArray(graph.nodes) || graph.nodes.length <= 1) return graph || null;
  return graph;
}
