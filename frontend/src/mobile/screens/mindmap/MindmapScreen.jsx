import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Button from '../../components/Button';
import { EmptyState, ErrorState, LoadingState } from '../../components/ScreenState';
import MobileScreen from '../../shell/MobileScreen';
import { agentService } from '../../../services/api';
import { convertChatLogsToObsidianGraph } from '../../../utils/graph/chatLogsToObsidianGraph';
import { useAsync } from '../../data/useAsync';
import MindmapExplorer from './MindmapExplorer';
import SemanticStatusNotice from './SemanticStatusNotice';
import { buildMindmapView } from './mindmapModel';
import { useSemanticRoomGraph } from './useSemanticRoomGraph';

function roomTitleOf(room) {
  return room?.roomName || room?.name || '학습메이트 방';
}

function sortRoomsByRecent(rooms) {
  return [...rooms].sort((a, b) =>
    String(b.updatedAt || b.createdAt || '').localeCompare(String(a.updatedAt || a.createdAt || ''))
  );
}

function RoomSelect({ rooms, selectedRoomId, onChange }) {
  return (
    <div className="mobile-field">
      <label className="mobile-field__label" htmlFor="mindmap-room">
        학습메이트 방
      </label>
      <select
        id="mindmap-room"
        className="mobile-field__input"
        value={selectedRoomId ?? ''}
        onChange={(event) => onChange(event.target.value)}
      >
        {rooms.map((room) => (
          <option key={room.id} value={room.id}>
            {roomTitleOf(room)} · 교수 {(room.agents || []).length}명
          </option>
        ))}
      </select>
    </div>
  );
}

function lastUserQuestionOf(logs) {
  const lastUser = [...logs].reverse().find((log) => log && log.sender === 'USER');
  return String(lastUser?.content || '');
}

function RoomGraph({ room }) {
  const navigate = useNavigate();
  const history = useAsync(() => agentService.getChatHistory(null, room.id), [room.id]);
  const logs = useMemo(() => (Array.isArray(history.data) ? history.data : []), [history.data]);
  const baseGraph = useMemo(
    () => (history.data ? convertChatLogsToObsidianGraph(room, history.data) : null),
    [history.data, room]
  );

  const { graph, semanticState, semanticReason, retrySemantic } = useSemanticRoomGraph({
    roomId: room.id,
    question: lastUserQuestionOf(logs),
    messages: logs,
    agents: room.agents || [],
    baseGraph,
  });
  const view = useMemo(() => (graph ? buildMindmapView(graph) : null), [graph]);

  if (history.isLoading && !history.data) return <LoadingState label="채팅 로그를 그래프로 변환하는 중입니다" />;
  if (history.isError) return <ErrorState message={history.errorMessage} onRetry={history.reload} />;
  if (view?.error) return <ErrorState message={view.error} onRetry={history.reload} />;
  if (!view) {
    return (
      <EmptyState
        message="이 방에는 아직 그래프로 만들 채팅 로그가 없습니다. 학습메이트에서 대화를 먼저 진행해 주세요."
        action={
          <Button variant="secondary" onClick={() => navigate(`/studymate/${room.id}`)}>
            학습메이트로 이동
          </Button>
        }
      />
    );
  }

  return (
    <>
      <SemanticStatusNotice state={semanticState} reason={semanticReason} onRetry={retrySemantic} />
      <MindmapExplorer view={view} fitKey={`${room.id}:${semanticState}`} />
    </>
  );
}

function RoomMindmaps() {
  const navigate = useNavigate();
  const rooms = useAsync(() => agentService.getAgents(), []);
  const [selectedRoomId, setSelectedRoomId] = useState(null);
  const sortedRooms = useMemo(() => sortRoomsByRecent(Array.isArray(rooms.data) ? rooms.data : []), [rooms.data]);
  const selectedRoom = sortedRooms.find((room) => String(room.id) === String(selectedRoomId)) || null;

  useEffect(() => {
    if (!selectedRoomId && sortedRooms.length > 0) setSelectedRoomId(String(sortedRooms[0].id));
  }, [selectedRoomId, sortedRooms]);

  if (rooms.isLoading && !rooms.data) return <LoadingState label="학습메이트 방을 불러오는 중입니다" />;
  if (rooms.isError) return <ErrorState message={rooms.errorMessage} onRetry={rooms.reload} />;
  if (sortedRooms.length === 0) {
    return (
      <EmptyState
        message="아직 학습메이트 방이 없습니다. 학습메이트에서 AI 방을 만들고 대화를 시작하세요."
        action={<Button onClick={() => navigate('/studymate')}>학습메이트에서 방 만들기</Button>}
      />
    );
  }

  return (
    <>
      <RoomSelect rooms={sortedRooms} selectedRoomId={selectedRoomId} onChange={setSelectedRoomId} />
      {selectedRoom && <RoomGraph key={selectedRoom.id} room={selectedRoom} />}
    </>
  );
}

export default function MindmapScreen() {
  return (
    <MobileScreen title="마인드맵" showBackButton>
      <RoomMindmaps />
    </MobileScreen>
  );
}
