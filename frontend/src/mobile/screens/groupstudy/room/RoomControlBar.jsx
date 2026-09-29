import React from 'react';
import { FileQuestion, MessageSquareText, Mic, MicOff, Users, Video, VideoOff } from 'lucide-react';
import { ROOM_PANEL } from './useRoomOverlay';

function ControlButton({ icon, label, isActive = false, isOff = false, hasBadge = false, disabled = false, onClick }) {
  const className = ['mobile-room-bar__button', isActive ? 'is-active' : '', isOff ? 'is-off' : '']
    .filter(Boolean)
    .join(' ');

  return (
    <button type="button" className={className} disabled={disabled} onClick={onClick}>
      <span className="mobile-room-bar__icon">
        {icon}
        {hasBadge && <span className="mobile-room-bar__dot" aria-label="새 메시지" />}
      </span>
      {label}
    </button>
  );
}

export default function RoomControlBar({ session, activePanel, hasUnreadChat, onOpenPanel }) {
  const isChatActive = activePanel === ROOM_PANEL.CHAT || activePanel === ROOM_PANEL.AI;
  const isMaterialsActive = activePanel === ROOM_PANEL.MATERIALS || activePanel === ROOM_PANEL.QUIZ;

  return (
    <nav className="mobile-room-bar" aria-label="스터디룸 제어">
      <ControlButton
        icon={session.isCameraOn ? <Video size={22} /> : <VideoOff size={22} />}
        label="비디오"
        isOff={!session.isCameraOn}
        disabled={session.isUpdatingDevices}
        onClick={session.toggleCamera}
      />
      <ControlButton
        icon={session.isMicrophoneOn ? <Mic size={22} /> : <MicOff size={22} />}
        label="마이크"
        isOff={!session.isMicrophoneOn}
        disabled={session.isUpdatingDevices}
        onClick={session.toggleMicrophone}
      />
      <ControlButton
        icon={<Users size={22} />}
        label="참여자"
        isActive={activePanel === ROOM_PANEL.PARTICIPANTS}
        onClick={() => onOpenPanel(ROOM_PANEL.PARTICIPANTS)}
      />
      <ControlButton
        icon={<MessageSquareText size={22} />}
        label="채팅/AI"
        isActive={isChatActive}
        hasBadge={hasUnreadChat && !isChatActive}
        onClick={() => onOpenPanel(ROOM_PANEL.CHAT)}
      />
      <ControlButton
        icon={<FileQuestion size={22} />}
        label="자료/퀴즈"
        isActive={isMaterialsActive}
        onClick={() => onOpenPanel(ROOM_PANEL.MATERIALS)}
      />
    </nav>
  );
}
