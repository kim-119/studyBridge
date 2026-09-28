import React from 'react';
import { LogOut, Menu } from 'lucide-react';
import { SOCKET_STATE } from '../socketConnectionModel';

const SHORT_STATUS_LABEL = {
  [SOCKET_STATE.IDLE]: '연결 준비',
  [SOCKET_STATE.CONNECTING]: '연결 중',
  [SOCKET_STATE.CONNECTED]: '실시간',
  [SOCKET_STATE.RECONNECTING]: '재연결 중',
  [SOCKET_STATE.OFFLINE]: '오프라인',
  [SOCKET_STATE.FAILED]: '연결 끊김',
};

export default function RoomHeader({ title, participantCount, socketState, onOpenMenu, onLeave }) {
  return (
    <header className="mobile-room-header">
      <button type="button" className="mobile-room-header__icon" aria-label="메뉴 열기" onClick={onOpenMenu}>
        <Menu size={22} />
      </button>

      <div className="mobile-room-header__title">
        <h1>{title}</h1>
        <p>{participantCount}명 참여 중</p>
      </div>

      <span
        className={`mobile-room-header__status is-${socketState}`}
        data-socket-state={socketState}
        role="status"
        aria-label={`실시간 연결 상태: ${SHORT_STATUS_LABEL[socketState]}`}
      >
        <span className="mobile-room-header__status-dot" aria-hidden="true" />
        {SHORT_STATUS_LABEL[socketState]}
      </span>

      <button
        type="button"
        className="mobile-room-header__icon is-danger"
        aria-label="스터디룸 나가기"
        onClick={onLeave}
      >
        <LogOut size={20} />
      </button>
    </header>
  );
}
