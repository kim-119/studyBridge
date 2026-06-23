import React from 'react';

// 공통 그래프 툴바. PDF 관련 버튼은 의도적으로 전혀 두지 않는다.
export default function GraphToolbar({
  mode, onSetMode, onFit, onCenterQuestion, onToggleSearch, searchOpen,
  filters, onToggleFilter, depth, onSetDepth,
  onExportMarkdown, onExportCanvas, extraActions,
}) {
  return (
    <div className="obsg-toolbar" role="toolbar" aria-label="그래프 도구">
      <button type="button" className={`obsg-btn${mode === 'local' ? ' is-active' : ''}`} onClick={() => onSetMode('local')}>Local Graph</button>
      <button type="button" className={`obsg-btn${mode === 'global' ? ' is-active' : ''}`} onClick={() => onSetMode('global')}>Global Graph</button>
      <button type="button" className="obsg-btn" onClick={onFit}>화면에 맞춤</button>
      <button type="button" className="obsg-btn" onClick={onCenterQuestion}>현재 질문 중심</button>
      <button type="button" className={`obsg-btn${searchOpen ? ' is-active' : ''}`} onClick={onToggleSearch}>검색</button>

      {mode === 'local' && (
        <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#cbd5e1' }}>
          깊이 {depth}
          <input
            type="range" min={0} max={4} value={depth}
            onChange={(e) => onSetDepth(Number(e.target.value))}
            aria-label="Local Graph 깊이"
            style={{ width: 80 }}
          />
        </label>
      )}

      <button type="button" className={`obsg-btn${filters.showAnswers ? ' is-active' : ''}`} onClick={() => onToggleFilter('showAnswers')}>답변</button>
      <button type="button" className={`obsg-btn${filters.showValidation ? ' is-active' : ''}`} onClick={() => onToggleFilter('showValidation')}>검증</button>
      <button type="button" className={`obsg-btn${filters.showRebuttal ? ' is-active' : ''}`} onClick={() => onToggleFilter('showRebuttal')}>반박</button>
      <button type="button" className={`obsg-btn${filters.showConcepts ? ' is-active' : ''}`} onClick={() => onToggleFilter('showConcepts')}>개념</button>

      <span className="obsg-spacer" />

      <button type="button" className="obsg-btn" onClick={onExportMarkdown}>Markdown 내보내기</button>
      <button type="button" className="obsg-btn" onClick={onExportCanvas}>Canvas 내보내기</button>
      {extraActions}
    </div>
  );
}
