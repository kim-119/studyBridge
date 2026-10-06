// 에이전트별 고유 색상 — 전 화면(말풍선 보더/이름/아바타/상세모달/좌측 카드) 일관성의 단일 소스.
// agentId 기반 결정적 매핑: index = hash(agentId) % palette.length.
// 같은 에이전트는 어디서 렌더되든 항상 같은 색을 받는다.

export const AGENT_COLOR_PALETTE = [
  { border: '#16A34A', bg: '#E8F5E9', text: '#15803D' }, // green
  { border: '#2563EB', bg: '#E3F2FD', text: '#1D4ED8' }, // blue
  { border: '#EA580C', bg: '#FFF3E0', text: '#C2410C' }, // orange
  { border: '#9333EA', bg: '#F3E8FF', text: '#7E22CE' }, // purple
  { border: '#0891B2', bg: '#E0F7FA', text: '#0E7490' }, // teal
  { border: '#DB2777', bg: '#FCE7F3', text: '#BE185D' }, // pink
  { border: '#CA8A04', bg: '#FEF9C3', text: '#A16207' }, // amber
  { border: '#4F46E5', bg: '#EEF2FF', text: '#4338CA' }, // indigo
];

// 문자열/숫자 키를 안정적인 양의 정수 해시로 변환 (결정적).
export const hashAgentKey = (key) => {
  const str = String(key ?? '');
  let h = 0;
  for (let i = 0; i < str.length; i += 1) {
    h = (Math.imul(31, h) + str.charCodeAt(i)) | 0;
  }
  return Math.abs(h);
};

// 에이전트 식별 키: agentId > id > name 순. (서브 에이전트는 안정적 id가 없을 수 있어 name으로 폴백)
export const agentColorKey = (agent) =>
  agent?.agentId ?? agent?.id ?? agent?.name ?? '';

// 키(또는 에이전트 객체) → 팔레트 색.
export const getAgentColor = (keyOrAgent) => {
  const key =
    keyOrAgent && typeof keyOrAgent === 'object' ? agentColorKey(keyOrAgent) : keyOrAgent;
  return AGENT_COLOR_PALETTE[hashAgentKey(key) % AGENT_COLOR_PALETTE.length];
};
