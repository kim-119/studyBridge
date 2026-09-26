import React, { useEffect, useMemo, useRef, useState } from 'react';
import { AtSign, RotateCcw, Send, Square } from 'lucide-react';
import { useParams } from 'react-router-dom';
import MarkdownText from '../../components/MarkdownText';
import { ErrorState, LoadingState } from '../../components/ScreenState';
import MobileScreen from '../../shell/MobileScreen';
import { agentService } from '../../../services/api';
import { getAgentColor } from '../../../utils/agentColor';
import { useAsync } from '../../data/useAsync';
import { useStudyMateStream } from './useStudyMateStream';

function historyToMessages(history) {
  const entries = Array.isArray(history) ? history : history?.messages || [];

  return entries.map((entry, index) => ({
    id: entry.id ?? `history-${index}`,
    role: entry.role === 'user' || entry.sender === 'user' ? 'user' : 'assistant',
    agentId: entry.agentId ?? entry.agent_id ?? null,
    agentName: entry.agentName || entry.agent_name || 'AI 메이트',
    text: entry.content || entry.message || entry.answer || '',
    isSealed: true,
  }));
}

function AgentBubble({ message, onMention }) {
  const palette = getAgentColor(message.agentId ?? message.agentName);

  return (
    <li
      className="mobile-chat__bubble mobile-chat__bubble--agent"
      style={{ borderLeftColor: palette.border, backgroundColor: palette.bg }}
    >
      <span className="mobile-chat__author" style={{ color: palette.text }}>
        {message.agentName}
      </span>

      <MarkdownText>{message.text}</MarkdownText>

      {message.isSealed && (
        <button
          type="button"
          className="mobile-chat__mention"
          onClick={() => onMention(message.agentName)}
        >
          <AtSign size={14} />이 교수님께 추가 질문
        </button>
      )}
    </li>
  );
}

export default function StudyMateChatScreen() {
  const { roomId } = useParams();
  const stream = useStudyMateStream(roomId);
  const [question, setQuestion] = useState('');
  const bottomRef = useRef(null);
  const inputRef = useRef(null);

  const history = useAsync(() => agentService.getChatHistory(null, roomId), [roomId]);

  useEffect(() => {
    if (!history.data) return;
    stream.setMessages(historyToMessages(history.data));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [history.data]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: 'end' });
  }, [stream.messages, stream.isStreaming]);

  const hasMultipleAgents = useMemo(() => {
    const names = new Set(
      stream.messages.filter((message) => message.role === 'assistant').map((message) => message.agentName)
    );
    return names.size > 1;
  }, [stream.messages]);

  const mentionAgent = (agentName) => {
    setQuestion((previous) => (previous.startsWith(`@${agentName}`) ? previous : `@${agentName} ${previous}`));
    inputRef.current?.focus();
  };

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
          {hasMultipleAgents && (
            <p className="mobile-chat__status">교수님별 답변은 색으로 구분됩니다</p>
          )}

          <ul className="mobile-chat__messages">
            {stream.messages.map((message) =>
              message.role === 'user' ? (
                <li key={message.id} className="mobile-chat__bubble is-user">
                  <p className="mobile-paragraph">{message.text}</p>
                </li>
              ) : (
                <AgentBubble key={message.id} message={message} onMention={mentionAgent} />
              )
            )}

            {stream.isStreaming && (
              <li className="mobile-chat__bubble">
                <span className="mobile-state__spinner" />
              </li>
            )}

            <li ref={bottomRef} />
          </ul>

          {stream.errorMessage && (
            <ErrorState
              message={stream.errorMessage}
              onRetry={stream.canRetry ? stream.retry : undefined}
            />
          )}

          {stream.isReconnecting && (
            <p className="mobile-chat__status">
              <RotateCcw size={14} />
              연결이 끊겨 다시 시도하는 중입니다 ({stream.retryAttempt}회차)
            </p>
          )}

          <form className="mobile-chat__composer" onSubmit={handleSubmit}>
            <textarea
              ref={inputRef}
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
