import React from 'react';
import { colorForNode, labelForNodeType } from '../../utils/graph/graphTypes';
import { makeWikilink } from '../../utils/graph/wikilink';
import { copyTextToClipboard } from '../../utils/graph/graphExportActions';

// 우측 상세 패널: 노드 전문 + backlink/outgoing + 태그 + 액션.
export default function GraphNodeDetailPanel({ node, linkIndex, onSelectNode, onCenterNode, onClose }) {
  if (!node) return null;
  const backlinks = linkIndex?.backlinks?.get(node.id) || [];
  const outgoing = linkIndex?.outgoing?.get(node.id) || [];
  const color = colorForNode(node.type);

  const copyMarkdown = async () => {
    const md = `### ${makeWikilink(node.obsidianName, node.title)}\n\n${node.body || ''}`;
    const ok = await copyTextToClipboard(md);
    if (!ok) window.alert('복사에 실패했습니다.');
  };

  return (
    <div className="obsg-detail" role="complementary" aria-label="노드 상세">
      <div className="obsg-detail-head">
        <div style={{ minWidth: 0 }}>
          <div className="obsg-detail-title">{node.title || node.label}</div>
          <span className="obsg-badge" style={{ background: color }}>{labelForNodeType(node.type)}</span>
        </div>
        <button type="button" className="obsg-icon-btn" onClick={onClose} aria-label="닫기">✕</button>
      </div>
      <div className="obsg-detail-body">
        {node.body ? node.body : '추가 내용이 없습니다.'}

        {Array.isArray(node.tags) && node.tags.length > 0 && (
          <div className="obsg-detail-section">
            <h5>태그</h5>
            <div>{node.tags.map((t) => <span key={t} className="obsg-tag">#{t}</span>)}</div>
          </div>
        )}

        {outgoing.length > 0 && (
          <div className="obsg-detail-section">
            <h5>이 노드가 연결한 항목</h5>
            {outgoing.map(({ edge, node: nb }) => (
              <button type="button" key={edge.id} className="obsg-link-item" onClick={() => onSelectNode?.(nb)}>
                {edge.label ? `${edge.label} · ` : ''}{nb.shortLabel || nb.label}
              </button>
            ))}
          </div>
        )}

        {backlinks.length > 0 && (
          <div className="obsg-detail-section">
            <h5>이 노드를 참조하는 항목</h5>
            {backlinks.map(({ edge, node: nb }) => (
              <button type="button" key={edge.id} className="obsg-link-item" onClick={() => onSelectNode?.(nb)}>
                {nb.shortLabel || nb.label}
              </button>
            ))}
          </div>
        )}

        <div className="obsg-detail-section">
          <h5>Obsidian 링크명</h5>
          <code style={{ fontSize: 12, color: '#a5b4fc' }}>{makeWikilink(node.obsidianName)}</code>
        </div>
      </div>
      <div style={{ display: 'flex', gap: 6, padding: 10, borderTop: '1px solid #1f2937' }}>
        <button type="button" className="obsg-btn" onClick={() => onCenterNode?.(node)} style={{ flex: 1 }}>이 노드 중심으로</button>
        <button type="button" className="obsg-btn" onClick={copyMarkdown} style={{ flex: 1 }}>Markdown 복사</button>
      </div>
    </div>
  );
}
