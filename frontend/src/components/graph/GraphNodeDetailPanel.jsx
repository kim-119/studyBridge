import React, { useState } from 'react';
import {
  colorForNode, labelForNodeType, displayLabelForNode, displayLabelForEdge,
} from '../../utils/graph/graphTypes';
import { makeWikilink } from '../../utils/graph/wikilink';
import { copyTextToClipboard } from '../../utils/graph/graphExportActions';

// 노드 1개의 표시 라벨(참조 리스트용): 본문 스니펫이 아니라 semanticRole 기반.
const nodeRefLabel = (n) => displayLabelForNode(n) || n?.shortLabel || n?.label || '항목';

// 본문 preview + 전체 보기 토글(spec 24). 긴 body 가 잘리지 않게 한다.
function ExpandableBody({ body }) {
  const [open, setOpen] = useState(false);
  const text = String(body || '');
  const isLong = text.length > 280 || text.split('\n').length > 8;
  if (!text) return <div className="obsg-detail-text">추가 내용이 없습니다.</div>;
  return (
    <div>
      <div className={`obsg-detail-text${isLong && !open ? ' is-clamped' : ''}`}>{text}</div>
      {isLong && (
        <button type="button" className="obsg-detail-more" onClick={() => setOpen((v) => !v)}>
          {open ? '접기' : '전체 보기'}
        </button>
      )}
    </div>
  );
}

// 우측 상세 패널: 노드 전문 + backlink/outgoing + 태그 + 액션.
//  · 어떤 필드가 깨져도 패널 전체가 죽지 않게 방어한다(spec 57).
export default function GraphNodeDetailPanel({ node, linkIndex, onSelectNode, onCenterNode, onClose }) {
  if (!node) return null;
  const backlinks = linkIndex?.backlinks?.get(node.id) || [];
  const outgoing = linkIndex?.outgoing?.get(node.id) || [];
  const color = colorForNode(node.type);
  const needsReview = node.metadata && node.metadata.needsReview === true;

  const copyMarkdown = async () => {
    try {
      const md = `### ${makeWikilink(node.obsidianName, node.title)}\n\n${node.body || ''}`;
      const ok = await copyTextToClipboard(md);
      if (!ok) window.alert('복사에 실패했습니다.');
    } catch {
      window.alert('복사에 실패했습니다.');
    }
  };

  return (
    <div className="obsg-detail" role="complementary" aria-label="노드 상세">
      <div className="obsg-detail-head">
        <div style={{ minWidth: 0 }}>
          <div className="obsg-detail-title" title={node.title || node.label}>{node.title || node.label || nodeRefLabel(node)}</div>
          <div className="obsg-detail-badges">
            <span className="obsg-badge" style={{ background: color }}>{labelForNodeType(node.type)}</span>
            {needsReview && <span className="obsg-badge obsg-badge-review">분류 검토 필요</span>}
          </div>
        </div>
        <button type="button" className="obsg-icon-btn" onClick={onClose} aria-label="닫기">✕</button>
      </div>

      <div className="obsg-detail-body">
        <ExpandableBody body={node.body} />

        {Array.isArray(node.tags) && node.tags.length > 0 && (
          <div className="obsg-detail-section">
            <h5>태그</h5>
            <div className="obsg-tag-list">
              {node.tags.map((t) => <span key={t} className="obsg-tag" title={`#${t}`}>#{t}</span>)}
            </div>
          </div>
        )}

        {outgoing.length > 0 && (
          <div className="obsg-detail-section">
            <h5>이 노드가 연결한 항목</h5>
            {outgoing.map(({ edge, node: nb }) => {
              const rel = displayLabelForEdge(edge);
              const label = nodeRefLabel(nb);
              return (
                <button
                  type="button"
                  key={edge.id}
                  className="obsg-link-item"
                  onClick={() => onSelectNode?.(nb)}
                  title={`[${rel}] ${nb.title || label}`}
                >
                  <span className="obsg-link-rel">[{rel}]</span>
                  <span className="obsg-link-text">{nb.title || label}</span>
                </button>
              );
            })}
          </div>
        )}

        {backlinks.length > 0 && (
          <div className="obsg-detail-section">
            <h5>이 노드를 참조하는 항목</h5>
            {backlinks.map(({ edge, node: nb }) => {
              const rel = displayLabelForEdge(edge);
              const label = nodeRefLabel(nb);
              return (
                <button
                  type="button"
                  key={edge.id}
                  className="obsg-link-item"
                  onClick={() => onSelectNode?.(nb)}
                  title={`[${rel}] ${nb.title || label}`}
                >
                  <span className="obsg-link-rel">[{rel}]</span>
                  <span className="obsg-link-text">{nb.title || label}</span>
                </button>
              );
            })}
          </div>
        )}

        <div className="obsg-detail-section">
          <h5>마인드맵 링크명</h5>
          <code className="obsg-detail-wikilink">{makeWikilink(node.obsidianName)}</code>
        </div>
      </div>

      <div className="obsg-detail-actions">
        <button type="button" className="obsg-btn" onClick={() => onCenterNode?.(node)}>이 노드 중심으로</button>
        <button type="button" className="obsg-btn" onClick={copyMarkdown}>Markdown 복사</button>
      </div>
    </div>
  );
}
