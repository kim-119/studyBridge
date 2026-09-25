import React, { useState } from 'react';
import { GraduationCap } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import BottomSheet from '../../components/BottomSheet';
import Button from '../../components/Button';
import Fab from '../../components/Fab';
import ListRow from '../../components/ListRow';
import ScreenState, { EmptyState } from '../../components/ScreenState';
import TextField from '../../components/TextField';
import MobileScreen from '../../shell/MobileScreen';
import { agentService } from '../../../services/api';
import { useAsync, useSubmit } from '../../data/useAsync';

const LEARNING_MODES = [
  { key: 'basic', label: '기본 개념' },
  { key: 'debate', label: '토론' },
  { key: 'socratic', label: '소크라테스' },
  { key: 'simulation', label: '시뮬레이션' },
];

export default function StudyMateScreen() {
  const navigate = useNavigate();
  const rooms = useAsync(() => agentService.getRooms(), []);
  const [isSheetOpen, setSheetOpen] = useState(false);
  const [roomName, setRoomName] = useState('');
  const [learningMode, setLearningMode] = useState(LEARNING_MODES[0].key);

  const createRoom = useSubmit(async () => {
    const created = await agentService.createRoom(null, {
      roomName: roomName.trim(),
      learningMode,
      agents: [
        {
          name: roomName.trim() || 'AI 메이트',
          role: '학습 도우미',
          persona: '사용자의 학습을 돕는다',
          tone: '전문적',
          goal: '사용자의 학습을 돕는다',
        },
      ],
    });

    setSheetOpen(false);
    setRoomName('');
    await rooms.reload();

    const roomId = created?.roomId ?? created?.id;
    if (roomId) navigate(`/studymate/${roomId}`);
  });

  const roomList = Array.isArray(rooms.data) ? rooms.data : rooms.data?.content || [];

  return (
    <MobileScreen title="학습메이트">
      <ScreenState query={rooms} loadingLabel="AI 메이트를 불러오는 중입니다">
        {roomList.length === 0 ? (
          <EmptyState message="아직 만든 AI 메이트가 없습니다. 새 메이트를 만들어 대화를 시작해보세요." />
        ) : (
          <ul className="mobile-list">
            {roomList.map((room) => (
              <li key={room.roomId ?? room.id}>
                <ListRow
                  icon={<GraduationCap size={20} />}
                  title={room.roomName || room.name || 'AI 메이트'}
                  subtitle={room.learningMode || 'basic'}
                  onClick={() => navigate(`/studymate/${room.roomId ?? room.id}`)}
                />
              </li>
            ))}
          </ul>
        )}
      </ScreenState>

      <Fab label="새 AI 메이트" onClick={() => setSheetOpen(true)} />

      <BottomSheet title="새 AI 메이트" isOpen={isSheetOpen} onClose={() => setSheetOpen(false)}>
        <TextField
          label="메이트 이름"
          value={roomName}
          placeholder="예: 개념 정리 교수"
          onChange={(event) => setRoomName(event.target.value)}
        />

        <div className="mobile-field">
          <label className="mobile-field__label" htmlFor="studymate-mode">
            학습 모드
          </label>
          <select
            id="studymate-mode"
            className="mobile-field__input"
            value={learningMode}
            onChange={(event) => setLearningMode(event.target.value)}
          >
            {LEARNING_MODES.map((mode) => (
              <option key={mode.key} value={mode.key}>
                {mode.label}
              </option>
            ))}
          </select>
        </div>

        {createRoom.errorMessage && <p className="mobile-auth__error">{createRoom.errorMessage}</p>}

        <Button
          fullWidth
          isLoading={createRoom.isSubmitting}
          disabled={!roomName.trim()}
          onClick={() => createRoom.submit().catch(() => {})}
        >
          만들기
        </Button>
      </BottomSheet>
    </MobileScreen>
  );
}
