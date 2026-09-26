import React, { useMemo } from 'react';

const CODE_FENCE = /```([a-zA-Z0-9+-]*)\n?([\s\S]*?)```/g;

function splitCodeBlocks(source) {
  const blocks = [];
  let lastIndex = 0;
  let match;

  CODE_FENCE.lastIndex = 0;
  while ((match = CODE_FENCE.exec(source)) !== null) {
    if (match.index > lastIndex) {
      blocks.push({ type: 'text', value: source.slice(lastIndex, match.index) });
    }
    blocks.push({ type: 'code', language: match[1] || '', value: match[2].replace(/\n$/, '') });
    lastIndex = CODE_FENCE.lastIndex;
  }

  if (lastIndex < source.length) {
    blocks.push({ type: 'text', value: source.slice(lastIndex) });
  }

  // 아직 닫히지 않은 코드 펜스(스트리밍 중)는 코드 블록으로 미리 보여준다.
  const trailing = blocks[blocks.length - 1];
  if (trailing?.type === 'text') {
    const open = trailing.value.match(/```([a-zA-Z0-9+-]*)\n?([\s\S]*)$/);
    if (open) {
      blocks[blocks.length - 1] = { type: 'text', value: trailing.value.slice(0, open.index) };
      blocks.push({ type: 'code', language: open[1] || '', value: open[2], isStreaming: true });
    }
  }

  return blocks;
}

function renderInline(text, keyPrefix) {
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*|__[^_]+__|\*[^*\n]+\*)/g;
  const parts = text.split(pattern).filter((part) => part !== '' && part !== undefined);

  return parts.map((part, index) => {
    const key = `${keyPrefix}-${index}`;

    if (part.startsWith('`') && part.endsWith('`')) {
      return (
        <code key={key} className="mobile-md__inline-code">
          {part.slice(1, -1)}
        </code>
      );
    }

    if ((part.startsWith('**') && part.endsWith('**')) || (part.startsWith('__') && part.endsWith('__'))) {
      return <strong key={key}>{part.slice(2, -2)}</strong>;
    }

    if (part.startsWith('*') && part.endsWith('*') && part.length > 2) {
      return <em key={key}>{part.slice(1, -1)}</em>;
    }

    return <React.Fragment key={key}>{part}</React.Fragment>;
  });
}

function renderTextBlock(value, keyPrefix) {
  const lines = value.split('\n');
  const nodes = [];
  let listBuffer = [];

  const flushList = () => {
    if (listBuffer.length === 0) return;
    nodes.push(
      <ul key={`${keyPrefix}-ul-${nodes.length}`} className="mobile-md__list">
        {listBuffer.map((item, index) => (
          <li key={`${keyPrefix}-li-${index}`}>{renderInline(item, `${keyPrefix}-li-${index}`)}</li>
        ))}
      </ul>
    );
    listBuffer = [];
  };

  lines.forEach((line, index) => {
    const heading = line.match(/^\s{0,3}(#{1,6})\s+(.*)$/);
    const listItem = line.match(/^\s*[-*+]\s+(.*)$/);
    const ordered = line.match(/^\s*\d+\.\s+(.*)$/);

    if (heading) {
      flushList();
      nodes.push(
        <p key={`${keyPrefix}-h-${index}`} className="mobile-md__heading">
          {renderInline(heading[2], `${keyPrefix}-h-${index}`)}
        </p>
      );
      return;
    }

    if (listItem || ordered) {
      listBuffer.push((listItem || ordered)[1]);
      return;
    }

    flushList();

    if (line.trim() === '') return;

    nodes.push(
      <p key={`${keyPrefix}-p-${index}`} className="mobile-md__paragraph">
        {renderInline(line, `${keyPrefix}-p-${index}`)}
      </p>
    );
  });

  flushList();
  return nodes;
}

export default function MarkdownText({ children }) {
  const blocks = useMemo(() => splitCodeBlocks(String(children ?? '')), [children]);

  return (
    <div className="mobile-md">
      {blocks.map((block, index) =>
        block.type === 'code' ? (
          <pre key={`code-${index}`} className="mobile-md__code">
            {block.language && <span className="mobile-md__code-lang">{block.language}</span>}
            <code>{block.value}</code>
          </pre>
        ) : (
          <React.Fragment key={`text-${index}`}>{renderTextBlock(block.value, `t${index}`)}</React.Fragment>
        )
      )}
    </div>
  );
}
