// 멀티에이전트("교수님들과 대화") Agent Identity 공통 리졸버.
//
// 불변조건: 사용자가 지정한 agent = 요청 targetAgentId = 백엔드가 답한 agentId = 화면에 붙는 교수.
//  · identity 의 최종 기준은 stable id(DB PK: agent.id / 이벤트 agentId)다.
//  · 배열 위치(index)는 "화면 슬롯(sprite 자리)"일 뿐 identity 가 아니다. 이벤트 → 슬롯 변환은
//    반드시 이 모듈을 거친다(agentId → 이름 → (레거시) 1-based agentIndex 순).
//  · 백엔드 SSE 의 agentIndex 는 1-based 이고, 대상 지정 시 "필터된 배열" 위치라 신뢰할 수 없다.
//    프론트 내부에서 쓰는 슬롯은 항상 0-based 방 배열 위치(agentSlot)다.

export const MENTION_ALL = '@모두';

const normName = (s) => String(s ?? '').trim();

/** 방 agent 객체의 stable id (Spring AgentDTO.Response.id 또는 agentId). */
export const agentIdOf = (agent) => {
  if (!agent || typeof agent !== 'object') return null;
  const v = agent.agentId ?? agent.id ?? null;
  return v == null || v === '' ? null : v;
};

/** 두 id 가 같은 agent 를 가리키는가(문자열/숫자 혼용 방어: "37" === 37). */
export const sameAgentId = (a, b) => a != null && b != null && String(a) !== '' && String(a) === String(b);

/**
 * SSE/응답 이벤트가 어느 방 agent 의 것인지 → 0-based 방 배열 슬롯. 못 찾으면 -1.
 * 우선순위: agentId → agentName → agentSlot(프론트 정규화값) → 레거시 1-based agentIndex.
 */
export function resolveRoomAgentSlot(roomAgents, evt) {
  const agents = Array.isArray(roomAgents) ? roomAgents : [];
  if (!evt || typeof evt !== 'object') return -1;
  const evId = evt.agentId ?? evt.agent_id;
  if (evId != null && String(evId) !== '') {
    const bySlot = agents.findIndex((ag) => sameAgentId(agentIdOf(ag), evId));
    if (bySlot >= 0) return bySlot;
  }
  const evName = normName(evt.agentName ?? evt.agent_name);
  if (evName) {
    const byName = agents.findIndex((ag) => normName(ag?.name) === evName);
    if (byName >= 0) return byName;
  }
  if (Number.isInteger(evt.agentSlot) && evt.agentSlot >= 0 && (agents.length === 0 || evt.agentSlot < agents.length)) {
    return evt.agentSlot;
  }
  const idx = Number(evt.agentIndex ?? evt.agent_index);
  if (Number.isInteger(idx) && idx >= 1 && (agents.length === 0 || idx <= agents.length)) return idx - 1;
  return -1;
}

/** 이벤트에 agent 를 식별할 수 있는 필드가 하나라도 있는가. */
export const hasAgentIdentity = (evt) => {
  if (!evt || typeof evt !== 'object') return false;
  const id = evt.agentId ?? evt.agent_id;
  const name = normName(evt.agentName ?? evt.agent_name);
  const idx = evt.agentIndex ?? evt.agent_index ?? evt.agentSlot;
  return (id != null && String(id) !== '') || !!name || idx != null;
};

/**
 * 입력 문구의 @멘션을 방 agent 로 해석한다(클릭 "이 교수에게 질문" 프리필과 직접 타이핑 모두 동일 경로).
 *  · '@모두' 포함 → all.
 *  · '@{agent.name}' 이 포함된 agent 가 있으면 single(이름이 긴 쪽 우선: "@AI 교수" vs "@AI 교수 2").
 *  · 없으면 all(기존 멀티에이전트 협업 모드 유지).
 */
export function resolveMentionTarget(text, roomAgents) {
  const msg = String(text || '');
  const agents = Array.isArray(roomAgents) ? roomAgents : [];
  const all = { scope: 'all', slot: null, agent: null, agentId: null, agentName: null };
  if (msg.includes(MENTION_ALL)) return all;
  let best = null;
  agents.forEach((ag, slot) => {
    const name = normName(ag?.name);
    if (!name || !msg.includes(`@${name}`)) return;
    if (!best || name.length > best.agentName.length) {
      best = { scope: 'single', slot, agent: ag, agentId: agentIdOf(ag), agentName: name };
    }
  });
  return best || all;
}

/**
 * single scope 에서 "이 이벤트가 대상 agent 의 것인가".
 *  · target 이 없거나 all → 항상 true.
 *  · 이벤트가 대상 슬롯으로 해석되면 true.
 *  · 식별 정보가 전혀 없으면 보존(true) — 단일 대상의 유일 답변일 수 있다.
 *  · 식별 정보가 있는데 다른 agent 로 해석되면 false(양성 불일치만 드롭).
 */
export function isEventForTarget(roomAgents, target, evt) {
  if (!target || target.scope !== 'single') return true;
  const slot = resolveRoomAgentSlot(roomAgents, evt);
  if (slot >= 0) return slot === target.slot;
  return !hasAgentIdentity(evt);
}
