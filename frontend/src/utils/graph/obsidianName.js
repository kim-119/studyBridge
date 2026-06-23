// ─────────────────────────────────────────────────────────────────────────────
// Obsidian 노트 이름/라벨/태그 정규화 유틸.
//  · Wikilink([[...]]) 안전, 파일명 안전, 중복 회피를 한곳에서 처리한다.
// ─────────────────────────────────────────────────────────────────────────────

const FS_UNSAFE = /[\\/:*?"<>|#^[\]]/g;

/**
 * Obsidian 노트 이름으로 정규화한다.
 *  trim → 줄바꿈/연속공백 축약 → wikilink/금지문자 제거 → 60자 축약.
 * @param {string} raw
 * @param {number} [maxLen=60]
 * @returns {string}
 */
export function normalizeObsidianName(raw, maxLen = 60) {
  let s = String(raw ?? '').replace(/[\r\n]+/g, ' ').trim();
  s = s.replace(/\[\[|\]\]/g, '').replace(/\|/g, ' ');
  s = s.replace(FS_UNSAFE, ' ');
  s = s.replace(/\s+/g, ' ').trim();
  if (!s) s = '제목 없음';
  if (s.length > maxLen) s = `${s.slice(0, maxLen - 1).trim()}…`;
  return s;
}

/**
 * 이름 집합에서 중복을 피해 유니크한 이름을 만든다(이미 있으면 " (2)" suffix).
 * @param {string} name
 * @param {Set<string>} used  소문자 키 집합(호출측에서 누적)
 * @returns {string}
 */
export function dedupeObsidianName(name, used) {
  const base = name;
  let candidate = base;
  let n = 2;
  while (used.has(candidate.toLowerCase())) {
    candidate = `${base} (${n})`;
    n += 1;
  }
  used.add(candidate.toLowerCase());
  return candidate;
}

/**
 * 짧은 라벨(노드 위 표시용). 한글/영문 혼합 안전 말줄임.
 * @param {string} raw
 * @param {number} [maxLen=24]
 * @returns {string}
 */
export function makeShortLabel(raw, maxLen = 24) {
  const s = String(raw ?? '').replace(/[\r\n]+/g, ' ').replace(/\s+/g, ' ').trim();
  if (s.length <= maxLen) return s;
  return `${s.slice(0, maxLen - 1).trim()}…`;
}

/**
 * 태그 정규화. '#' 제거, 공백→'-', 중복 제거, 기본 태그 부여.
 * @param {string[]} raw
 * @returns {string[]}
 */
export function normalizeTags(raw) {
  const base = ['StudyBridge', 'mindmap'];
  const all = [...base, ...(Array.isArray(raw) ? raw : [])];
  const seen = new Set();
  const out = [];
  for (const t of all) {
    const clean = String(t ?? '').replace(/^#+/, '').replace(/\s+/g, '-').trim();
    if (!clean) continue;
    const key = clean.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(clean);
  }
  return out;
}

/**
 * 원문/축약/병기 라벨을 aliases 로 보존(검색 인덱스용).
 * @param {string} label
 * @param {string} shortLabel
 * @param {string[]} [extra]
 * @returns {string[]}
 */
export function buildAliases(label, shortLabel, extra = []) {
  const seen = new Set();
  const out = [];
  for (const a of [label, shortLabel, ...extra]) {
    const s = String(a ?? '').replace(/\s+/g, ' ').trim();
    if (!s) continue;
    const key = s.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(s);
  }
  return out;
}
