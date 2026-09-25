import React, { useEffect, useRef, useState } from 'react';
import { Send, Square } from 'lucide-react';
import { useParams } from 'react-router-dom';
import { LoadingState } from '../../components/ScreenState';
import MobileScreen from '../../shell/MobileScreen';
import { agentService } from '../../../services/api';
import { useAsync } from '../../data/useAsync';
import { useStudyMateStream } from './useStudyMateStream';

function historyToMessages(history) {
  const entries = Array.isArray(history) ? history : history?.messages || [];

  return entries.map((entry, index) => ({
    id: entry.id ?? `history-${index}`,
    role: entry.role === 'user' || entry.sender === 'user' ? 'user' : 'assistant',
    agentName: entry.agentName || entry.agent_name || 'AI 메이트',
    text: entry.content || entry.message || entry.answer || '',
    isSealed: true,
  }));
}

export default function StudyMateChatScreen() {
  const { roomId } = useParams();
  const stream = useStudyMateStream(roomId);
  const [question, setQuestion] = useState('');
  const bottomRef = useRef(null);

  const history = useAsync(() => agentService.getChatHistory(null, roomId), [roomId]);

  useEffect(() => {
    if (!history.data) return;
    stream.setMessages(historyToMessages(history.data));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [history.data]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: 'end' });
  }, [stream.messages, stream.isStreaming]);

  const handleSubmit = (event) => {
    event.preventDefault();
    const text = question;
    setQuestion('');
    stream.send(text);
  };

  return (
    <MobileScreen title="학습메이트" showBackButton>
      {history.isLoading && stream.messages.length === 0 ? (
        <LoadingState label="대화를 불러오는 중입니다" />
      ) : (
        <div className="mobile-chat">
          <ul className="mobile-chat__messages">
            {stream.messages.map((message) => (
              <li
                key={message.id}
                className={message.role === 'user' ? 'mobile-chat__bubble is-user' : 'mobile-chat__bubble'}
              >
                {message.role === 'assistant' && (
                  <span className="mobile-chat__author">{message.agentName}</span>
                )}
                <p className="mobile-paragraph">{message.text}</p>
              </li>
            ))}

            {stream.isStreaming && (
              <li className="mobile-chat__bubble">
                <span className="mobile-state__spinner" />
              </li>
            )}

            <li ref={bottomRef} />
          </ul>

          {stream.errorMessage && <p className="mobile-auth__error">{stream.errorMessage}</p>}

          <form className="mobile-chat__composer" onSubmit={handleSubmit}>
            <textarea
              className="mobile-chat__input"
              value={question}
              rows={1}
              placeholder="무엇이든 물어보세요"
              onChange={(event) => setQuestion(event.target.value)}
            />

            {stream.isStreaming ? (
              <button type="button" className="mobile-chat__send is-stop" aria-label="중지" onClick={stream.stop}>
                <Square size={18} />
              </button>
            ) : (
              <button
                type="submit"
                className="mobile-chat__send"
                aria-label="전송"
                disabled={!question.trim()}
              >
                <Send size={18} />
              </button>
            )}
          </form>
        </div>
      )}
    </MobileScreen>
  );
}
