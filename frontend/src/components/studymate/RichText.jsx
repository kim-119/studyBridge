import React from 'react';

// 경량 마크다운 렌더러 (react-markdown 의존성 없이 raw **, ###, ```, - 리스트 노출 방지).
// 채팅 탭과 "교수님들과 대화" 뷰가 동일한 렌더링을 쓰도록 공유한다.
const renderInlineNodes = (line, keyBase) => {
  const nodes = [];
  const regex = /\*\*(.+?)\*\*|`([^`]+)`/g;
  let last = 0;
  let m;
  let i = 0;
  while ((m = regex.exec(line)) !== null) {
    if (m.index > last) nodes.push(line.slice(last, m.index));
    if (m[1] != null) nodes.push(<strong key={`${keyBase}-b${i}`}>{m[1]}</strong>);
    else nodes.push(<code key={`${keyBase}-c${i}`} style={{ background: 'rgba(0,0,0,0.06)', padding: '1px 4px', borderRadius: 4, fontSize: '0.92em' }}>{m[2]}</code>);
    last = m.index + m[0].length;
    i += 1;
  }
  if (last < line.length) nodes.push(line.slice(last));
  return nodes;
};

const RichText = ({ text }) => {
  const src = String(text ?? '');
  if (!src) return null;
  const segments = src.split('```');
  return (
    <>
      {segments.map((seg, si) => {
        if (si % 2 === 1) {
          const nl = seg.indexOf('\n');
          const lang = nl > -1 ? seg.slice(0, nl).trim() : '';
          const isLang = nl > -1 && /^[a-zA-Z0-9+#.-]{0,15}$/.test(lang);
          const code = isLang ? seg.slice(nl + 1) : seg;
          return (
            <pre key={`code-${si}`} style={{ background: '#0f172a', color: '#e2e8f0', padding: '10px 12px', borderRadius: 8, overflowX: 'auto', fontSize: 12, lineHeight: 1.5, margin: '6px 0' }}>
              <code>{code.replace(/\n$/, '')}</code>
            </pre>
          );
        }
        const lines = seg.split('\n');
        return (
          <span key={`txt-${si}`}>
            {lines.map((rawLine, li) => {
              const key = `${si}-${li}`;
              const heading = rawLine.match(/^(#{1,6})\s+(.*)$/);
              if (heading) {
                return <div key={key} style={{ fontWeight: 700, margin: '4px 0' }}>{renderInlineNodes(heading[2], key)}</div>;
              }
              const list = rawLine.match(/^\s*[-*]\s+(.*)$/);
              const content = list ? `• ${list[1]}` : rawLine;
              return (
                <React.Fragment key={key}>
                  {renderInlineNodes(content, key)}
                  {li < lines.length - 1 ? <br /> : null}
                </React.Fragment>
              );
            })}
          </span>
        );
      })}
    </>
  );
};

export default RichText;
