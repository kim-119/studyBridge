import React, { useEffect, useMemo, useState } from 'react';
import { Search } from 'lucide-react';
import BottomSheet from '../../components/BottomSheet';
import ListRow from '../../components/ListRow';
import ScreenState, { EmptyState, ErrorState } from '../../components/ScreenState';
import MobileScreen from '../../shell/MobileScreen';
import { materialService } from '../../../services/api';
import { useAsync } from '../../data/useAsync';
import MindmapCanvas from './MindmapCanvas';
import { buildMindmapView, matchNodes, parseMindmapGraph } from './mindmapModel';

export default function MindmapScreen() {
  const [selectedId, setSelectedId] = useState(null);
  const [keyword, setKeyword] = useState('');
  const [isSearchOpen, setSearchOpen] = useState(false);
  const [focusNodeId, setFocusNodeId] = useState(null);
  const [selectedNode, setSelectedNode] = useState(null);

  const archive = useAsync(() => materialService.getArchiveItems(null, 'MINDMAP'), []);

  const mindmaps = useMemo(() => archive.data?.materials || [], [archive.data]);

  useEffect(() => {
    if (!selectedId && mindmaps.length > 0) setSelectedId(mindmaps[0].materialId);
  }, [mindmaps, selectedId]);

  const detail = useAsync(
    async () => (selectedId ? materialService.getMaterialDetail(selectedId) : null),
    [selectedId],
    { immediate: Boolean(selectedId) }
  );

  const view = useMemo(() => {
    const graph = parseMindmapGraph(detail.data);
    return graph ? buildMindmapView(graph) : null;
  }, [detail.data]);

  const matches = useMemo(() => matchNodes(view?.nodes || [], keyword), [view, keyword]);
  const highlightIds = useMemo(() => new Set(matches.map((node) => node.id)), [matches]);

  return (
    <MobileScreen
      title="마인드맵"
      showBackButton
      actions={
        <button
          type="button"
          className="mobile-app-bar__action"
          aria-label="노드 검색"
          onClick={() => setSearchOpen(true)}
        >
          <Search size={22} />
        </button>
      }
    >
      <ScreenState
        query={archive}
        loadingLabel="마인드맵을 불러오는 중입니다"
        emptyWhen={() => mindmaps.length === 0}
        emptyMessage="저장된 마인드맵이 없습니다. 웹에서 학습 대화를 마인드맵으로 저장하면 여기에 표시됩니다."
      >
        <>
          <div className="mobile-field">
            <label className="mobile-field__label" htmlFor="mindmap-topic">
              학습 주제
            </label>
            <select
              id="mindmap-topic"
              className="mobile-field__input"
              value={selectedId ?? ''}
              onChange={(event) => {
                setSelectedId(Number(event.target.value));
                setKeyword('');
                setSelectedNode(null);
              }}
            >
              {mindmaps.map((material) => (
                <option key={material.materialId} value={material.materialId}>
                  {material.title}
                </option>
              ))}
            </select>
          </div>

          {detail.isError ? (
            <ErrorState message={detail.errorMessage} onRetry={detail.reload} />
          ) : view?.error ? (
            <EmptyState message={view.error} />
          ) : view ? (
            <>
              <p className="mobile-card__meta">
                노드 {view.nodes.length} · 연결 {view.edges.length} · 깊이 {view.depth}
                {keyword && ` · 검색 ${matches.length}건`}
              </p>

              <MindmapCanvas
                view={view}
                highlightIds={highlightIds}
                focusNodeId={focusNodeId}
                onSelectNode={setSelectedNode}
              />
            </>
          ) : (
            <EmptyState message="그래프 데이터를 불러오지 못했습니다." />
          )}
        </>
      </ScreenState>

      <BottomSheet title="노드 검색" isOpen={isSearchOpen} onClose={() => setSearchOpen(false)}>
        <input
          className="mobile-search"
          type="search"
          value={keyword}
          placeholder="개념 이름으로 검색"
          onChange={(event) => setKeyword(event.target.value)}
        />

        <ul className="mobile-list">
          {matches.slice(0, 30).map((node) => (
            <li key={node.id}>
              <ListRow
                title={node.label}
                subtitle={node.type}
                onClick={() => {
                  setFocusNodeId(node.id);
                  setSelectedNode(node);
                  setSearchOpen(false);
                }}
              />
            </li>
          ))}
        </ul>

        {keyword && matches.length === 0 && <EmptyState message="일치하는 노드가 없습니다." />}
      </BottomSheet>

      <BottomSheet
        title={selectedNode?.label || '노드'}
        isOpen={Boolean(selectedNode)}
        onClose={() => setSelectedNode(null)}
      >
        <p className="mobile-card__meta">유형 {selectedNode?.type}</p>
        <p className="mobile-paragraph">
          {selectedNode?.detail || '이 노드에는 추가 설명이 없습니다.'}
        </p>
      </BottomSheet>
    </MobileScreen>
  );
}
