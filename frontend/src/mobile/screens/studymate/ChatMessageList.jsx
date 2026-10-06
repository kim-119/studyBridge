import React from 'react';
import { AtSign, MessageSquare, RefreshCw } from 'lucide-react';
import MarkdownText from '../../components/MarkdownText';
import AgentIdentityLabel from './AgentIdentityLabel';
import { agentStyleOf, identityOfMessage, identityOfStage, resolveAnswerAgent } from './agentAnswers';
import { isAnswerMessage, isUserMessage, stripLegacyActBadge } from './chatMessages';
import './studymateAgents.css';

const RISK_LABELS = { high: '높음', medium: '중간', low: '낮음' };

function bubbleClassName(message, agent) {
  return [
    'mobile-chat__bubble',
    'mobile-chat__bubble--agent',
    agent ? 'has-agent' : '',
    message.isError ? 'is-error' : '',
  ]
    .filter(Boolean)
    .join(' ');
}

function ActBadge({ message }) {
  if (message.actType === 'REACTION') {
    return <span className="mobile-chat__badge">💬 보충·반박{message.replyToName ? ` → ${message.replyToName}` : ''}</span>;
  }
  if (message.actType === 'WRAP') return <span className="mobile-chat__badge">🧩 정리</span>;
  if (message.stageTitle) return <span className="mobile-chat__badge">{message.stageTitle}</span>;
  return null;
}

function ValidationSummary({ validation }) {
  if (!validation) return null;
  const score = typeof validation.factualityScore === 'number'
    ? Math.round(validation.factualityScore <= 1 ? validation.factualityScore * 100 : validation.factualityScore)
    : null;
  const risk = RISK_LABELS[validation.riskLevel];
  const notes = [...validation.unsupportedClaims, ...validation.contradictions, ...validation.evidenceNotes].slice(0, 5);

  return (
    <div className="mobile-chat__validation">
      <strong>검증 결과</strong>
      <div className="mobile-chat__validation-chips">
        {score != null && <span>사실성 {score}%</span>}
        {risk && <span className={validation.riskLevel === 'high' ? 'is-danger' : ''}>위험도 {risk}</span>}
      </div>
      {notes.length > 0 && (
        <ul className="mobile-md__list">
          {notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      )}
      {validation.safeRevisionHint && <p className="mobile-card__meta">보완 제안 {validation.safeRevisionHint}</p>}
    </div>
  );
}

function StageChoices({ choices, onChoose, disabled }) {
  if (!choices.length) return null;
  return (
    <div className="mobile-chat__choices">
      {choices.map((choice, index) => (
        <button
          key={choice.choiceId || choice.label || index}
          type="button"
          className="mobile-chat__choice"
          disabled={disabled}
          onClick={() => onChoose(choice)}
        >
          {choice.label || choice.choiceId}
          {choice.text || choice.description ? ` · ${choice.text || choice.description}` : ''}
        </button>
      ))}
    </div>
  );
}

function TurnStage({ stage, roomAgents, onChoose, isStreaming }) {
  const agent = resolveAnswerAgent(identityOfStage(stage), roomAgents);

  return (
    <li
      className={agent ? 'mobile-chat__stage has-agent' : 'mobile-chat__stage'}
      data-agent-key={agent?.key}
      style={agentStyleOf(agent)}
    >
      <span className="mobile-chat__stage-title">{stage.title}</span>
      {agent && <AgentIdentityLabel agent={agent} />}
      <MarkdownText>{stage.content}</MarkdownText>
      <StageChoices choices={stage.choices} onChoose={onChoose} disabled={isStreaming} />
    </li>
  );
}

function StructuredTurnBubble({ message, roomAgents, onChoose, isStreaming }) {
  return (
    <li className="mobile-chat__bubble mobile-chat__bubble--agent mobile-chat__bubble--wide">
      <span className="mobile-chat__author">{message.senderName}</span>
      <ol className="mobile-chat__stages">
        {message.stages.map((stage, index) => (
          <TurnStage
            key={`${stage.stageType}-${stage.side || ''}-${index}`}
            stage={stage}
            roomAgents={roomAgents}
            onChoose={onChoose}
            isStreaming={isStreaming}
          />
        ))}
      </ol>
    </li>
  );
}

function AgentBubble({ message, roomAgents, onMention, onRetry, isStreaming }) {
  const agent = resolveAnswerAgent(identityOfMessage(message), roomAgents);
  const speaker = agent && agent.slot >= 0 ? roomAgents[agent.slot] : null;

  return (
    <li className={bubbleClassName(message, agent)} data-agent-key={agent?.key} style={agentStyleOf(agent)}>
      <span className="mobile-chat__author">
        <AgentIdentityLabel agent={agent} fallbackName={message.senderName || 'AI'} />
        <ActBadge message={message} />
      </span>

      {message.isPending ? (
        <p className="mobile-chat__pending">{message.statusText || '답변 생성 중…'}</p>
      ) : (
        <MarkdownText>{stripLegacyActBadge(message.content)}</MarkdownText>
      )}

      <ValidationSummary validation={message.validation} />

      {message.canRetry && message.retryMessage && (
        <button type="button" className="mobile-chat__mention" disabled={isStreaming} onClick={() => onRetry(message)}>
          <RefreshCw size={14} />
          다시 시도
        </button>
      )}

      {speaker && isAnswerMessage(message) && (
        <button type="button" className="mobile-chat__mention" onClick={() => onMention(speaker)}>
          <AtSign size={14} />이 교수님께 추가 질문
        </button>
      )}
    </li>
  );
}

export default function ChatMessageList({ messages, roomAgents, isStreaming, onMention, onRetry, onChoose }) {
  if (messages.length === 0 && !isStreaming) {
    return (
      <div className="mobile-chat__empty">
        <MessageSquare size={32} />
        <p className="mobile-state__text">질문을 입력해보세요.</p>
      </div>
    );
  }

  return (
    <ul className="mobile-chat__messages">
      {messages.map((message) => {
        if (isUserMessage(message)) {
          return (
            <li key={message.id} className="mobile-chat__bubble is-user">
              <p className="mobile-paragraph">{message.content}</p>
            </li>
          );
        }
        if (message.turnKind) {
          return (
            <StructuredTurnBubble
              key={message.id}
              message={message}
              roomAgents={roomAgents}
              onChoose={onChoose}
              isStreaming={isStreaming}
            />
          );
        }
        return (
          <AgentBubble
            key={message.id}
            message={message}
            roomAgents={roomAgents}
            onMention={onMention}
            onRetry={onRetry}
            isStreaming={isStreaming}
          />
        );
      })}

      {isStreaming && (
        <li className="mobile-chat__typing" aria-live="polite">
          <span className="mobile-state__spinner" />
          답변 작성 중...
        </li>
      )}
    </ul>
  );
}
