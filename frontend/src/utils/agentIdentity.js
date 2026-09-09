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
 *
 * pinnedAgentId: 사용자가 방금 "이 교수에게 질문"으로 클릭한 agent 의 stable id.
 *  이름은 identity 가 아니다 — 같은 이름의 교수가 둘 이상이면 이름 매칭은 항상 배열 첫 번째로 붕괴한다.
 *  멘션 후보 중 이 id 를 가진 agent 가 있으면 그 agent 를 대상으로 확정한다(클릭 identity 우선).
 *  후보에 없으면(멘션을 지웠거나 다른 교수로 바꿨거나 방을 옮김) 무시한다 → stale 핀이 남지 않는다.
 */
export function resolveMentionTarget(text, roomAgents, pinnedAgentId = null) {
  const msg = String(text || '');
  const agents = Array.isArray(roomAgents) ? roomAgents : [];
  const all = { scope: 'all', slot: null, agent: null, agentId: null, agentName: null };
  if (msg.includes(MENTION_ALL)) return all;
  const mentioned = [];
  agents.forEach((ag, slot) => {
    const name = normName(ag?.name);
    if (!name || !msg.includes(`@${name}`)) return;
    mentioned.push({ scope: 'single', slot, agent: ag, agentId: agentIdOf(ag), agentName: name });
  });
  if (!mentioned.length) return all;
  const pinned = pinnedAgentId == null
    ? null
    : mentioned.find((m) => sameAgentId(m.agentId, pinnedAgentId));
  if (pinned) return pinned;
  return mentioned.reduce((best, m) => (!best || m.agentName.length > best.agentName.length ? m : best), null);
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

/**
 * 입력창 draft 의 맨 앞 교수 멘션만 새 멘션으로 교체한다(없으면 앞에 붙인다).
 *  · 클릭("이 교수에게 질문")/멘션 팝업/직접 타이핑이 모두 같은 문자열 규칙을 쓰도록 여기 둔다.
 *  · 교체 대상은 방의 실제 교수 이름 + '@모두' 뿐이라, 사용자가 쓴 본문은 보존된다.
 *  · 1번 → 2번 → 3번으로 빠르게 바꿔도 이전 멘션이 남지 않는다(stale target 방지).
 */
export function applyMentionPrefill(draft, mention, roomAgents) {
  const current = String(draft || '');
  const names = (Array.isArray(roomAgents) ? roomAgents : []).map((a) => normName(a?.name)).filter(Boolean);
  const esc = names.map((n) => n.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  const pattern = esc.length ? `^@(?:${esc.join('|')}|모두)\\s*` : '^@모두\\s*';
  const re = new RegExp(pattern);
  if (re.test(current)) return current.replace(re, mention);
  return current ? `${mention}${current}` : mention;
}
