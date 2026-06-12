/**
 * 마크다운 제거 — UI/학습일지/피드백에 마크다운 기호가 절대 보이지 않도록 sanitize.
 * ai07에서도 정리하지만 프론트에서 2중 방어한다.
 */
export function sanitizeMarkdownText(value) {
  if (value == null) return '';
  let s = String(value);
  s = s.replace(/```[a-zA-Z0-9]*\n?/g, '').replace(/```/g, ''); // code fence
  s = s.replace(/`([^`]*)`/g, '$1');                              // inline code
  s = s.replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1');                 // image
  s = s.replace(/\[([^\]]+)\]\([^)]*\)/g, '$1');                  // link
  s = s.replace(/\*\*([^*]+)\*\*/g, '$1');                        // **bold**
  s = s.replace(/__([^_]+)__/g, '$1');                            // __bold__
  s = s.replace(/\*([^*\n]+)\*/g, '$1');                          // *italic*
  s = s.replace(/(^|[^_\w])_([^_\n]+)_(?=[^_\w]|$)/g, '$1$2');    // _italic_
  s = s.replace(/^\s{0,3}#{1,6}\s*/gm, '');                       // # 제목
  s = s.replace(/^\s{0,3}>\s?/gm, '');                            // > 인용
  s = s.replace(/^\s*[-*+]\s+/gm, '');                            // - / * 목록
  s = s.replace(/<[^>]+>/g, '');                                  // HTML 태그
  s = s.replace(/\*\*/g, '').replace(/(^|\s)#{1,6}(\s)/g, '$1$2'); // 잔여 기호
  s = s.replace(/[ \t]{2,}/g, ' ');
  return s.trim();
}

export function sanitizeList(arr) {
  return (Array.isArray(arr) ? arr : []).map(sanitizeMarkdownText).filter(Boolean);
}
