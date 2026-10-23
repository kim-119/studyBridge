import React from 'react';
import { AtSign, GitCompare, PencilLine, Users } from 'lucide-react';
import PixelProfessorStage from '../../../components/studymate/pixel/PixelProfessorStage';
import { knowledgeLevelOf } from './agentDrafts';
import { agentRoleText, agentStyleOf, identityOfRoomAgent } from './agentAnswers';
import ProfessorAnswerList from './ProfessorAnswerList';
import { professorRoleOfSlot } from './professorActions';
import './studymateAgents.css';

const VISUAL_STATE_LABELS = {
  walking_to_question: '준비 중',
  thinking: '생각 중',
  listening: '듣는 중',
  answering: '답변 중',
  validating: '검증 중',
  peer_feedback: '피드백 중',
  returning: '정리 중',
  completed: '완료',
  error: '오류',
};

function ProfessorCard({ agent, slot, visualState, onAskOne }) {
  const identity = identityOfRoomAgent(agent, slot);
  const knowledgeLabel = agent.knowledgeLevel ? knowledgeLevelOf(agent.knowledgeLevel).label : '';

  return (
    <li className="mobile-professor-card has-agent" data-agent-key={identity.key} style={agentStyleOf(identity)}>
      <div className="mobile-professor-card__body">
        <strong className="mobile-professor-card__name">{agent.name || `교수 ${slot + 1}`}</strong>
        <span className="mobile-card__meta">{[agentRoleText(agent), knowledgeLabel].filter(Boolean).join(' · ')}</span>
        {VISUAL_STATE_LABELS[visualState] && <span className="mobile-chat__badge">{VISUAL_STATE_LABELS[visualState]}</span>}
      </div>
      <button type="button" className="mobile-chat__mention" onClick={() => onAskOne(professorRoleOfSlot(slot))}>
        <AtSign size={14} />이 교수에게 질문
      </button>
    </li>
  );
}

export default function ProfessorTab({ roomAgents, messages = [], stage, onRefine, onAskOne, onAskAll, onCompare }) {
  return (
    <div className="mobile-professor-tab">
      <div className="mobile-professor-stage">
        <PixelProfessorStage
          visualStates={stage.visualStates}
          agents={roomAgents}
          bubbles={stage.bubbles}
          stageStatusMessage={stage.statusMessage}
          onAutoReset={stage.autoReset}
          selectedRole={stage.selectedRole}
          onSelectRole={stage.setSelectedRole}
          recap={stage.recap}
          onRecapDismiss={stage.dismissRecap}
          onRefine={onRefine}
          onAskProfessor={onAskOne}
          onAskAll={onAskAll}
          onCompare={onCompare}
        />
      </div>

      <ProfessorAnswerList messages={messages} roomAgents={roomAgents} />

      <div className="mobile-professor-tab__actions">
        <button type="button" className="mobile-chat__mention" onClick={onRefine}>
          <PencilLine size={14} />
          질문 정제
        </button>
        <button type="button" className="mobile-chat__mention" onClick={onAskAll}>
          <Users size={14} />
          모두에게 질문
        </button>
        <button type="button" className="mobile-chat__mention" onClick={onCompare}>
          <GitCompare size={14} />
          답변 비교
        </button>
      </div>

      <ul className="mobile-professor-tab__cards">
        {roomAgents.map((agent, slot) => (
          <ProfessorCard
            key={agent.agentId ?? agent.id ?? slot}
            agent={agent}
            slot={slot}
            visualState={stage.visualStates[professorRoleOfSlot(slot)]}
            onAskOne={onAskOne}
          />
        ))}
      </ul>
    </div>
  );
}
