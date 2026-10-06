import React, { useEffect, useRef, useState } from 'react';
import { Send, Square, WifiOff } from 'lucide-react';
import MarkdownText from '../../../components/MarkdownText';
import { ErrorState, LoadingState } from '../../../components/ScreenState';
import SubTabs from '../../../components/SubTabs';
import { canRetryManually, describeSocketStatus } from '../socketConnectionModel';
import RoomPanel from './RoomPanel';
import { ROOM_PANEL } from './useRoomOverlay';

const CHAT_TABS = [
  { key: ROOM_PANEL.CHAT, label: '채팅' },
  { key: ROOM_PANEL.AI, label: 'AI 질문' },
];

function useScrollToLatest(count) {
  const bottomRef = useRef(null);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: 'end' });
  }, [count]);
  return bottomRef;
}

function Composer({ placeholder, isDisabled, isStreaming = false, onSend, onStop }) {
  const [draft, setDraft] = useState('');

  const submit = (event) => {
    event.preventDefault();
    const content = draft.trim();
    if (!content || isDisabled) return;
    if (onSend(content) !== false) setDraft('');
  };

  return (
    <form className="mobile-chat__composer" onSubmit={submit}>
      <textarea
        className="mobile-chat__input"
        rows={1}
        value={draft}
        placeholder={placeholder}
        onChange={(event) => setDraft(event.target.value)}
      />
      {isStreaming ? (
        <button type="button" className="mobile-chat__send is-stop" aria-label="응답 중지" onClick={onStop}>
          <Square size={16} />
        </button>
      ) : (
        <button type="submit" className="mobile-chat__send" aria-label="전송" disabled={!draft.trim() || isDisabled}>
          <Send size={18} />
        </button>
      )}
    </form>
  );
}

function GroupChat({ room, userId }) {
  const bottomRef = useScrollToLatest(room.chatMessages.length);

  if (room.history.isLoading && room.chatMessages.length === 0) {
    return <LoadingState label="대화를 불러오는 중입니다" />;
  }

  if (room.history.isError) {
    return <ErrorState message={room.history.errorMessage} onRetry={room.history.reload} />;
  }

  return (
    <div className="mobile-room-chat">
      {!room.isSocketConnected && (
        <p className="mobile-chat__status" data-socket-state={room.socketState}>
          <WifiOff size={14} />
          {describeSocketStatus(room.socketState, room.socketReconnectAttempt)}
          {canRetryManually(room.socketState) && (
            <button type="button" className="mobile-room-chat__reconnect" onClick={room.reconnectSocket}>
              재연결
            </button>
          )}
        </p>
      )}

      <ul className="mobile-chat__messages">
        {room.chatMessages.length === 0 && <li className="mobile-field__hint">첫 메시지를 남겨보세요.</li>}
        {room.chatMessages.map((message) => {
          const isMine = String(message.senderId) === String(userId);
          return (
            <li
              key={message.id}
              className={isMine ? 'mobile-chat__bubble is-user' : 'mobile-chat__bubble'}
              data-chat-message-id={message.serverId || message.id}
            >
              {!isMine && <span className="mobile-chat__author">{message.senderName}</span>}
              <p className="mobile-paragraph">{message.content}</p>
            </li>
          );
        })}
        <li ref={bottomRef} />
      </ul>

      <Composer placeholder="메시지를 입력하세요" isDisabled={!room.isSocketConnected} onSend={room.sendChat} />
    </div>
  );
}

function aiBubbleClassName(message) {
  if (message.isUser) return 'mobile-chat__bubble is-user';
  if (message.isError) return 'mobile-chat__bubble mobile-room-chat__error';
  return 'mobile-chat__bubble mobile-chat__bubble--agent';
}

function AiChat({ ai, history }) {
  const bottomRef = useScrollToLatest(ai.messages.length);

  return (
    <div className="mobile-room-chat">
      <p className="mobile-field__hint">AI 질문과 답변은 스터디 멤버 모두에게 공유됩니다.</p>
      {history.isLoading && <LoadingState label="AI 대화 기록을 불러오는 중입니다" />}
      {history.isError && <ErrorState message={history.errorMessage} onRetry={history.reload} />}

      <ul className="mobile-chat__messages">
        {ai.messages.map((message) => (
          <li key={message.id} className={aiBubbleClassName(message)}>
            {!message.isUser && <span className="mobile-chat__author">{message.senderName}</span>}
            {message.isUser ? (
              <p className="mobile-paragraph">{message.content}</p>
            ) : (
              <MarkdownText>{message.content}</MarkdownText>
            )}
          </li>
        ))}
        {ai.isStreaming && <li className="mobile-field__hint">AI가 답변을 작성하는 중입니다…</li>}
        <li ref={bottomRef} />
      </ul>

      <Composer
        placeholder="AI에게 질문하세요"
        isDisabled={ai.isStreaming}
        isStreaming={ai.isStreaming}
        onSend={ai.send}
        onStop={ai.stop}
      />
    </div>
  );
}

export default function ChatPanel({ activeTab, room, ai, userId, onChangeTab, onClose }) {
  return (
    <RoomPanel
      title="채팅 / AI"
      onClose={onClose}
      tabs={<SubTabs tabs={CHAT_TABS} activeKey={activeTab} onChange={onChangeTab} />}
    >
      {activeTab === ROOM_PANEL.AI ? <AiChat ai={ai} history={room.history} /> : <GroupChat room={room} userId={userId} />}
    </RoomPanel>
  );
}
