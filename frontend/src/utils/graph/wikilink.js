// ─────────────────────────────────────────────────────────────────────────────
// Wikilink 생성 + Markdown/YAML/Mermaid escape 유틸.
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Obsidian Wikilink 생성. alias 가 target 과 다르면 [[target|alias]].
 * @param {string} target
 * @param {string} [alias]
 * @returns {string}
 */
export function makeWikilink(target, alias) {
  const t = String(target ?? '').replace(/\[\[|\]\]/g, '').trim();
  if (!t) return '';
  const a = alias != null ? String(alias).trim() : '';
  if (a && a !== t) return `[[${t}|${a}]]`;
  return `[[${t}]]`;
}

/** YAML frontmatter 안전 문자열(따옴표 escape + 항상 큰따옴표 감쌈). */
export function escapeYaml(raw) {
  const s = String(raw ?? '').replace(/[\r\n]+/g, ' ').replace(/"/g, '\\"');
  return `"${s}"`;
}

/** Markdown 표/heading/code 충돌 방지(파이프·백틱·heading 기호 escape). */
export function escapeMarkdown(raw) {
  return String(raw ?? '')
    .replace(/\|/g, '\\|')
    .replace(/`/g, '\\`');
}

/** Mermaid 라벨 안전(따옴표/줄바꿈/대괄호 제거·치환). */
export function escapeMermaidLabel(raw) {
  return String(raw ?? '')
    .replace(/[\r\n]+/g, ' ')
    .replace(/"/g, '″')
    .replace(/[[\]{}]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}
