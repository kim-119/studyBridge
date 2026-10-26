import React from 'react';
import {
  Maximize2, Crosshair, Search, Tag as TagIcon, Settings2, FileDown, LayoutGrid, Circle, Globe, Monitor,
} from 'lucide-react';

// ─────────────────────────────────────────────────────────────────────────────
// 그래프 위에 떠 있는 컴팩트 floating 툴바(Obsidian 느낌: 낮은 대비, 아이콘 중심).
//  · PDF 관련 버튼은 전혀 두지 않는다. 필터/표시/힘은 설정 패널(기어)로 분리.
// ─────────────────────────────────────────────────────────────────────────────
function TBtn({ active, onClick, title, children }) {
  return (
    <button type="button" className={`obsg-tb-btn${active ? ' is-active' : ''}`} onClick={onClick} title={title} aria-label={title} aria-pressed={!!active}>
      {children}
    </button>
  );
}

export default function GraphToolbar({
  mode, onSetMode, onFit, onCenterQuestion, onToggleSearch, searchOpen,
  depth, onSetDepth,
  showEdgeLabels, onToggleEdgeLabels,
  settingsOpen, onToggleSettings,
  presentation, onTogglePresentation,
  onExportMarkdown, onExportCanvas, extraActions,
}) {
  return (
    <div className="obsg-toolbar" role="toolbar" aria-label="그래프 도구">
      <div className="obsg-tb-group">
        <TBtn active={mode === 'local'} onClick={() => onSetMode('local')} title="Local Graph (L)"><Circle size={15} /></TBtn>
        <TBtn active={mode === 'global'} onClick={() => onSetMode('global')} title="Global Graph (G)"><Globe size={15} /></TBtn>
      </div>

      {mode === 'local' && (
        <label className="obsg-tb-depth" title="Local Graph 깊이">
          <span>깊이 {depth}</span>
          <input type="range" min={0} max={4} value={depth} onChange={(e) => onSetDepth(Number(e.target.value))} aria-label="Local Graph 깊이" />
        </label>
      )}

      <div className="obsg-tb-group">
        <TBtn active={searchOpen} onClick={onToggleSearch} title="검색 (Ctrl/Cmd+F)"><Search size={15} /></TBtn>
        <TBtn active={showEdgeLabels} onClick={onToggleEdgeLabels} title="간선 이름 (E)"><TagIcon size={15} /></TBtn>
        <TBtn onClick={onFit} title="화면에 맞춤 (0)"><Maximize2 size={15} /></TBtn>
        <TBtn onClick={onCenterQuestion} title="현재 질문 중심"><Crosshair size={15} /></TBtn>
      </div>

      <div className="obsg-tb-group">
        <TBtn active={presentation} onClick={onTogglePresentation} title="발표 모드 (라벨·간선 강조, 범례 접힘)"><Monitor size={15} /></TBtn>
        <TBtn onClick={onExportMarkdown} title="Markdown 내보내기"><FileDown size={15} /></TBtn>
        <TBtn onClick={onExportCanvas} title="Canvas 내보내기"><LayoutGrid size={15} /></TBtn>
        <TBtn active={settingsOpen} onClick={onToggleSettings} title="그래프 설정 (Filters/Groups/Display/Forces)"><Settings2 size={15} /></TBtn>
      </div>

      {extraActions ? <div className="obsg-tb-group obsg-tb-extra">{extraActions}</div> : null}
    </div>
  );
}
