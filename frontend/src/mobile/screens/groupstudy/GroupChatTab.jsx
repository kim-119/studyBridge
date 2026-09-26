import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Send, WifiOff } from 'lucide-react';
import { LoadingState } from '../../components/ScreenState';
import { groupService } from '../../../services/api';
import { useAuth } from '../../../hooks/useAuth';
import { useAsync } from '../../data/useAsync';
import { useGroupSocket } from './useGroupSocket';

function toMessage(entry, index) {
  return {
    id: entry.id ?? `live-${index}-${entry.timestamp ?? ''}`,
    senderId: String(entry.senderId ?? ''),
    senderName: entry.senderName || '참여자',
    content: entry.content || '',
    isAi: Boolean(entry.isAi),
  };
}

export default function GroupChatTab({ groupId }) {
  const { userId, user } = useAuth();
  const [liveMessages, setLiveMessages] = useState([]);
  const [draft, setDraft] = useState('');
  const bottomRef = useRef(null);

  const history = useAsync(() => groupService.getChatHistory(groupId), [groupId]);

  const socket = useGroupSocket(
    groupId,
    useMemo(
      () => ({
        chat: (payload) => setLiveMessages((previous) => [...previous, payload]),
      }),
      []
    )
  );

  const messages = useMemo(() => {
    const past = (history.data || []).map(toMessage);
    const live = liveMessages.map(toMessage);
    return [...past, ...live];
  }, [history.data, liveMessages]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: 'end' });
  }, [messages.length]);

  const sendMessage = (event) => {
    event.preventDefault();

    const content = draft.trim();
    if (!content) return;

    const sent = socket.publish('chat', {
      senderId: String(userId ?? ''),
      senderName: user?.displayName || '나',
      content,
    });

    if (sent) setDraft('');
  };

  if (history.isLoading && messages.length === 0) {
    return <LoadingState label="대화를 불러오는 중입니다" />;
  }

  return (
    <div className="mobile-chat">
      {!socket.isConnected && (
        <p className="mobile-chat__status">
          <WifiOff size={14} />
          {socket.state === 'connecting' ? '채팅 서버에 연결하는 중입니다' : '채팅 연결이 끊겼습니다. 자동으로 다시 연결합니다.'}
        </p>
      )}

      <ul className="mobile-chat__messages">
        {messages.map((message) => (
          <li
            key={message.id}
            className={
              message.senderId === String(userId)
                ? 'mobile-chat__bubble is-user'
                : 'mobile-chat__bubble'
            }
          >
            {message.senderId !== String(userId) && (
              <span className="mobile-chat__author">{message.senderName}</span>
            )}
            <p className="mobile-paragraph">{message.content}</p>
          </li>
        ))}
        <li ref={bottomRef} />
      </ul>

      <form className="mobile-chat__composer" onSubmit={sendMessage}>
        <textarea
          className="mobile-chat__input"
          rows={1}
          value={draft}
          placeholder="메시지를 입력하세요"
          onChange={(event) => setDraft(event.target.value)}
        />
        <button
          type="submit"
          className="mobile-chat__send"
          aria-label="전송"
          disabled={!draft.trim() || !socket.isConnected}
        >
          <Send size={18} />
        </button>
      </form>
    </div>
  );
}
