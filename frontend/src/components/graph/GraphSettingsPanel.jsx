import React, { useMemo, useState } from 'react';
import { X } from 'lucide-react';
import { NODE_TYPES, colorForNode, labelForNodeType } from '../../utils/graph/graphTypes';

// ─────────────────────────────────────────────────────────────────────────────
// Obsidian Graph Settings 스타일 패널. Filters / Groups / Display / Forces 4섹션.
//  · 각 섹션 접기/펼치기. 우측 floating drawer. PDF 관련 항목 없음.
// ─────────────────────────────────────────────────────────────────────────────
const FILTER_ROWS = [
  { key: 'showAgents', type: NODE_TYPES.AGENT, label: '교수' },
  { key: 'showAnswers', type: NODE_TYPES.ANSWER, label: '답변' },
  { key: 'showConcepts', type: NODE_TYPES.CONCEPT, label: '개념' },
  { key: 'showValidation', type: NODE_TYPES.VALIDATION, label: '검증' },
  { key: 'showRebuttal', type: NODE_TYPES.REBUTTAL, label: '반박' },
  { key: 'showExamples', type: NODE_TYPES.EXAMPLE, label: '예시' },
  { key: 'showSources', type: NODE_TYPES.SOURCE, label: '자료' },
];

function Section({ title, children, defaultOpen = true }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="obsg-set-sec">
      <button type="button" className="obsg-set-sec-head" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <span className={`obsg-set-caret${open ? ' is-open' : ''}`}>▸</span>{title}
      </button>
      {open && <div className="obsg-set-sec-body">{children}</div>}
    </div>
  );
}

function Slider({ label, value, min, max, step = 0.1, onChange, fmt }) {
  return (
    <label className="obsg-set-row">
      <span className="obsg-set-label">{label}</span>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} />
      <span className="obsg-set-val">{fmt ? fmt(value) : value}</span>
    </label>
  );
}

export default function GraphSettingsPanel({
  graph, filters, onToggleFilter, display, onDisplay, forces, onForces, onResetForces, onClose,
}) {
  const counts = useMemo(() => {
    const m = {};
    (graph?.nodes || []).forEach((n) => { m[n.type] = (m[n.type] || 0) + 1; });
    return m;
  }, [graph]);

  const groupTypes = [
    NODE_TYPES.QUESTION, NODE_TYPES.AGENT, NODE_TYPES.ANSWER, NODE_TYPES.CONCEPT,
    NODE_TYPES.VALIDATION, NODE_TYPES.REBUTTAL, NODE_TYPES.SOURCE,
  ].filter((t) => counts[t]);

  return (
    <aside className="obsg-settings" role="complementary" aria-label="그래프 설정">
      <div className="obsg-settings-head">
        <span>그래프 설정</span>
        <button type="button" className="obsg-icon-btn" onClick={onClose} aria-label="설정 닫기"><X size={15} /></button>
      </div>
      <div className="obsg-settings-body">
        {/* ── Filters ── */}
        <Section title="필터 (Filters)">
          {FILTER_ROWS.map((r) => (
            <label key={r.key} className="obsg-set-check">
              <input type="checkbox" checked={filters[r.key] !== false} onChange={() => onToggleFilter(r.key)} />
              <span className="obsg-set-dot" style={{ background: colorForNode(r.type) }} />
              <span className="obsg-set-label">{r.label}</span>
              <span className="obsg-set-count">{counts[r.type] || 0}</span>
            </label>
          ))}
          <label className="obsg-set-check">
            <input type="checkbox" checked={!!filters.showOrphans} onChange={() => onToggleFilter('showOrphans')} />
            <span className="obsg-set-dot" style={{ background: '#64748b' }} />
            <span className="obsg-set-label">고립 노드 (Orphans)</span>
          </label>
        </Section>

        {/* ── Groups ── */}
        <Section title="그룹 (Groups)">
          {groupTypes.map((t) => (
            <div key={t} className="obsg-set-group">
              <span className="obsg-set-chip" style={{ background: colorForNode(t) }} />
              <span className="obsg-set-label">{labelForNodeType(t)}</span>
              <span className="obsg-set-count">{counts[t]}</span>
            </div>
          ))}
          {groupTypes.length === 0 && <div className="obsg-set-empty">표시할 그룹이 없습니다.</div>}
        </Section>

        {/* ── Display ── */}
        <Section title="표시 (Display)">
          <label className="obsg-set-check">
            <input type="checkbox" checked={display.showArrows} onChange={(e) => onDisplay('showArrows', e.target.checked)} />
            <span className="obsg-set-label">화살표 (Arrows)</span>
          </label>
          <label className="obsg-set-check">
            <input type="checkbox" checked={display.showNodeLabels} onChange={(e) => onDisplay('showNodeLabels', e.target.checked)} />
            <span className="obsg-set-label">노드 라벨 (Show labels)</span>
          </label>
          <label className="obsg-set-check">
            <input type="checkbox" checked={display.showEdgeLabels} onChange={(e) => onDisplay('showEdgeLabels', e.target.checked)} />
            <span className="obsg-set-label">간선 이름 (Edge labels)</span>
          </label>
          <Slider label="노드 크기" value={display.nodeScale} min={0.5} max={2} step={0.1} onChange={(v) => onDisplay('nodeScale', v)} fmt={(v) => `${v.toFixed(1)}×`} />
          <Slider label="간선 두께" value={display.linkThickness} min={0.5} max={2.5} step={0.1} onChange={(v) => onDisplay('linkThickness', v)} fmt={(v) => `${v.toFixed(1)}×`} />
          <Slider label="라벨 표시 임계 줌" value={display.textFade} min={0} max={1.6} step={0.05} onChange={(v) => onDisplay('textFade', v)} fmt={(v) => `${Math.round(v * 100)}%`} />
        </Section>

        {/* ── Forces ── */}
        <Section title="힘 (Forces)" defaultOpen={false}>
          <Slider label="밀어내기 (Repel)" value={forces.repel} min={0.6} max={1.8} step={0.05} onChange={(v) => onForces('repel', v)} fmt={(v) => `${v.toFixed(2)}`} />
          <Slider label="링크 거리 (Link distance)" value={forces.linkDistance} min={0.6} max={1.8} step={0.05} onChange={(v) => onForces('linkDistance', v)} fmt={(v) => `${v.toFixed(2)}`} />
          <Slider label="중심 인력 (Center)" value={forces.center} min={0.4} max={1.6} step={0.05} onChange={(v) => onForces('center', v)} fmt={(v) => `${v.toFixed(2)}`} />
          <button type="button" className="obsg-btn obsg-set-reset" onClick={onResetForces}>기본값으로 재설정</button>
        </Section>
      </div>
    </aside>
  );
}
