const LEADING_HEADING = /^\s{0,3}#{1,6}\s+/;
const LEADING_QUOTE = /^\s*(?:>\s?)+/;
const LEADING_BULLET = /^\s*[-*+•]\s+/;
const LEADING_NUMBER = /^\s*\d+[.)]\s+/;
const BOLD_MARKERS = /\*\*+/g;
const WRAPPING_UNDERSCORES = /^__(.+)__$/;
const INLINE_CODE = /`([^`]*)`/g;
const LINK = /\[([^\]]+)\]\([^)]*\)/g;
const WRAPPING_ASTERISKS = /^\*+|\*+$/g;
const WHITESPACE = /\s+/g;

export function cleanNodeLabel(raw) {
  return String(raw ?? '')
    .replace(WHITESPACE, ' ')
    .replace(LINK, '$1')
    .replace(INLINE_CODE, '$1')
    .replace(BOLD_MARKERS, '')
    .replace(LEADING_HEADING, '')
    .replace(LEADING_QUOTE, '')
    .replace(LEADING_BULLET, '')
    .replace(LEADING_NUMBER, '')
    .replace(WRAPPING_ASTERISKS, '')
    .trim()
    .replace(WRAPPING_UNDERSCORES, '$1')
    .trim();
}
