import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Network, Trash2, Search, Plus, RefreshCw, AlertTriangle } from 'lucide-react';
import { materialService } from '../services/api';
import ObsidianGraphView from '../components/graph/ObsidianGraphView';
import GraphErrorBoundary from '../components/graph/GraphErrorBoundary';
import { isObsidianMaterial, roomFromMaterial, parseArchiveGraph } from '../utils/graph/archiveGraph';

// ─────────────────────────────────────────────────────────────────────────────
// 옵시디언 독립 페이지(/obsidian). 학습메이트처럼 좌측 방 목록 + 우측 그래프.
//  · 자료보관함 activeTab 상태와 완전 분리. 선택 방의 그래프만 렌더(방 섞임 금지).
//  · requestSeq 가드로 늦게 도착한 이전 방 응답이 현재 그래프를 덮어쓰지 못하게 한다.
//  · 자동 legacy fallback 없음 — 그래프 오류 시 오류 패널 + 다시 시도만 표시.
//  · PDF 저장/변환/Viewer 진입 경로 전무.
// ─────────────────────────────────────────────────────────────────────────────
const SORTS = [
  { key: 'recent', label: '최근 수정순' },
  { key: 'name', label: '이름순' },
  { key: 'nodes', label: '노드 많은 순' },
];

export default function ObsidianPage() {
  const navigate = useNavigate();

  const [rooms, setRooms] = useState([]);
  const [roomsLoading, setRoomsLoading] = useState(true);
  const [roomsError, setRoomsError] = useState('');
  const [selectedRoomId, setSelectedRoomId] = useState(null);

  const [graph, setGraph] = useState(null);
  const [graphTitle, setGraphTitle] = useState('');
  const [graphLoading, setGraphLoading] = useState(false);
  const [graphError, setGraphError] = useState('');

  const [query, setQuery] = useState('');
  const [sort, setSort] = useState('recent');

  const reqSeqRef = useRef(0);

  const loadRooms = useCallback(async () => {
    setRoomsLoading(true);
    setRoomsError('');
    try {
      const data = await materialService.getArchiveItems(null, 'MINDMAP');
      const list = (Array.isArray(data?.materials) ? data.materials : [])
        .filter(isObsidianMaterial)
        .map(roomFromMaterial);
      setRooms(list);
    } catch (e) {
      console.error('[Obsidian] 방 목록 로드 실패', e);
      setRoomsError('옵시디언 방 목록을 불러오지 못했습니다.');
    } finally {
      setRoomsLoading(false);
    }
  }, []);

  useEffect(() => { loadRooms(); }, [loadRooms]);

  // 선택 방의 그래프 로드(stale 응답 차단: 최신 seq 만 반영).
  useEffect(() => {
    if (selectedRoomId == null) {
      setGraph(null); setGraphError(''); setGraphLoading(false);
      return undefined;
    }
    const seq = reqSeqRef.current + 1;
    reqSeqRef.current = seq;
    let alive = true;
    setGraphLoading(true);
    setGraphError('');
    setGraph(null);
    (async () => {
      try {
        const detail = await materialService.getMaterialDetail(selectedRoomId);
        if (!alive || seq !== reqSeqRef.current) return; // 늦게 도착한 이전 방 응답 폐기
        const g = parseArchiveGraph(detail);
        if (!alive || seq !== reqSeqRef.current) return;
        if (!g) { setGraphError('옵시디언 그래프 데이터를 불러올 수 없습니다.'); setGraph(null); }
        else { setGraph(g); setGraphTitle(detail.title || '옵시디언 방'); }
      } catch (e) {
        if (!alive || seq !== reqSeqRef.current) return;
        console.error('[Obsidian] 그래프 로드 실패', e);
        setGraphError('옵시디언 그래프 데이터를 불러올 수 없습니다.');
      } finally {
        if (alive && seq === reqSeqRef.current) setGraphLoading(false);
      }
    })();
    return () => { alive = false; };
  }, [selectedRoomId]);

  const handleDelete = async (room, e) => {
    e.stopPropagation();
    if (!window.confirm('이 옵시디언 방과 연결된 그래프 데이터를 삭제할까요?')) return;
    try {
      await materialService.deleteMaterial(room.id);
      setRooms((rs) => rs.filter((r) => r.id !== room.id));
      if (selectedRoomId === room.id) setSelectedRoomId(null);
    } catch (err) {
      console.error('[Obsidian] 방 삭제 실패', err);
      window.alert('방 삭제에 실패했습니다.');
    }
  };

  const visibleRooms = useMemo(() => {
    const q = query.trim().toLowerCase();
    let list = rooms.filter((r) => {
      if (!q) return true;
      return [r.title, r.sourceType, ...(r.tags || [])].join(' ').toLowerCase().includes(q);
    });
    list = [...list].sort((a, b) => {
      if (sort === 'name') return String(a.title).localeCompare(String(b.title));
      if (sort === 'nodes') return (b.nodeCount || 0) - (a.nodeCount || 0);
      return String(b.updatedAt || '').localeCompare(String(a.updatedAt || '')); // recent
    });
    return list;
  }, [rooms, query, sort]);

  // 같은 방을 다시 로드(effect 재실행). null→원래 id 토글로 깔끔히 재트리거.
  const retryGraph = () => {
    const cur = selectedRoomId;
    setSelectedRoomId(null);
    setTimeout(() => setSelectedRoomId(cur), 0);
  };

  return (
    <div style={{ display: 'flex', height: 'calc(100vh - 80px)', background: '#0b1020' }}>
      {/* ── 좌측: 방 목록 ── */}
      <aside style={{ width: 320, flex: 'none', display: 'flex', flexDirection: 'column', background: '#fff', borderRight: '1px solid #e5e7eb' }}>
        <div style={{ padding: '16px 16px 10px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Network size={20} color="#7c3aed" />
            <h2 style={{ margin: 0, fontSize: 18, fontWeight: 800, color: '#111827' }}>옵시디언</h2>
            <span style={{ marginLeft: 'auto', fontSize: 12, color: '#6b7280' }}>그래프 세션 {rooms.length}개</span>
          </div>
          <p style={{ margin: '6px 0 0', fontSize: 12, color: '#9ca3af' }}>학습메이트에서 저장한 지식 그래프를 방 단위로 탐색합니다.</p>
        </div>

        <div style={{ padding: '0 16px 10px', display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div style={{ position: 'relative' }}>
            <Search size={15} color="#9ca3af" style={{ position: 'absolute', left: 10, top: 9 }} />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="방 검색 (제목·태그)"
              aria-label="옵시디언 방 검색"
              style={{ width: '100%', padding: '8px 8px 8px 30px', fontSize: 13, border: '1px solid #e5e7eb', borderRadius: 8, boxSizing: 'border-box', outline: 'none' }}
            />
          </div>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            <select value={sort} onChange={(e) => setSort(e.target.value)} aria-label="방 정렬" style={{ flex: 1, fontSize: 12, padding: '6px 8px', border: '1px solid #e5e7eb', borderRadius: 8 }}>
              {SORTS.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
            </select>
            <button type="button" onClick={loadRooms} title="새로고침" style={{ padding: 7, border: '1px solid #e5e7eb', borderRadius: 8, background: '#fff', cursor: 'pointer' }}>
              <RefreshCw size={14} color="#6b7280" />
            </button>
          </div>
          <button
            type="button"
            onClick={() => navigate('/studymate')}
            style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 6, padding: '9px 12px', fontSize: 13, fontWeight: 700, color: '#fff', background: '#7c3aed', border: 'none', borderRadius: 8, cursor: 'pointer' }}
          >
            <Plus size={15} /> 새 옵시디언 방 (학습메이트에서 생성)
          </button>
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: '4px 12px 16px' }}>
          {roomsLoading ? (
            <div style={{ padding: 20, textAlign: 'center', color: '#9ca3af', fontSize: 13 }}>불러오는 중…</div>
          ) : roomsError ? (
            <div style={{ padding: 16, color: '#b91c1c', fontSize: 13 }}>{roomsError}
              <button type="button" onClick={loadRooms} style={{ display: 'block', marginTop: 8, fontSize: 12 }}>다시 시도</button>
            </div>
          ) : rooms.length === 0 ? (
            <div style={{ padding: '24px 12px', textAlign: 'center', color: '#9ca3af', fontSize: 13, lineHeight: 1.6 }}>
              아직 옵시디언 방이 없습니다.<br />학습메이트에서 마인드맵을 만들고 “자료보관함에 저장”하면 방이 생성됩니다.
            </div>
          ) : visibleRooms.length === 0 ? (
            <div style={{ padding: '24px 12px', textAlign: 'center', color: '#9ca3af', fontSize: 13 }}>검색 결과가 없습니다.</div>
          ) : visibleRooms.map((room) => {
            const active = room.id === selectedRoomId;
            return (
              <button
                type="button"
                key={room.id}
                onClick={() => setSelectedRoomId(room.id)}
                style={{
                  display: 'block', width: '100%', textAlign: 'left', marginBottom: 8, padding: '10px 12px',
                  border: `1px solid ${active ? '#7c3aed' : '#e5e7eb'}`, borderRadius: 10,
                  background: active ? '#f5f3ff' : '#fff', cursor: 'pointer',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Network size={14} color="#7c3aed" style={{ flex: 'none' }} />
                  <span style={{ fontWeight: 700, fontSize: 13.5, color: '#111827', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }} title={room.title}>{room.title}</span>
                  <span role="button" tabIndex={0} aria-label="방 삭제" onClick={(e) => handleDelete(room, e)} onKeyDown={(e) => { if (e.key === 'Enter') handleDelete(room, e); }} style={{ flex: 'none', color: '#9ca3af', cursor: 'pointer', display: 'inline-flex' }}>
                    <Trash2 size={14} />
                  </span>
                </div>
                <div style={{ marginTop: 5, fontSize: 11, color: '#6b7280' }}>
                  노드 {room.nodeCount}개 · 연결 {room.edgeCount}개{room.updatedAt ? ` · ${String(room.updatedAt).split('T')[0]}` : ''}
                </div>
                {room.tags.length > 0 && (
                  <div style={{ marginTop: 6, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                    {room.tags.slice(0, 3).map((t) => (
                      <span key={t} style={{ fontSize: 10, color: '#6d28d9', background: '#ede9fe', padding: '1px 6px', borderRadius: 999 }}>#{t}</span>
                    ))}
                  </div>
                )}
              </button>
            );
          })}
        </div>
      </aside>

      {/* ── 우측: 선택 방 그래프 ── */}
      <main style={{ flex: 1, minWidth: 0, position: 'relative' }}>
        {selectedRoomId == null ? (
          <div style={{ height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 12, color: '#64748b' }}>
            <Network size={48} color="#312e81" />
            <div style={{ fontSize: 15 }}>왼쪽에서 옵시디언 방을 선택하면 지식 그래프를 볼 수 있어요.</div>
          </div>
        ) : graphLoading ? (
          <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8', fontSize: 14 }}>그래프를 불러오는 중…</div>
        ) : graphError ? (
          <div style={{ height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 12, color: '#cbd5e1' }}>
            <AlertTriangle size={40} color="#f87171" />
            <div style={{ fontSize: 15 }}>{graphError}</div>
            <button type="button" className="obsg-btn" onClick={retryGraph}>다시 시도</button>
          </div>
        ) : graph ? (
          <GraphErrorBoundary
            fallback={(
              <div style={{ height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 12, color: '#cbd5e1', background: '#0b1020' }}>
                <AlertTriangle size={40} color="#f87171" />
                <div style={{ fontSize: 15 }}>그래프 렌더 중 오류가 발생했습니다.</div>
                <button type="button" className="obsg-btn" onClick={retryGraph}>다시 시도</button>
              </div>
            )}
          >
            {/* roomId 를 key 로 두어 방 전환 시 그래프 상태를 깨끗이 분리(섞임 방지) */}
            <ObsidianGraphView key={selectedRoomId} graph={graph} title={graphTitle} />
          </GraphErrorBoundary>
        ) : null}
      </main>
    </div>
  );
}
