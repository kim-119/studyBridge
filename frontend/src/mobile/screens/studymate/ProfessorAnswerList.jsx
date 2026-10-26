import React, { useMemo } from 'react';
import MarkdownText from '../../components/MarkdownText';
import AgentIdentityLabel from './AgentIdentityLabel';
import { agentStyleOf, groupAnswersByAgent, latestTurnAnswerEntries } from './agentAnswers';

const UNASSIGNED_GROUP_NAME = '공통 진행';

function AnswerEntry({ entry }) {
  return (
    <div className={entry.isError ? 'mobile-professor-answer__entry is-error' : 'mobile-professor-answer__entry'}>
      {entry.title && <span className="mobile-chat__badge">{entry.title}</span>}
      {entry.isPending ? (
        <p className="mobile-chat__pending">{entry.content}</p>
      ) : (
        <MarkdownText>{entry.content}</MarkdownText>
      )}
    </div>
  );
}

function AgentAnswerGroup({ group }) {
  return (
    <li
      className={group.agent ? 'mobile-professor-answer has-agent' : 'mobile-professor-answer'}
      data-agent-key={group.key}
      style={agentStyleOf(group.agent)}
    >
      <AgentIdentityLabel agent={group.agent} fallbackName={UNASSIGNED_GROUP_NAME} />
      {group.entries.map((entry) => (
        <AnswerEntry key={entry.id} entry={entry} />
      ))}
    </li>
  );
}

export default function ProfessorAnswerList({ messages, roomAgents }) {
  const groups = useMemo(
    () => groupAnswersByAgent(latestTurnAnswerEntries(messages), roomAgents),
    [messages, roomAgents]
  );

  if (groups.length === 0) return null;

  return (
    <section className="mobile-professor-answers" aria-label="이번 질문에 대한 교수님 답변">
      <h3 className="mobile-professor-answers__title">이번 질문 답변</h3>
      <ul className="mobile-professor-answers__list">
        {groups.map((group) => (
          <AgentAnswerGroup key={group.key} group={group} />
        ))}
      </ul>
    </section>
  );
}
