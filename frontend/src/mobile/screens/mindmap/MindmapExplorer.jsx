import React, { useMemo, useState } from 'react';
import { Search } from 'lucide-react';
import BottomSheet from '../../components/BottomSheet';
import ListRow from '../../components/ListRow';
import MarkdownText from '../../components/MarkdownText';
import { EmptyState } from '../../components/ScreenState';
import MindmapCanvas from './MindmapCanvas';
import MindmapLegend from './MindmapLegend';
import { matchNodes } from './mindmapModel';
import { canShowRelationOnly, neighborhoodOf, visibleGraphOf } from './mindmapSelection';

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

function relationSentenceOf(node, relation) {
  const isOutgoing = relation.direction === 'outgoing';
  const source = isOutgoing ? node : relation.neighbor;
  const target = isOutgoing ? relation.neighbor : node;
  return `${source.title} → [${relation.label}] ${target.title}`;
}

function SelectedNodeCard({ node, relations, onSelectNode, onOpenDetail, onClear }) {
  return (
    <section className="mobile-card mobile-mindmap-selection" aria-live="polite" data-selected-node={node.id}>
      <div className="mobile-mindmap-selection__header">
        <div className="mobile-mindmap-selection__title">
          <p className="mobile-card__meta">{node.typeLabel}</p>
          <h3>{node.title}</h3>
        </div>
        <button type="button" className="mobile-mindmap-selection__clear" onClick={onClear}>
          선택 해제
        </button>
      </div>

      {relations.length === 0 ? (
        <p className="mobile-card__meta">연결된 노드가 없습니다.</p>
      ) : (
        <ul className="mobile-mindmap-selection__relations" aria-label={`연결 ${relations.length}개`}>
          {relations.map((relation) => (
            <li key={relation.edgeId}>
              <button type="button" onClick={() => onSelectNode(relation.neighbor)}>
                <span className="mobile-mindmap-selection__neighbor">{relationSentenceOf(node, relation)}</span>
              </button>
            </li>
          ))}
        </ul>
      )}

      <button type="button" className="mobile-mindmap-selection__detail" onClick={onOpenDetail}>
        노드 설명 보기
      </button>
    </section>
  );
}

function RelationOnlyToggle({ isChecked, isAvailable, onChange }) {
  return (
    <label className={`mobile-mindmap-explorer__filter${isAvailable ? '' : ' is-disabled'}`}>
      <input
        type="checkbox"
        checked={isChecked}
        disabled={!isAvailable}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span>선택 관계만 보기</span>
      {!isAvailable && <span className="mobile-mindmap-explorer__filter-hint">노드를 선택하면 사용할 수 있어요</span>}
    </label>
  );
}

function relationFitKeyOf(fitKey, neighborhood) {
  return `${fitKey}:relation:${neighborhood.selectedNodeId}`;
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
  const [selectedNodeId, setSelectedNodeId] = useState(null);
  const [detailNode, setDetailNode] = useState(null);
  const [relationOnly, setRelationOnly] = useState(false);

  const matches = useMemo(() => matchNodes(view?.nodes || [], keyword), [view, keyword]);
  const highlightIds = useMemo(() => new Set(matches.map((node) => node.id)), [matches]);
  const neighborhood = useMemo(() => neighborhoodOf(view, selectedNodeId), [view, selectedNodeId]);
  const selectedNode = view?.nodes.find((node) => node.id === neighborhood.selectedNodeId) || null;
  const isRelationOnlyAvailable = canShowRelationOnly(neighborhood);
  const isRelationOnly = relationOnly && isRelationOnlyAvailable;
  const visibleView = useMemo(
    () => visibleGraphOf(view, neighborhood, isRelationOnly),
    [view, neighborhood, isRelationOnly]
  );
  const canvasFitKey = isRelationOnly ? relationFitKeyOf(fitKey, neighborhood) : fitKey;

  const selectNode = (node) => setSelectedNodeId(node.id);
  const clearSelection = () => {
    setSelectedNodeId(null);
    setRelationOnly(false);
  };

  const focusNode = (node) => {
    setFocusTarget({ id: node.id, requestedAt: Date.now() });
    selectNode(node);
  };

  const pickSearchResult = (node) => {
    focusNode(node);
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
      <RelationOnlyToggle
        isChecked={isRelationOnly}
        isAvailable={isRelationOnlyAvailable}
        onChange={setRelationOnly}
      />

      <MindmapCanvas
        view={visibleView}
        fitKey={canvasFitKey}
        highlightIds={highlightIds}
        neighborhood={neighborhood}
        focusTarget={focusTarget}
        onSelectNode={selectNode}
        onClearSelection={clearSelection}
      />
      {selectedNode && (
        <SelectedNodeCard
          node={selectedNode}
          relations={neighborhood.relations}
          onSelectNode={focusNode}
          onOpenDetail={() => setDetailNode(selectedNode)}
          onClear={clearSelection}
        />
      )}
      <MindmapLegend view={view} />

      <SearchSheet
        isOpen={isSearchOpen}
        onClose={() => setSearchOpen(false)}
        keyword={keyword}
        onKeywordChange={setKeyword}
        matches={matches}
        onPick={pickSearchResult}
      />
      <NodeSheet node={detailNode} onClose={() => setDetailNode(null)} />
    </div>
  );
}
