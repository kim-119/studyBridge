import React, { useMemo } from 'react';
import './markdownText.css';

const CODE_FENCE = /```([\w+#.-]*)[^\S\n]*\n?([\s\S]*?)```/g;
const OPEN_CODE_FENCE = /```([\w+#.-]*)[^\S\n]*\n?([\s\S]*)$/;
const LINE_BREAK_TAG = /<br\s*\/?>/gi;
const INLINE_TOKEN =
  /(`[^`\n]+`|\*\*\*[^\s*][^\n]*?\*\*\*|\*\*[^\s*][^\n]*?\*\*|__[^\s_][^\n]*?__|\*[^\s*](?:[^*\n]*[^\s*])?\*|\[[^\]\n]+\]\([^)\s]+\))/g;
const LINK_TOKEN = /^\[([^\]\n]+)\]\([^)\s]+\)$/;
const STRAY_EMPHASIS = /\*\*+|__+/g;

const HORIZONTAL_RULE = /^\s{0,3}([-*_])(\s*\1){2,}\s*$/;
const TABLE_SEPARATOR = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;
const TABLE_ROW = /^\s*\|(.+)\|\s*$/;
const HEADING = /^\s{0,3}(#{1,6})(\s*)(.*?)(?:\s+#+)?\s*$/;
const QUOTE = /^\s{0,3}(?:>\s?)+(.*)$/;
const UNORDERED_ITEM = /^\s*[-*+•]\s+(.*)$/;
const ORDERED_ITEM = /^\s*(\d+)[.)]\s+(.*)$/;

function splitCodeBlocks(source) {
  const blocks = [];
  let lastIndex = 0;
  let match;

  CODE_FENCE.lastIndex = 0;
  while ((match = CODE_FENCE.exec(source)) !== null) {
    if (match.index > lastIndex) blocks.push({ type: 'text', value: source.slice(lastIndex, match.index) });
    blocks.push({ type: 'code', language: match[1] || '', value: match[2].replace(/\n$/, '') });
    lastIndex = CODE_FENCE.lastIndex;
  }
  if (lastIndex < source.length) blocks.push({ type: 'text', value: source.slice(lastIndex) });

  return withStreamingCodeBlock(blocks);
}

function withStreamingCodeBlock(blocks) {
  const trailing = blocks[blocks.length - 1];
  if (trailing?.type !== 'text') return blocks;

  const open = trailing.value.match(OPEN_CODE_FENCE);
  if (!open) return blocks;

  return [
    ...blocks.slice(0, -1),
    { type: 'text', value: trailing.value.slice(0, open.index) },
    { type: 'code', language: open[1] || '', value: open[2], isStreaming: true },
  ];
}

function isWrappedBy(part, marker) {
  return part.length > marker.length * 2 && part.startsWith(marker) && part.endsWith(marker);
}

function renderInlineToken(part, key) {
  if (isWrappedBy(part, '`')) {
    return (
      <code key={key} className="mobile-md__inline-code">
        {part.slice(1, -1)}
      </code>
    );
  }
  if (isWrappedBy(part, '***')) {
    return (
      <strong key={key}>
        <em>{renderInline(part.slice(3, -3), key)}</em>
      </strong>
    );
  }
  if (isWrappedBy(part, '**') || isWrappedBy(part, '__')) {
    return <strong key={key}>{renderInline(part.slice(2, -2), key)}</strong>;
  }
  if (isWrappedBy(part, '*')) {
    return <em key={key}>{renderInline(part.slice(1, -1), key)}</em>;
  }

  const link = part.match(LINK_TOKEN);
  if (link) return <React.Fragment key={key}>{link[1]}</React.Fragment>;

  return <React.Fragment key={key}>{part.replace(STRAY_EMPHASIS, '')}</React.Fragment>;
}

function renderInline(text, keyPrefix) {
  return text
    .split(INLINE_TOKEN)
    .filter((part) => part !== '' && part !== undefined)
    .map((part, index) => renderInlineToken(part, `${keyPrefix}-${index}`));
}

function headingTextOf(line) {
  const heading = line.match(HEADING);
  if (!heading) return null;
  const [, hashes, spacing, text] = heading;
  const isHeading = spacing.length > 0 || hashes.length >= 2;
  return isHeading ? text : null;
}

function tableCellsOf(line) {
  const row = line.match(TABLE_ROW);
  if (!row) return null;
  return row[1]
    .split('|')
    .map((cell) => cell.trim())
    .filter(Boolean)
    .join(' · ');
}

function classifyLine(line) {
  if (line.trim() === '') return { kind: 'blank' };
  if (HORIZONTAL_RULE.test(line)) return { kind: 'rule' };
  if (TABLE_SEPARATOR.test(line) && line.includes('-') && line.includes('|')) return { kind: 'blank' };

  const quote = line.match(QUOTE);
  if (quote) return { kind: 'quote', text: quote[1] };

  const headingText = headingTextOf(line);
  if (headingText !== null) return headingText ? { kind: 'heading', text: headingText } : { kind: 'blank' };

  const unordered = line.match(UNORDERED_ITEM);
  if (unordered) return { kind: 'unordered', text: unordered[1] };

  const ordered = line.match(ORDERED_ITEM);
  if (ordered) return { kind: 'ordered', text: ordered[2], number: Number(ordered[1]) };

  const tableText = tableCellsOf(line);
  if (tableText) return { kind: 'paragraph', text: tableText };

  return { kind: 'paragraph', text: line };
}

function quoteLineText(text) {
  const inner = classifyLine(text);
  return inner.text ?? '';
}

function renderGroup(group, key) {
  if (group.kind === 'quote') {
    return (
      <blockquote key={key} className="mobile-md__quote">
        {group.items.map((item, index) => (
          <p key={`${key}-${index}`} className="mobile-md__paragraph">
            {renderInline(quoteLineText(item), `${key}-${index}`)}
          </p>
        ))}
      </blockquote>
    );
  }

  const ListTag = group.kind === 'ordered' ? 'ol' : 'ul';
  return (
    <ListTag key={key} className="mobile-md__list" start={group.start}>
      {group.items.map((item, index) => (
        <li key={`${key}-${index}`}>{renderInline(item, `${key}-${index}`)}</li>
      ))}
    </ListTag>
  );
}

function renderSingleLine(line, key) {
  if (line.kind === 'rule') return <hr key={key} className="mobile-md__rule" />;
  if (line.kind === 'heading') {
    return (
      <p key={key} className="mobile-md__heading">
        {renderInline(line.text, key)}
      </p>
    );
  }
  return (
    <p key={key} className="mobile-md__paragraph">
      {renderInline(line.text, key)}
    </p>
  );
}

const GROUPED_KINDS = new Set(['quote', 'unordered', 'ordered']);

function renderTextBlock(value, keyPrefix) {
  const lines = value.replace(LINE_BREAK_TAG, '\n').split('\n').map(classifyLine);
  const nodes = [];
  let group = null;

  const flushGroup = () => {
    if (group) nodes.push(renderGroup(group, `${keyPrefix}-g${nodes.length}`));
    group = null;
  };

  lines.forEach((line, index) => {
    if (GROUPED_KINDS.has(line.kind)) {
      if (group?.kind !== line.kind) flushGroup();
      group = group || { kind: line.kind, items: [], start: line.number };
      if (line.text) group.items.push(line.text);
      return;
    }
    flushGroup();
    if (line.kind !== 'blank') nodes.push(renderSingleLine(line, `${keyPrefix}-l${index}`));
  });

  flushGroup();
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
