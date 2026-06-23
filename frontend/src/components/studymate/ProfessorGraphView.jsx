import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { roleForAgentIndex } from './pixel/professorSprites';
import { exportGraphPdf } from './graphPdfExport';
import './professorGraph.css';

// ─────────────────────────────────────────────────────────────────────────────
// 교수/에이전트 답변을 "노드-간선 그래프"로 보여주는 compact fit-to-view 뷰.
//   · "전체 의견" 요약 섹션 없이 곧장 그래프(질문→교수 답변→상호 피드백/반박)를 보여준다.
//   · SSE/응답 데이터 계약은 건드리지 않고, 이 렌더링 계층에서 GraphNode/GraphEdge로 정규화한다.
//   · 초기 렌더는 fit-to-view(전체가 한 화면). 가로/세로 스크롤 없음(container overflow:hidden).
// ─────────────────────────────────────────────────────────────────────────────

// 교수 역할별 고정 색상(랜덤 금지). 픽셀 stage / typingAgents 색과 동일 계열.
const ROLE_ORDER = ['theory', 'book', 'ai'];
const ROLE_COLOR = { theory: '#2563EB', book: '#EA580C', ai: '#7C3AED', question: '#0F172A', summary: '#0EA5E9' };

// 관계 라벨 → relation key + 색/스타일.
const RELATION_STYLE = {
  answer: { color: '#94A3B8', label: '답변' },
  feedback: { color: '#2563EB', label: '피드백' },
  rebuttal: { color: '#DC2626', label: '반박' },
  validation: { color: '#16A34A', label: '검증' },
  supplement: { color: '#D97706', label: '보완' },
  agreement: { color: '#0D9488', label: '동의' },
};

const relationFromLabel = (rawLabel = '') => {
  const s = String(rawLabel);
  if (/재?반박/.test(s)) return 'rebuttal';
  if (/검증/.test(s)) return 'validation';
  if (/보완/.test(s)) return 'supplement';
  if (/동의|합의/.test(s)) return 'agreement';
  if (/답변/.test(s)) return 'answer';
  return 'feedback';
};

const clampNum = (v, lo, hi) => Math.min(Math.max(v, lo), hi);

// ── 데이터 정규화: messages(+interactions) → { nodes, edges } ───────────────────
function buildGraph({ question, agents, messages, interactions }) {
  const agentList = Array.isArray(agents) ? agents : [];
  const nameToSlot = new Map();
  agentList.forEach((ag, i) => { if (ag?.name) nameToSlot.set(String(ag.name), i); });

  const slotToRole = (slot) => ROLE_ORDER[((Number(slot) || 0) % 3 + 3) % 3];

  // 1) 질문 노드(상단 중앙). 없으면 일반 안내.
  const questionNode = {
    id: 'q',
    type: 'question',
    title: '질문',
    content: (question && String(question).trim()) || '질문을 입력하면 교수들이 답변합니다.',
    status: 'complete',
    role: 'question',
  };

  // 2) 교수 답변 노드. 이번 턴 AI 답변(질문에 대한 답)만 role별로 최신 1개.
  const answerMsgs = (Array.isArray(messages) ? messages : []).filter((m) => {
    if (!m || m.sender === 'USER') return false;
    if (m.nodeType && ['debate', 'socratic', 'simulation'].includes(m.nodeType)) return false;
    return true;
  });

  const byRole = new Map();
  const resolveRole = (m, fallbackIdx) => {
    if (m.agentRole && ROLE_ORDER.includes(m.agentRole)) return m.agentRole;
    if (Number.isInteger(m.agentIndex)) return roleForAgentIndex(m.agentIndex);
    if (m.senderName && nameToSlot.has(String(m.senderName))) return slotToRole(nameToSlot.get(String(m.senderName)));
    return slotToRole(fallbackIdx);
  };
  answerMsgs.forEach((m, i) => {
    const role = resolveRole(m, i);
    const text = String(m.content ?? m.answer ?? '').trim();
    const prev = byRole.get(role);
    // 같은 역할이 여러 발화면 마지막(최신) 비어있지 않은 것 우선.
    if (!prev || (text && (!prev._text || true))) {
      byRole.set(role, { msg: m, role, _text: text });
    }
  });

  // agents 배열 기준으로 3개 슬롯을 항상 만든다(데이터 부족해도 그래프 유지 — fallback).
  const presentRoles = [];
  const slotCount = Math.max(agentList.length, byRole.size, 3);
  for (let i = 0; i < Math.min(slotCount, 3); i += 1) presentRoles.push(slotToRole(i));
  const uniqueRoles = Array.from(new Set([...presentRoles, ...byRole.keys()])).slice(0, 3);

  const agentNodes = uniqueRoles.map((role, i) => {
    const hit = byRole.get(role);
    const ag = agentList[i] || {};
    const m = hit?.msg || {};
    const text = (hit?._text || '').trim();
    const badge = String(
      m.role || ag.personality || ag.tone || ag.personalityStyle || ag.style || ''
    ).trim();
    const name = m.senderName || ag.name || `교수 ${i + 1}`;
    const empty = !text;
    return {
      id: `agent-${role}`,
      type: 'agent_answer',
      role,
      agentName: name,
      title: name,
      badge,
      content: empty ? '아직 답변 생성 중…' : text,
      empty,
      status: m.isError ? 'error' : (empty ? 'pending' : 'answer'),
    };
  });

  const nodeById = new Map();
  [questionNode, ...agentNodes].forEach((n) => nodeById.set(n.id, n));
  const roleToNodeId = new Map(agentNodes.map((n) => [n.role, n.id]));

  // 3) 간선. question→agent "답변"은 항상.
  const edges = [];
  agentNodes.forEach((n) => {
    edges.push({
      id: `e-q-${n.role}`, source: 'q', target: n.id,
      relation: 'answer', label: '답변', derived: false, content: '',
    });
  });

  // 4) 상호작용 → 교수 간 edge / 검증 badge.
  let realCross = 0;
  const seenEdge = new Set();
  (Array.isArray(interactions) ? interactions : []).forEach((it, i) => {
    const fromRole = it?.fromRole;
    const targetRole = it?.targetRole;
    const rel = relationFromLabel(it?.relationLabel || it?.phaseLabel);
    const label = it?.relationLabel || RELATION_STYLE[rel].label;
    // from→target 둘 다 교수 노드면 방향성 간선.
    if (fromRole && targetRole && roleToNodeId.has(fromRole) && roleToNodeId.has(targetRole) && fromRole !== targetRole) {
      const sId = roleToNodeId.get(fromRole);
      const tId = roleToNodeId.get(targetRole);
      const dedupe = `${sId}->${tId}:${label}`;
      if (seenEdge.has(dedupe)) return;
      seenEdge.add(dedupe);
      edges.push({
        id: `e-it-${i}`, source: sId, target: tId,
        relation: rel, label, derived: false, content: it?.content || '',
      });
      realCross += 1;
    } else if (fromRole && roleToNodeId.has(fromRole)) {
      // target 없는 검증/보완 → 해당 노드 status badge + 내용 보존.
      const node = nodeById.get(roleToNodeId.get(fromRole));
      if (node) {
        if (rel === 'validation') node.status = 'validation';
        if (it?.content && !node.validationNote) node.validationNote = it.content;
      }
    }
  });

  // 5) fallback: 교수 간 실제 간선이 없으면 derived 상호검증 간선을 만든다(내부 derived=true).
  if (realCross === 0 && agentNodes.length >= 2) {
    const ids = agentNodes.map((n) => n.id);
    const fb = [
      { a: 0, b: 1, rel: 'feedback' },
      { a: 1, b: 2, rel: 'rebuttal' },
      { a: 2, b: 0, rel: 'validation' },
    ];
    fb.forEach(({ a, b, rel }, i) => {
      if (ids[a] && ids[b]) {
        edges.push({
          id: `e-fb-${i}`, source: ids[a], target: ids[b],
          relation: rel, label: RELATION_STYLE[rel].label, derived: true, content: '',
        });
      }
    });
  }

  return { nodes: [questionNode, ...agentNodes], edges };
}

// ── 레이아웃: container 폭에 따라 cols 결정 → 논리 좌표(node center) 계산 ──────────
const NODE_W = 280;
const NODE_H = 132;
const Q_W = 320;
const Q_H = 92;
const GAP_X = 44;
const GAP_Y = 76;
const PAD = 28;

function computeLayout(nodes, cols) {
  const agentNodes = nodes.filter((n) => n.type !== 'question');
  const rows = [];
  for (let i = 0; i < agentNodes.length; i += cols) rows.push(agentNodes.slice(i, i + cols));

  const rowWidth = (count) => count * NODE_W + (count - 1) * GAP_X;
  const maxRowW = Math.max(Q_W, ...rows.map((r) => rowWidth(r.length)), NODE_W);
  const W = maxRowW + PAD * 2;

  const pos = {};
  // 질문 노드: 최상단 중앙.
  let y = PAD + Q_H / 2;
  pos.q = { x: W / 2, y, w: Q_W, h: Q_H };

  y += Q_H / 2 + GAP_Y;
  rows.forEach((row) => {
    const rw = rowWidth(row.length);
    let x = (W - rw) / 2 + NODE_W / 2;
    row.forEach((n) => {
      pos[n.id] = { x, y: y + NODE_H / 2, w: NODE_W, h: NODE_H };
      x += NODE_W + GAP_X;
    });
    y += NODE_H + GAP_Y;
  });
  const H = y - GAP_Y + PAD;
  return { pos, W, H };
}

// 노드 경계까지 선을 잘라 화살표가 카드에 안 파묻히게 한다.
function trimToBox(from, to) {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const len = Math.hypot(dx, dy) || 1;
  const ux = dx / len;
  const uy = dy / len;
  const inset = (p, sign) => {
    const halfW = p.w / 2 + 6;
    const halfH = p.h / 2 + 6;
    const tx = ux !== 0 ? halfW / Math.abs(ux) : Infinity;
    const ty = uy !== 0 ? halfH / Math.abs(uy) : Infinity;
    const t = Math.min(tx, ty);
    return { x: p.x + sign * ux * t, y: p.y + sign * uy * t };
  };
  return { s: inset(from, 1), e: inset(to, -1) };
}

export default function ProfessorGraphView({ question, agents = [], messages = [], interactions = [], onOpenDetail }) {
  const { nodes, edges } = useMemo(
    () => buildGraph({ question, agents, messages, interactions }),
    [question, agents, messages, interactions]
  );

  const containerRef = useRef(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  const [userZoom, setUserZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [detail, setDetail] = useState(null); // {kind:'node'|'edge', ...}
  const [saving, setSaving] = useState(false);
  const drag = useRef(null);

  // PDF 저장: 현재 그래프 모델을 자기완결 SVG→canvas(JPEG)→PDF로 만들어 로컬에 내려받는다.
  const handleSavePdf = async () => {
    if (saving) return;
    setSaving(true);
    try {
      await exportGraphPdf(
        { nodes, edges, pos, W, H, roleColor: ROLE_COLOR, relationStyle: RELATION_STYLE, title: question ? `질문: ${String(question).slice(0, 60)}` : '교수 답변 마인드맵' },
        'studymate-mindmap.pdf'
      );
    } catch (err) {
      console.error('[ProfessorGraphView] PDF 저장 실패', err);
      // eslint-disable-next-line no-alert
      alert('PDF 저장에 실패했습니다. 다시 시도해 주세요.');
    } finally {
      setSaving(false);
    }
  };

  // container 크기 추적(ResizeObserver) → fit 재계산. 인치/해상도 분기 없음.
  useLayoutEffect(() => {
    const el = containerRef.current;
    if (!el) return undefined;
    const measure = () => setSize({ w: el.clientWidth, h: el.clientHeight });
    measure();
    let ro;
    if (typeof ResizeObserver !== 'undefined') {
      ro = new ResizeObserver(measure);
      ro.observe(el);
    }
    window.addEventListener('resize', measure);
    return () => { if (ro) ro.disconnect(); window.removeEventListener('resize', measure); };
  }, []);

  // container 폭으로 cols 결정(데스크톱 3 / 태블릿 2 / 모바일 1).
  const cols = size.w >= 720 ? 3 : size.w >= 480 ? 2 : 1;
  const { pos, W, H } = useMemo(() => computeLayout(nodes, cols), [nodes, cols]);

  // fit-to-view 스케일: 컨테이너에 전체가 들어오도록(초기 userZoom=1 → 순수 fit).
  const fitScale = size.w && size.h ? Math.min(size.w / W, size.h / H) : 1;
  const effScale = clampNum(fitScale * userZoom, 0.2, 2.4);

  // 새 그래프(노드/cols)면 사용자 줌·팬 초기화 → 항상 fit 상태로 시작.
  useEffect(() => { setUserZoom(1); setPan({ x: 0, y: 0 }); }, [W, H, cols, nodes.length]);

  const fitView = () => { setUserZoom(1); setPan({ x: 0, y: 0 }); };

  // 팬(드래그). 초기엔 fit이라 사용 안 해도 됨(목표: 초기 전체 보임).
  const onPointerDown = (e) => {
    if (e.target.closest('.pgraph-node') || e.target.closest('.pgraph-edge-hit')) return;
    drag.current = { x: e.clientX, y: e.clientY, px: pan.x, py: pan.y };
  };
  const onPointerMove = (e) => {
    if (!drag.current) return;
    setPan({ x: drag.current.px + (e.clientX - drag.current.x), y: drag.current.py + (e.clientY - drag.current.y) });
  };
  const endDrag = () => { drag.current = null; };

  const markerId = (rel) => `pg-arrow-${rel}`;

  return (
    <div className="pgraph-root">
      <div
        ref={containerRef}
        className="pgraph-canvas-container"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerLeave={endDrag}
      >
        {/* 우측 상단: 모드 상태를 작은 pill로만 축소 노출(전체 의견 섹션 대체) */}
        <div className="pgraph-statepill" aria-hidden="true">교수 {Math.max(0, nodes.length - 1)}명 · 상호검증</div>

        <div
          className="pgraph-canvas"
          style={{
            width: W, height: H,
            transform: `translate(-50%, -50%) translate(${pan.x}px, ${pan.y}px) scale(${effScale})`,
          }}
        >
          <svg className="pgraph-edges" width={W} height={H} aria-hidden="true">
            <defs>
              {Object.keys(RELATION_STYLE).map((rel) => (
                <marker key={rel} id={markerId(rel)} viewBox="0 0 10 10" refX="9" refY="5"
                  markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                  <path d="M 0 0 L 10 5 L 0 10 z" fill={RELATION_STYLE[rel].color} />
                </marker>
              ))}
            </defs>
            {edges.map((edge) => {
              const s = pos[edge.source];
              const t = pos[edge.target];
              if (!s || !t) return null;
              const { s: p1, e: p2 } = trimToBox(s, t);
              const mx = (p1.x + p2.x) / 2;
              const my = (p1.y + p2.y) / 2;
              const style = RELATION_STYLE[edge.relation] || RELATION_STYLE.feedback;
              const labelW = edge.label.length * 11 + 18;
              const hasDetail = !!edge.content;
              return (
                <g key={edge.id} className="pgraph-edge">
                  <line
                    x1={p1.x} y1={p1.y} x2={p2.x} y2={p2.y}
                    stroke={style.color} strokeWidth={2}
                    strokeDasharray={edge.derived ? '6 5' : undefined}
                    markerEnd={`url(#${markerId(edge.relation)})`}
                    opacity={edge.derived ? 0.55 : 0.9}
                  />
                  {/* 라벨 pill: 선보다 위, 노드보다 아래. 흰 배경으로 가독성 확보 */}
                  <g
                    className={`pgraph-edge-label ${hasDetail ? 'is-clickable' : ''}`}
                    transform={`translate(${mx}, ${my})`}
                    onClick={hasDetail ? (e) => { e.stopPropagation(); setDetail({ kind: 'edge', edge, style }); } : undefined}
                  >
                    <rect className="pgraph-edge-hit" x={-labelW / 2} y={-12} width={labelW} height={24} rx={12}
                      fill="#ffffff" stroke={style.color} strokeWidth={1.5} />
                    <text x={0} y={4} textAnchor="middle" fontSize={12} fontWeight={800} fill={style.color}>
                      {edge.label}{edge.derived ? '·예시' : ''}
                    </text>
                  </g>
                </g>
              );
            })}
          </svg>

          {nodes.map((n) => {
            const p = pos[n.id];
            if (!p) return null;
            const isQ = n.type === 'question';
            const color = ROLE_COLOR[n.role] || ROLE_COLOR.question;
            return (
              <div
                key={n.id}
                className={`pgraph-node ${isQ ? 'is-question' : 'is-agent'} ${n.empty ? 'is-empty' : ''}`}
                style={{
                  left: p.x - p.w / 2, top: p.y - p.h / 2, width: p.w, minHeight: p.h,
                  '--accent': color,
                }}
                onClick={(e) => { e.stopPropagation(); setDetail({ kind: 'node', node: n, color }); onOpenDetail?.(n); }}
                title="클릭하면 전체 내용 보기"
              >
                <div className="pgraph-node-head">
                  <span className="pgraph-node-dot" style={{ background: color }} />
                  <strong className="pgraph-node-name">{n.title}</strong>
                  {!isQ && n.badge ? <span className="pgraph-node-badge">{n.badge}</span> : null}
                </div>
                <p className={`pgraph-node-body ${isQ ? 'q' : ''}`}>{n.content}</p>
                {!isQ && (
                  <div className="pgraph-node-foot">
                    <span className={`pgraph-status st-${n.status}`}>
                      {n.status === 'answer' ? '답변' : n.status === 'validation' ? '검증' : n.status === 'error' ? '오류' : n.status === 'pending' ? '생성 중' : '완료'}
                    </span>
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* 좌측 하단 PDF 저장 */}
        <button type="button" className="pgraph-save" onClick={handleSavePdf} disabled={saving}>
          {saving ? '저장 중…' : '⬇ PDF 저장'}
        </button>

        {/* 우측 하단 zoom/fit 컨트롤 */}
        <div className="pgraph-controls" role="group" aria-label="그래프 확대/축소">
          <button type="button" onClick={() => setUserZoom((z) => clampNum(z + 0.15, 0.4, 2.2))} aria-label="확대">＋</button>
          <button type="button" onClick={() => setUserZoom((z) => clampNum(z - 0.15, 0.4, 2.2))} aria-label="축소">－</button>
          <button type="button" className="pgraph-fit" onClick={fitView}>화면에 맞춤</button>
        </div>
      </div>

      {/* 노드/간선 상세(전문) — 스케일 밖 레이어라 항상 또렷하게 읽힘 */}
      {detail && (
        <div className="pgraph-detail" onClick={() => setDetail(null)}>
          <div className="pgraph-detail-card" onClick={(e) => e.stopPropagation()} style={{ '--accent': detail.kind === 'node' ? detail.color : detail.style.color }}>
            <div className="pgraph-detail-head">
              <strong>
                {detail.kind === 'node'
                  ? detail.node.title
                  : `${detail.style.label} 내용`}
              </strong>
              <button type="button" onClick={() => setDetail(null)} aria-label="닫기">✕</button>
            </div>
            {detail.kind === 'node' ? (
              <>
                {detail.node.badge ? <span className="pgraph-detail-badge">{detail.node.badge}</span> : null}
                <p className="pgraph-detail-body">{detail.node.content}</p>
                {detail.node.validationNote ? (
                  <div className="pgraph-detail-note"><b>검증 메모</b><p>{detail.node.validationNote}</p></div>
                ) : null}
              </>
            ) : (
              <p className="pgraph-detail-body">{detail.edge.content || '추가 내용이 없습니다.'}</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
