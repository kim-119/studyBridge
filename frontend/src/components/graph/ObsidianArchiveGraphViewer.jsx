import React, { useMemo } from 'react';
import { ArrowLeft, Trash2, Network } from 'lucide-react';
import ObsidianGraphView from './ObsidianGraphView';
import { sanitizeGraph, validateGraph } from '../../utils/graph/graphValidation';

// ─────────────────────────────────────────────────────────────────────────────
// 자료보관함 mindmap 전용 뷰어. 절대 PDFViewer/MarkdownViewer 로 열지 않는다.
//  · material.contentJson(저장 payload) 또는 material.rawGraphJson 에서 그래프를 읽는다.
// ─────────────────────────────────────────────────────────────────────────────
function parseGraph(material) {
  const tryParse = (v) => {
    if (!v) return null;
    if (typeof v === 'object') return v;
    try { return JSON.parse(v); } catch { return null; }
  };
  // 1) 저장 payload(contentJson) → rawGraphJson.
  const payload = tryParse(material?.contentJson);
  let raw = payload?.rawGraphJson ? tryParse(payload.rawGraphJson) || payload.rawGraphJson : null;
  // 2) migration 등이 직접 rawGraphJson 을 둔 경우.
  if (!raw && material?.rawGraphJson) raw = tryParse(material.rawGraphJson) || material.rawGraphJson;
  // 3) contentJson 자체가 그래프인 경우.
  if (!raw && payload && Array.isArray(payload.nodes)) raw = payload;
  if (!raw || !Array.isArray(raw.nodes)) return null;
  return sanitizeGraph(raw);
}

export default function ObsidianArchiveGraphViewer({ material, onBack, onDelete }) {
  const graph = useMemo(() => parseGraph(material), [material]);
  const valid = graph ? validateGraph(graph) : { ok: false, errors: ['그래프 데이터 없음'] };
  const title = material?.title || '마인드맵';

  return (
    <div style={{ width: '100%', height: '100%', display: 'flex', flexDirection: 'column', background: '#0b1020' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 18px', background: '#111827', borderBottom: '1px solid #1f2937' }}>
        <button type="button" className="obsg-btn" onClick={onBack}><ArrowLeft size={16} /> 목록</button>
        <Network size={16} color="#a78bfa" />
        <span style={{ fontWeight: 700, fontSize: 15, color: '#f9fafb', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }} title={title}>{title}</span>
        <span style={{ fontSize: 11, color: '#a78bfa', background: '#312e81', padding: '2px 8px', borderRadius: 999 }}>Obsidian Graph</span>
        {onDelete && (
          <button type="button" className="obsg-btn" style={{ color: '#fca5a5' }} onClick={onDelete}><Trash2 size={15} /> 삭제</button>
        )}
      </div>
      <div style={{ flex: 1, minHeight: 0 }}>
        {graph && valid.ok ? (
          <ObsidianGraphView graph={graph} title={title} />
        ) : (
          <div className="obsg-empty" style={{ position: 'static', height: '100%' }}>
            <Network size={40} color="#374151" />
            <div>그래프 데이터를 불러올 수 없습니다.</div>
            <div style={{ fontSize: 12 }}>{valid.errors?.[0] || '손상된 마인드맵 데이터'}</div>
          </div>
        )}
      </div>
    </div>
  );
}
