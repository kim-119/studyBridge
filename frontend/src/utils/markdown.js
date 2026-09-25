/**
 * 마크다운 제거 — UI/학습일지/피드백에 마크다운 기호가 절대 보이지 않도록 sanitize.
 * ai07에서도 정리하지만 프론트에서 2중 방어한다.
 */
export function sanitizeMarkdownText(value) {
  if (value == null) return '';
  let s = String(value);
  // 0) qwen3 등 추론 토큰 블록 통째로 제거(내용 포함). 닫는 태그가 없어도 끝까지 잘라낸다.
  s = s.replace(/<think>[\s\S]*?<\/think>/gi, '');
  s = s.replace(/<(think|thinking|reasoning|analysis)>[\s\S]*$/gi, '');
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
  // 표: 구분선(|---|:--:|) 제거 + 셀 구분 파이프를 ' · '로(테두리 파이프는 제거).
  //  ※ \s 대신 [ \t]을 써야 한다. \s는 \n까지 먹어 행이 서로 붙는 버그가 난다.
  s = s.replace(/^[ \t]*\|?[ \t:|-]*-[ \t:|-]*\|?[ \t]*$/gm, ''); // |---|:-:| 구분행
  s = s.replace(/^[ \t]*\|(.+?)\|[ \t]*$/gm, (_m, inner) =>
    inner.split('|').map((c) => c.trim()).filter(Boolean).join('  ·  '));
  s = s.replace(/^\s*[-*+]\s+/gm, '');                            // - / * 목록
  s = s.replace(/<[^>]+>/g, '');                                  // 남은 HTML 태그
  s = s.replace(/\*\*/g, '').replace(/(^|\s)#{1,6}(\s)/g, '$1$2'); // 잔여 기호
  // HTML 엔티티 복원(순서 주의: &amp;를 마지막에)
  s = s.replace(/&nbsp;/gi, ' ').replace(/&lt;/gi, '<').replace(/&gt;/gi, '>')
       .replace(/&quot;/gi, '"').replace(/&#39;/gi, "'").replace(/&amp;/gi, '&');
  // PDF 자료 인용 가독화: [Page N] 구획과 • 글머리표를 줄바꿈으로 분리(원문 한 줄 덤프 방지)
  s = s.replace(/[ \t]*\[\s*page\s*(\d+)\s*\][ \t]*/gi, '\n\n[Page $1]\n');
  s = s.replace(/[ \t]*•[ \t]*/g, '\n• ');                        // 가운뎃점 글머리표 → 줄 단위
  s = s.replace(/[ \t]{2,}/g, ' ');                               // 연속 공백
  s = s.replace(/[ \t]+$/gm, '');                                 // 줄 끝 공백
  s = s.replace(/^[ \t]+/gm, '');                                 // 줄 앞 공백
  s = s.replace(/\n{3,}/g, '\n\n');                               // 3줄+ 빈줄 → 2줄
  return s.trim();
}

export function sanitizeList(arr) {
  return (Array.isArray(arr) ? arr : []).map(sanitizeMarkdownText).filter(Boolean);
}
