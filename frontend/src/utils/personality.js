// 성격/말투(personality style) 단일 소스 — AI 학습메이트·기본 질문·에이전트/방 생성·토론 설정 등
// 모든 성격 선택 UI는 반드시 이 7개만 노출한다(두 번째 UI 기준으로 통일).
// payload에는 label 문자열이 아니라 canonical key를 우선 전달하고, temperature를 number로 보장한다.

export const PERSONALITY_STYLE_OPTIONS = [
  { key: 'default', label: '기본값', description: '기본 스타일과 말투', temperature: 0.5 },
  { key: 'professional', label: '전문적', description: '정제되어 있고 정확함', temperature: 0.35 },
  { key: 'friendly', label: '친근함', description: '따뜻하고 수다스러움', temperature: 0.65 },
  { key: 'honest', label: '솔직함', description: '직설적이면서도 격려함', temperature: 0.45 },
  { key: 'unique', label: '독특함', description: '유쾌하고 상상력이 풍부함', temperature: 0.8 },
  { key: 'efficient', label: '효율적', description: '간결하고 꾸밈없음', temperature: 0.25 },
  { key: 'cynical', label: '냉소적', description: '비꼬면서 비판적임', temperature: 0.55 },
];

// 구버전/타화면 라벨 → canonical key. 저장된 레거시 값이 와도 UI가 깨지지 않게 흡수한다.
export const LEGACY_PERSONALITY_MAP = {
  '기본': 'default', '기본값': 'default', '차분하게': 'default', '차분한': 'default', 'calm': 'default',
  '전문적으로': 'professional', '전문적': 'professional', 'professional': 'professional',
  '친근하게': 'friendly', '친근함': 'friendly', 'friendly': 'friendly',
  '솔직하게': 'honest', '솔직함': 'honest', '정직하게': 'honest', 'honest': 'honest',
  '유머러스하게': 'unique', '독특함': 'unique', 'humorous': 'unique', 'creative': 'unique',
  '효율적': 'efficient', '간결하게': 'efficient', 'concise': 'efficient', 'efficient': 'efficient',
  '냉철하게': 'cynical', '냉소적': 'cynical', '비판적으로': 'cynical', '엄격하게': 'cynical',
  'strict': 'cynical', 'cold': 'cynical', 'sardonic': 'cynical', 'critical': 'cynical', 'cynical': 'cynical',
};

const OPTION_BY_KEY = Object.fromEntries(PERSONALITY_STYLE_OPTIONS.map((o) => [o.key, o]));
export const PERSONALITY_KEYS = PERSONALITY_STYLE_OPTIONS.map((o) => o.key);
export const DEFAULT_PERSONALITY_KEY = 'default';

// 임의 입력(key/한글 라벨/레거시 라벨)을 canonical key로 정규화한다. 미상이면 'default'.
export const normalizePersonalityKey = (raw) => {
  const v = String(raw ?? '').trim();
  if (!v) return DEFAULT_PERSONALITY_KEY;
  if (OPTION_BY_KEY[v]) return v;
  const low = v.toLowerCase();
  if (OPTION_BY_KEY[low]) return low;
  return LEGACY_PERSONALITY_MAP[v] || LEGACY_PERSONALITY_MAP[low] || DEFAULT_PERSONALITY_KEY;
};

// canonical key → 7종 한글 라벨(기본값/전문적/...). 표시는 항상 이 라벨만 쓴다.
export const personalityLabel = (raw) => (OPTION_BY_KEY[normalizePersonalityKey(raw)] || OPTION_BY_KEY.default).label;
export const personalityOption = (raw) => OPTION_BY_KEY[normalizePersonalityKey(raw)] || OPTION_BY_KEY.default;

// temperature는 number로 보장하고 0.0~1.2로 clamp한다(문자열 전달로 인한 파싱 실패 방지).
export const clampTemperature = (n) => {
  const x = typeof n === 'number' ? n : Number(n);
  if (!Number.isFinite(x)) return null;
  return Math.min(1.2, Math.max(0, x));
};

// 우선순위: 사용자가 명시 조절한 값 → 성격 기본값 → 시스템 기본(0.5).
export const personalityTemperature = (raw, override) => {
  const ov = clampTemperature(override);
  if (ov != null) return ov;
  const opt = personalityOption(raw);
  return clampTemperature(opt.temperature) ?? 0.5;
};
