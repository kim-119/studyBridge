import React, { useLayoutEffect } from 'react';
import { Send, Square } from 'lucide-react';
import { MENTION_ALL, agentIdOf } from '../../../utils/agentIdentity';
import { followUpMessage, insertMention, mentionQueryOf } from './professorActions';

const MAX_INPUT_HEIGHT = 120;

function isComposingEnter(event) {
  return event.nativeEvent?.isComposing || event.keyCode === 229;
}

function mentionCandidates(roomAgents, query) {
  const everyone = { name: MENTION_ALL.slice(1), isEveryone: true };
  const needle = query.toLowerCase();
  return [everyone, ...roomAgents].filter((agent) => !needle || String(agent.name || '').toLowerCase().includes(needle));
}

function useAutoGrow(inputRef, value) {
  useLayoutEffect(() => {
    const element = inputRef.current;
    if (!element) return;
    element.style.height = 'auto';
    element.style.height = `${Math.min(element.scrollHeight, MAX_INPUT_HEIGHT)}px`;
  }, [inputRef, value]);
}

function MentionPicker({ draft, roomAgents, onPick }) {
  const query = mentionQueryOf(draft);
  if (query == null) return null;

  const candidates = mentionCandidates(roomAgents, query);
  if (!candidates.length) return null;

  return (
    <div className="mobile-chat__mentions" role="listbox" aria-label="교수 멘션">
      {candidates.map((agent) => (
        <button key={agent.isEveryone ? 'everyone' : agentIdOf(agent) ?? agent.name} type="button" onClick={() => onPick(agent)}>
          @{agent.name}
        </button>
      ))}
    </div>
  );
}

function FollowUpChips({ chips, onSend }) {
  if (!chips.length) return null;
  return (
    <div className="mobile-chat__followups">
      {chips.map((chip) => (
        <button key={chip.id || chip.label} type="button" onClick={() => onSend(followUpMessage(chip))}>
          {chip.label}
        </button>
      ))}
    </div>
  );
}

export default function ChatComposer({
  inputRef,
  draft,
  onDraftChange,
  onSubmit,
  onStop,
  onPickMention,
  onSendFollowUp,
  followUps,
  roomAgents,
  isStreaming,
}) {
  useAutoGrow(inputRef, draft);

  const handleKeyDown = (event) => {
    if (event.key !== 'Enter') return;
    if (isComposingEnter(event)) {
      event.preventDefault();
      return;
    }
    if (event.shiftKey) return;
    event.preventDefault();
    onSubmit();
  };

  const pickMention = (agent) => {
    onDraftChange(insertMention(draft, agent.name));
    onPickMention(agent.isEveryone ? null : agentIdOf(agent));
    inputRef.current?.focus();
  };

  return (
    <div className="mobile-chat__dock">
      <MentionPicker draft={draft} roomAgents={roomAgents} onPick={pickMention} />
      {!isStreaming && <FollowUpChips chips={followUps} onSend={onSendFollowUp} />}

      <form
        className="mobile-chat__composer"
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit();
        }}
      >
        <textarea
          ref={inputRef}
          className="mobile-chat__input"
          value={draft}
          rows={1}
          enterKeyHint="send"
          placeholder={isStreaming ? '새 질문을 보내면 현재 답변 생성을 중단합니다' : '질문을 입력하세요 (@로 교수 호출)'}
          onChange={(event) => onDraftChange(event.target.value)}
          onKeyDown={handleKeyDown}
        />

        {isStreaming && !draft.trim() ? (
          <button type="button" className="mobile-chat__send is-stop" aria-label="답변 생성 중단" onClick={onStop}>
            <Square size={18} />
          </button>
        ) : (
          <button type="submit" className="mobile-chat__send" aria-label="전송" disabled={!draft.trim()}>
            <Send size={18} />
          </button>
        )}
      </form>
    </div>
  );
}
