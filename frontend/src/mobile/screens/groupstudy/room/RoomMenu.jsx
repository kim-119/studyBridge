import React from 'react';
import {
  Bot,
  FileText,
  FileQuestion,
  MessageSquareText,
  Settings,
  SwitchCamera,
  Users,
  Volume2,
  VolumeX,
} from 'lucide-react';
import ListRow from '../../../components/ListRow';
import { FACING_MODE } from '../cameraTrack';
import RoomPanel from './RoomPanel';
import { ROOM_PANEL } from './useRoomOverlay';

const MENU_ITEMS = [
  { panel: ROOM_PANEL.SETTINGS, label: '그룹스터디 설정', icon: <Settings size={20} /> },
  { panel: ROOM_PANEL.AI, label: 'AI 질문', icon: <Bot size={20} /> },
  { panel: ROOM_PANEL.CHAT, label: '채팅', icon: <MessageSquareText size={20} /> },
  { panel: ROOM_PANEL.PARTICIPANTS, label: '참여자', icon: <Users size={20} /> },
  { panel: ROOM_PANEL.MATERIALS, label: '학습자료', icon: <FileText size={20} /> },
  { panel: ROOM_PANEL.QUIZ, label: '퀴즈', icon: <FileQuestion size={20} /> },
];

export default function RoomMenu({ session, onOpenPanel, onClose }) {
  return (
    <RoomPanel title="스터디룸 메뉴" onClose={onClose}>
      <ul className="mobile-list">
        {MENU_ITEMS.map((item) => (
          <li key={item.panel}>
            <ListRow icon={item.icon} title={item.label} onClick={() => onOpenPanel(item.panel)} />
          </li>
        ))}
      </ul>

      <h3 className="mobile-section__title mobile-room-panel__subtitle">장치</h3>
      <ul className="mobile-list">
        <li>
          <ListRow
            icon={<SwitchCamera size={20} />}
            title="카메라 전환"
            subtitle={session.facingMode === FACING_MODE.FRONT ? '현재 전면 카메라' : '현재 후면 카메라'}
            trailing={session.isSwitchingCamera ? <span className="mobile-button__spinner" /> : null}
            onClick={session.isCameraOn ? session.switchCamera : undefined}
          />
        </li>
        <li>
          <ListRow
            icon={session.isSpeakerphoneOn ? <Volume2 size={20} /> : <VolumeX size={20} />}
            title={session.isSpeakerphoneOn ? '스피커폰 끄기' : '스피커폰 켜기'}
            onClick={session.toggleSpeakerphone}
          />
        </li>
      </ul>
      {!session.isCameraOn && <p className="mobile-field__hint">카메라를 켜면 전면·후면을 전환할 수 있습니다.</p>}
    </RoomPanel>
  );
}
