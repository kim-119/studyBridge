import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Network, Search, RefreshCw, AlertTriangle, ArrowRight, Users } from 'lucide-react';
import { agentService } from '../services/api';
import { useAuth } from '../hooks/useAuth';
import ObsidianGraphView from '../components/graph/ObsidianGraphView';
import GraphErrorBoundary from '../components/graph/GraphErrorBoundary';
import { convertChatLogsToObsidianGraph } from '../utils/graph/chatLogsToObsidianGraph';

// ─────────────────────────────────────────────────────────────────────────────
// 옵시디언 독립 페이지(/obsidian). 학습메이트처럼 좌측 방 목록 + 우측 그래프.
//  · 좌측 source of truth = 학습메이트 AI 방 목록(agentService.getAgents). 옵시디언 전용 방 생성 없음.
//  · 방 선택 시 그 방의 채팅 로그(getChatHistory)를 Obsidian Graph 로 변환해 우측에 표시.
//  · requestSeq + AbortController 로 늦게 도착한 이전 방 응답이 현재 그래프를 덮어쓰지 못하게 한다.
//  · 자동 legacy fallback 없음 — 오류 시 오류 패널 + 다시 시도만. PDF 저장/변환/Viewer 경로 전무.
// ─────────────────────────────────────────────────────────────────────────────
const SORTS = [
  { key: 'recent', label: '최근 대화순' },
  { key: 'name', label: '이름순' },
  { key: 'messages', label: '메시지 많은 순' },
];

function roomTitle(r) {
  return r?.roomName || r?.name || '학습메이트 방';
}
function roomAgentNames(r) {
  return (Array.isArray(r?.agents) ? r.agents : []).map((a) => a?.name).filter(Boolean);
}

export default function ObsidianPage() {
  const navigate = useNavigate();
  const { userId } = useAuth();

  const [rooms, setRooms] = useState([]);
  const [roomsLoading, setRoomsLoading] = useState(true);
  const [roomsError, setRoomsError] = useState('');
  const [selectedRoomId, setSelectedRoomId] = useState(null);

  const [graph, setGraph] = useState(null);
  const [graphTitle, setGraphTitle] = useState('');
  const [graphState, setGraphState] = useState('idle'); // idle | loading | ready | empty | error

  const [query, setQuery] = useState('');
  const [sort, setSort] = useState('recent');

  const reqSeqRef = useRef(0);

  const selectedRoom = useMemo(
    () => rooms.find((r) => String(r.id) === String(selectedRoomId)) || null,
    [rooms, selectedRoomId],
  );

  const loadRooms = useCallback(async () => {
    setRoomsLoading(true);
    setRoomsError('');
    try {
      const data = await agentService.getAgents(userId);
      setRooms(Array.isArray(data) ? data : []);
    } catch (e) {
      console.error('[Obsidian] 학습메이트 방 목록 로드 실패', e);
      setRoomsError('학습메이트 방 목록을 불러오지 못했습니다.');
    } finally {
      setRoomsLoading(false);
    }
  }, [userId]);

  useEffect(() => { loadRooms(); }, [loadRooms]);

  // 선택 방의 채팅 로그 → 그래프(stale 응답 차단: 최신 seq 만 반영).
  useEffect(() => {
    if (selectedRoomId == null) {
      setGraph(null); setGraphState('idle');
      return undefined;
    }
    const room = rooms.find((r) => String(r.id) === String(selectedRoomId));
    const seq = reqSeqRef.current + 1;
    reqSeqRef.current = seq;
    const ac = new AbortController();
    let alive = true;
    setGraphState('loading');
    setGraph(null);
    (async () => {
      try {
        const logs = await agentService.getChatHistory(userId, selectedRoomId);
        if (!alive || seq !== reqSeqRef.current || ac.signal.aborted) return; // 늦게 도착한 이전 방 응답 폐기
        const g = convertChatLogsToObsidianGraph(room, logs);
        if (!alive || seq !== reqSeqRef.current) return;
        if (!g) { setGraph(null); setGraphState('empty'); }
        else { setGraph(g); setGraphTitle(roomTitle(room)); setGraphState('ready'); }
      } catch (e) {
        if (!alive || seq !== reqSeqRef.current) return;
        console.error('[Obsidian] 채팅 로그 로드 실패', e);
        setGraphState('error');
      }
    })();
    return () => { alive = false; ac.abort(); };
  }, [selectedRoomId, rooms, userId]);

  const visibleRooms = useMemo(() => {
    const q = query.trim().toLowerCase();
    let list = rooms.filter((r) => {
      if (!q) return true;
      return [roomTitle(r), r.learningMode, ...roomAgentNames(r)].join(' ').toLowerCase().includes(q);
    });
    list = [...list].sort((a, b) => {
      if (sort === 'name') return roomTitle(a).localeCompare(roomTitle(b));
      if (sort === 'messages') return (b.messageCount || 0) - (a.messageCount || 0);
      return String(b.updatedAt || b.createdAt || '').localeCompare(String(a.updatedAt || a.createdAt || '')); // recent
    });
    return list;
  }, [rooms, query, sort]);

  const retryGraph = () => {
    const cur = selectedRoomId;
    setSelectedRoomId(null);
    setTimeout(() => setSelectedRoomId(cur), 0);
  };

  return (
    <div className="mindmap-layout" style={{ display: 'flex', height: 'calc(100vh - 80px)', background: '#0b1020' }}>
      {/* ── 좌측: 학습메이트 방 목록 ── */}
      <aside className="mindmap-aside" style={{ width: 320, flex: 'none', display: 'flex', flexDirection: 'column', background: '#fff', borderRight: '1px solid #e5e7eb' }}>
        <div style={{ padding: '16px 16px 10px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Network size={20} color="#7c3aed" />
            <h2 style={{ margin: 0, fontSize: 18, fontWeight: 800, color: '#111827' }}>마인드맵</h2>
            <span style={{ marginLeft: 'auto', fontSize: 12, color: '#6b7280' }}>학습메이트 방 {rooms.length}개</span>
          </div>
          <p style={{ margin: '6px 0 0', fontSize: 12, color: '#9ca3af' }}>학습메이트 채팅 로그를 지식 그래프로 탐색합니다.</p>
        </div>

        <div style={{ padding: '0 16px 10px', display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div style={{ position: 'relative' }}>
            <Search size={15} color="#9ca3af" style={{ position: 'absolute', left: 10, top: 9 }} />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="방 검색 (제목·교수·태그)"
              aria-label="학습메이트 방 검색"
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
            학습메이트에서 방 만들기 <ArrowRight size={15} />
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
              아직 학습메이트 방이 없습니다.<br />학습메이트에서 AI 방을 만들고 대화를 시작하세요.
            </div>
          ) : visibleRooms.length === 0 ? (
            <div style={{ padding: '24px 12px', textAlign: 'center', color: '#9ca3af', fontSize: 13 }}>검색 결과가 없습니다.</div>
          ) : visibleRooms.map((room) => {
            const active = String(room.id) === String(selectedRoomId);
            const names = roomAgentNames(room);
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
                  <span style={{ fontWeight: 700, fontSize: 13.5, color: '#111827', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }} title={roomTitle(room)}>{roomTitle(room)}</span>
                  {room.learningMode && (
                    <span style={{ flex: 'none', fontSize: 10, color: '#6d28d9', background: '#ede9fe', padding: '1px 6px', borderRadius: 999 }}>{room.learningMode}</span>
                  )}
                </div>
                <div style={{ marginTop: 5, fontSize: 11, color: '#6b7280', display: 'flex', alignItems: 'center', gap: 4 }}>
                  <Users size={11} /> 교수 {names.length}명{room.createdAt ? ` · ${String(room.createdAt).split('T')[0]}` : ''}
                </div>
                {names.length > 0 && (
                  <div style={{ marginTop: 6, display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                    {names.slice(0, 3).map((t, i) => (
                      <span key={`${room.id}-ag-${i}`} style={{ fontSize: 10, color: '#3730a3', background: '#e0e7ff', padding: '1px 6px', borderRadius: 999 }}>{t}</span>
                    ))}
                  </div>
                )}
              </button>
            );
          })}
        </div>
      </aside>

      {/* ── 우측: 선택 방 그래프 ── */}
      <main className="mindmap-graph" style={{ flex: 1, minWidth: 0, position: 'relative' }}>
        {selectedRoomId == null ? (
          <div style={{ height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 12, color: '#64748b' }}>
            <Network size={48} color="#312e81" />
            <div style={{ fontSize: 15 }}>왼쪽에서 학습메이트 방을 선택하면 채팅 로그 기반 지식 그래프를 볼 수 있어요.</div>
          </div>
        ) : graphState === 'loading' ? (
          <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#94a3b8', fontSize: 14 }}>채팅 로그를 그래프로 변환하는 중…</div>
        ) : graphState === 'empty' ? (
          <div style={{ height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 12, color: '#cbd5e1', textAlign: 'center', padding: 24 }}>
            <Network size={40} color="#374151" />
            <div style={{ fontSize: 15 }}>이 방에는 아직 그래프로 만들 채팅 로그가 없습니다.<br />학습메이트에서 대화를 먼저 진행해 주세요.</div>
            <button type="button" className="obsg-btn" onClick={() => navigate('/studymate')}>학습메이트로 이동</button>
          </div>
        ) : graphState === 'error' ? (
          <div style={{ height: '100%', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 12, color: '#cbd5e1' }}>
            <AlertTriangle size={40} color="#f87171" />
            <div style={{ fontSize: 15 }}>이 방의 채팅 로그를 불러오지 못했습니다.</div>
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
