// ─────────────────────────────────────────────────────────────────────────────
// 학습메이트 방(AI 룸)의 채팅 히스토리 → Obsidian GraphNode/GraphEdge 변환 adapter.
//  · 옵시디언 페이지가 source of truth 로 사용하는 단일 진입점.
//  · 방 1개의 로그만 받아 그래프를 만든다(방 섞임 금지는 호출측 requestSeq 가드가 담당).
//  · 검증/반박은 AI 메시지의 processSteps(validatedAnswers/peerFeedback)에서 best-effort 로 뽑는다.
//  · 실제 노드/간선 생성은 검증된 convertMindMapToObsidianGraph 를 재사용한다.
// ─────────────────────────────────────────────────────────────────────────────
import { convertMindMapToObsidianGraph } from './mindmapToObsidianGraph';

const ROLE_ORDER = ['theory', 'book', 'ai'];
const slotToRole = (slot) => ROLE_ORDER[((Number(slot) || 0) % 3 + 3) % 3];

const asArray = (v) => (Array.isArray(v) ? v : []);
const text = (v) => String(v ?? '').trim();

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

    // 검증 단계: validatedAnswers[*] → fromRole 이 자기 답변을 검증한 노드.
    asArray(ps.validatedAnswers).forEach((row) => {
      const fromRole = roleOf(row, m.senderName);
      const content = text(row.validation || row.content || row.feedback || row.answer);
      if (fromRole && content) {
        interactions.push({ fromRole, targetRole: fromRole, relationLabel: '검증', content });
      }
    });

    // 상호평가/반박: peerFeedback[*] → fromRole 이 targetRole 답변에 보충/반박.
    asArray(ps.peerFeedback || ps.peerFeedbacks).forEach((row) => {
      const fromRole = roleOf(row, row?.fromAgentName);
      const targetRole = roleOf(
        { agentIndex: row?.toAgentIndex, agentName: row?.toAgentName },
        row?.toAgentName,
      );
      const content = text(row.content || row.feedback);
      if (fromRole && targetRole && content) {
        const isRebut = /반박|반대|오류|허점|틀렸|문제/.test(content);
        interactions.push({
          fromRole,
          targetRole,
          relationLabel: isRebut ? '반박' : '보완',
          content,
        });
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
