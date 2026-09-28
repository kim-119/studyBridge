import React, { useMemo, useState } from 'react';
import { Search } from 'lucide-react';
import BottomSheet from '../../components/BottomSheet';
import ListRow from '../../components/ListRow';
import MarkdownText from '../../components/MarkdownText';
import { EmptyState } from '../../components/ScreenState';
import MindmapCanvas from './MindmapCanvas';
import MindmapLegend from './MindmapLegend';
import { matchNodes } from './mindmapModel';

const SEARCH_RESULT_LIMIT = 30;

function SearchSheet({ isOpen, onClose, keyword, onKeywordChange, matches, onPick }) {
  return (
    <BottomSheet title="노드 검색" isOpen={isOpen} onClose={onClose}>
      <input
        className="mobile-search"
        type="search"
        value={keyword}
        placeholder="개념 이름으로 검색"
        onChange={(event) => onKeywordChange(event.target.value)}
      />

      <ul className="mobile-list">
        {matches.slice(0, SEARCH_RESULT_LIMIT).map((node) => (
          <li key={node.id}>
            <ListRow title={node.label} subtitle={node.typeLabel} onClick={() => onPick(node)} />
          </li>
        ))}
      </ul>

      {keyword && matches.length === 0 && <EmptyState message="일치하는 노드가 없습니다." />}
    </BottomSheet>
  );
}

function NodeSheet({ node, onClose }) {
  return (
    <BottomSheet title={node?.title || '노드'} isOpen={Boolean(node)} onClose={onClose}>
      <p className="mobile-card__meta">유형 {node?.typeLabel}</p>
      {node?.detail ? (
        <MarkdownText>{node.detail}</MarkdownText>
      ) : (
        <p className="mobile-paragraph">이 노드에는 추가 설명이 없습니다.</p>
      )}
    </BottomSheet>
  );
}

export default function MindmapExplorer({ view, fitKey, toolbarActions = null }) {
  const [keyword, setKeyword] = useState('');
  const [isSearchOpen, setSearchOpen] = useState(false);
  const [focusTarget, setFocusTarget] = useState(null);
  const [selectedNode, setSelectedNode] = useState(null);

  const matches = useMemo(() => matchNodes(view?.nodes || [], keyword), [view, keyword]);
  const highlightIds = useMemo(() => new Set(matches.map((node) => node.id)), [matches]);

  const pickSearchResult = (node) => {
    setFocusTarget({ id: node.id, requestedAt: Date.now() });
    setSelectedNode(node);
    setSearchOpen(false);
  };

  return (
    <div className="mobile-mindmap-explorer">
      <div className="mobile-mindmap-explorer__toolbar">
        <p className="mobile-card__meta">
          노드 {view.nodes.length} · 연결 {view.edges.length} · 깊이 {view.depth}
          {keyword && ` · 검색 ${matches.length}건`}
        </p>
        <button type="button" className="mobile-app-bar__action" aria-label="노드 검색" onClick={() => setSearchOpen(true)}>
          <Search size={20} />
        </button>
        {toolbarActions}
      </div>

      <MindmapCanvas
        view={view}
        fitKey={fitKey}
        highlightIds={highlightIds}
        focusTarget={focusTarget}
        onSelectNode={setSelectedNode}
      />
      <MindmapLegend view={view} />

      <SearchSheet
        isOpen={isSearchOpen}
        onClose={() => setSearchOpen(false)}
        keyword={keyword}
        onKeywordChange={setKeyword}
        matches={matches}
        onPick={pickSearchResult}
      />
      <NodeSheet node={selectedNode} onClose={() => setSelectedNode(null)} />
    </div>
  );
}
