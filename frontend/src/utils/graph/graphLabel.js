// ─────────────────────────────────────────────────────────────────────────────
// 그래프 라벨 글자(grapheme) 단위 처리 유틸 (단일 출처).
//  · text.length(코드유닛) 대신 "사용자 눈에 보이는 한 글자(grapheme cluster)" 기준으로
//    분리/측정/절단한다. 한글 조합 문자·이모지·특수문자에서 깨지지 않게 한다.
//  · Intl.Segmenter 가 있으면 그것을 쓰고, 없으면 Array.from(코드포인트) 로 폴백한다.
//  · 순수 함수 — 회귀 테스트는 graphLabel.test.mjs 참고.
//  · 의존성 없음(node 단독 실행 가능): 노드 타입은 graphTypes 의 문자열 값과 동일한 리터럴로 비교.
// ─────────────────────────────────────────────────────────────────────────────

// Segmenter 는 비싸므로 1회 생성해 재사용(매 호출 new 금지).
let _segmenter = null;
function getSegmenter() {
  if (_segmenter !== null) return _segmenter;
  if (typeof Intl !== 'undefined' && typeof Intl.Segmenter === 'function') {
    try {
      _segmenter = new Intl.Segmenter('ko', { granularity: 'grapheme' });
    } catch {
      _segmenter = false;
    }
  } else {
    _segmenter = false;
  }
  return _segmenter;
}

/** 문자열을 grapheme 단위 배열로 분리. 빈 입력은 []. */
export function splitByGrapheme(text = '') {
  const value = String(text ?? '');
  if (!value) return [];
  const seg = getSegmenter();
  if (seg) return Array.from(seg.segment(value), (part) => part.segment);
  // 폴백: 코드포인트 단위(이모지 surrogate pair 보존). 조합 문자는 합쳐지지 않지만 깨지진 않음.
  return Array.from(value);
}

/** grapheme 개수(글자 수 카운터/제한 계산용). */
export function countGraphemes(text = '') {
  return splitByGrapheme(text).length;
}

/**
 * grapheme 단위 말줄임. maxChars 초과면 maxChars 글자 + '…'.
 *  · 공백 등 양끝 정리는 호출부(normalizeGraphLabel)에서 수행.
 */
export function truncateByGrapheme(text, maxChars = 12) {
  const chars = splitByGrapheme(text);
  if (chars.length <= maxChars) return chars.join('');
  return `${chars.slice(0, Math.max(0, maxChars)).join('')}…`;
}

/** 라벨 정규화: 개행/연속 공백을 단일 공백으로, 양끝 트림. (노드 라벨은 1줄 표시 전제) */
export function normalizeGraphLabel(text = '') {
  return String(text ?? '').replace(/\s+/g, ' ').trim();
}

// 노드 타입별 기본 표시 글자 수(grapheme). 질문은 중심이라 길게, 개념/오류는 짧게.
//  · graphTypes.NODE_TYPES 값(question/agent/answer/concept/validation/rebuttal/example/source/...)
//    + spec 상의 professor/verification/error/user 별칭을 함께 매핑한다.
export const NODE_LABEL_LIMIT = Object.freeze({
  question: 22,
  agent: 12, // 교수
  professor: 12,
  answer: 14,
  concept: 12,
  validation: 14,
  verification: 14,
  rebuttal: 14,
  example: 12,
  source: 14, // 근거/자료
  error: 10,
  roadmap: 16,
  planner: 16,
  tag: 12,
  user: 12,
  default: 12,
});

export function labelLimitForType(type) {
  return NODE_LABEL_LIMIT[type] ?? NODE_LABEL_LIMIT.default;
}

/**
 * 화면 표시용 라벨: 정규화 → 타입별(또는 지정) 글자 수로 grapheme 절단.
 * @param {string} text
 * @param {{ type?:string, maxChars?:number }} [options]
 */
export function getDisplayLabel(text, options = {}) {
  const normalized = normalizeGraphLabel(text);
  if (!normalized) return '';
  const max = options.maxChars != null ? options.maxChars : labelLimitForType(options.type);
  return truncateByGrapheme(normalized, max);
}

/** 툴팁(전체) 라벨: 절단하지 않되 정규화만. 매우 길면 안전하게 상한(120 grapheme). */
export function getTooltipLabel(text) {
  const normalized = normalizeGraphLabel(text);
  return truncateByGrapheme(normalized, 120);
}

/**
 * 줌/중요도/타입에 따른 라벨 표시 여부(LOD). 선택/질문 노드는 항상 표시.
 * @param {number} zoom   현재 줌 배율(1=100%)
 * @param {number} importance 0~1 정규화 중요도(없으면 0)
 * @param {string} nodeType
 * @param {boolean} [selected]
 * @returns {boolean}
 */
export function getLabelVisibilityLevel(zoom, importance = 0, nodeType, selected = false) {
  if (selected) return true;
  if (nodeType === 'question') return true;

  const imp = Number.isFinite(importance) ? importance : 0;
  if (zoom < 0.55) {
    return imp >= 0.8 && nodeType === 'answer';
  }
  if (zoom < 0.85) {
    return ['answer', 'agent', 'professor'].includes(nodeType);
  }
  if (zoom < 1.2) {
    return ['answer', 'agent', 'concept', 'professor'].includes(nodeType) && imp >= 0.35;
  }
  return true;
}
