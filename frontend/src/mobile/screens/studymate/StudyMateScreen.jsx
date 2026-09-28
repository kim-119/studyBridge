import React, { useState } from 'react';
import { GraduationCap, Trash2 } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import BottomSheet from '../../components/BottomSheet';
import Button from '../../components/Button';
import Fab from '../../components/Fab';
import ListRow from '../../components/ListRow';
import ScreenState, { EmptyState } from '../../components/ScreenState';
import MobileScreen from '../../shell/MobileScreen';
import { agentService } from '../../../services/api';
import { useAuth } from '../../../hooks/useAuth';
import { useAsync, useSubmit } from '../../data/useAsync';
import CreateRoomSheet from './CreateRoomSheet';
import { STUDYBRIDGE_ROOM_TITLE, roomLimitForRole } from './agentDrafts';
import { describeRoomMode } from './learningModes';

function roomTitleOf(room) {
  return room.roomName || room.name || STUDYBRIDGE_ROOM_TITLE;
}

function roomSubtitleOf(room) {
  const agentNames = (room.agents || []).map((agent) => agent.name).filter(Boolean);
  return [describeRoomMode(room).label, agentNames.join(' · ')].filter(Boolean).join(' · ');
}

function DeleteRoomSheet({ room, onClose, onConfirm, isDeleting, errorMessage }) {
  return (
    <BottomSheet title="스터디방 삭제" isOpen={Boolean(room)} onClose={onClose}>
      <p className="mobile-paragraph">
        {room ? `'${roomTitleOf(room)}'` : ''} 스터디방을 삭제하시겠습니까? 모든 대화 내용이 완전히 삭제됩니다.
      </p>
      {errorMessage && <p className="mobile-auth__error">{errorMessage}</p>}
      <Button variant="danger" fullWidth isLoading={isDeleting} onClick={onConfirm}>
        삭제
      </Button>
    </BottomSheet>
  );
}

export default function StudyMateScreen() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const rooms = useAsync(() => agentService.getAgents(), []);
  const [isCreateOpen, setCreateOpen] = useState(false);
  const [roomToDelete, setRoomToDelete] = useState(null);
  const roomList = Array.isArray(rooms.data) ? rooms.data : [];

  const removeRoom = useSubmit(async () => {
    await agentService.deleteAgent(null, roomToDelete.id);
    setRoomToDelete(null);
    await rooms.reload();
  });

  const handleCreated = async (created) => {
    setCreateOpen(false);
    await rooms.reload();
    if (created?.id != null) navigate(`/studymate/${created.id}`);
  };

  return (
    <MobileScreen title="학습메이트">
      <ScreenState query={rooms} loadingLabel="학습메이트 방을 불러오는 중입니다">
        {roomList.length === 0 ? (
          <EmptyState message="아직 만든 스터디방이 없습니다. 새 스터디방을 만들어 교수님들과 대화를 시작해보세요." />
        ) : (
          <ul className="mobile-list">
            {roomList.map((room) => (
              <li key={room.id}>
                <ListRow
                  icon={<GraduationCap size={20} />}
                  title={roomTitleOf(room)}
                  subtitle={roomSubtitleOf(room)}
                  onClick={() => navigate(`/studymate/${room.id}`)}
                  trailing={
                    <button
                      type="button"
                      className="mobile-todo__delete"
                      aria-label={`${roomTitleOf(room)} 삭제`}
                      onClick={(event) => {
                        event.stopPropagation();
                        removeRoom.clearError();
                        setRoomToDelete(room);
                      }}
                    >
                      <Trash2 size={18} />
                    </button>
                  }
                />
              </li>
            ))}
          </ul>
        )}
      </ScreenState>

      <Fab label="새 스터디방" onClick={() => setCreateOpen(true)} />

      <CreateRoomSheet
        isOpen={isCreateOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={handleCreated}
        roomCount={roomList.length}
        roomLimit={roomLimitForRole(user?.role)}
      />

      <DeleteRoomSheet
        room={roomToDelete}
        onClose={() => setRoomToDelete(null)}
        onConfirm={() => removeRoom.submit().catch(() => {})}
        isDeleting={removeRoom.isSubmitting}
        errorMessage={removeRoom.errorMessage}
      />
    </MobileScreen>
  );
}
