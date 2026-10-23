import React from 'react';
import { Minus, Plus } from 'lucide-react';
import TextField from '../../components/TextField';
import { personalityLabel } from '../../../utils/personality';
import {
  KNOWLEDGE_LEVELS,
  MATE_TYPES,
  MAX_AGENT_COUNT,
  MIN_AGENT_COUNT,
  REQUEST_GUIDE_CHIPS,
  TONE_OPTIONS,
  appendRequestChip,
  knowledgeLevelOf,
} from './agentDrafts';

function AgentCountControl({ total, onAdd, onRemove }) {
  return (
    <div className="mobile-agent-count">
      <span>인원</span>
      <button type="button" aria-label="에이전트 줄이기" disabled={total <= MIN_AGENT_COUNT} onClick={onRemove}>
        <Minus size={16} />
      </button>
      <strong>{total}명</strong>
      <button type="button" aria-label="에이전트 늘리기" disabled={total >= MAX_AGENT_COUNT} onClick={onAdd}>
        <Plus size={16} />
      </button>
    </div>
  );
}

function MateTypePicker({ selectedKey, onChoose }) {
  const selected = MATE_TYPES.find((type) => type.key === selectedKey);

  return (
    <div className="mobile-field">
      <span className="mobile-field__label">학습메이트 유형</span>
      <div className="mobile-choice-chips">
        {MATE_TYPES.map((type) => (
          <button
            key={type.key}
            type="button"
            className={type.key === selectedKey ? 'mobile-choice-chip is-active' : 'mobile-choice-chip'}
            onClick={() => onChoose(type.key)}
          >
            {type.icon} {type.key}
          </button>
        ))}
      </div>
      <p className="mobile-field__hint">{selected?.desc || '현재 AI 학습메이트의 역할과 말투를 선택하세요.'}</p>
    </div>
  );
}

function SelectField({ id, label, value, options, hint, onChange }) {
  return (
    <div className="mobile-field">
      <label className="mobile-field__label" htmlFor={id}>
        {label}
      </label>
      <select id={id} className="mobile-field__input" value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      {hint && <p className="mobile-field__hint">{hint}</p>}
    </div>
  );
}

function RequestChips({ customInstruction, onChange }) {
  return (
    <div className="mobile-choice-chips">
      {REQUEST_GUIDE_CHIPS.map((chip) => (
        <button
          key={chip.label}
          type="button"
          className="mobile-choice-chip"
          onClick={() => onChange(appendRequestChip(customInstruction, chip.text))}
        >
          + {chip.label}
        </button>
      ))}
    </div>
  );
}

export default function AgentDraftStep({ roomDraft, index }) {
  const { draft } = roomDraft;
  const agent = draft.agentDrafts[index];
  if (!agent) return null;

  const update = (patch) => roomDraft.updateAgent(index, patch);
  const knowledgeLevel = knowledgeLevelOf(agent.knowledgeLevel);

  return (
    <div className="mobile-agent-step">
      <div className="mobile-agent-step__header">
        <strong>AI 학습메이트 #{index + 1} 설정</strong>
        <AgentCountControl total={draft.agentDrafts.length} onAdd={roomDraft.addAgent} onRemove={roomDraft.removeAgent} />
      </div>
      <p className="mobile-field__hint">{agent.role || '이 AI 학습메이트의 역할과 말투, 학습자 수준, 추가 요청을 설정하세요.'}</p>

      <MateTypePicker selectedKey={agent.agentPreset} onChoose={(key) => roomDraft.chooseMateType(index, key)} />

      <TextField
        label="이름"
        value={agent.name}
        maxLength={30}
        placeholder="예: 김영한"
        onChange={(event) => update({ name: event.target.value, nameEdited: true })}
      />

      <SelectField
        id={`agent-${index}-tone`}
        label="답변 톤"
        value={personalityLabel(agent.personality)}
        options={TONE_OPTIONS}
        hint="AI가 어떤 말투로 설명할지 정합니다."
        onChange={(personality) => update({ personality })}
      />

      <SelectField
        id={`agent-${index}-level`}
        label="학습자 수준"
        value={knowledgeLevel.value}
        options={KNOWLEDGE_LEVELS}
        hint={knowledgeLevel.desc}
        onChange={(value) => update({ knowledgeLevel: value })}
      />

      <TextField
        as="textarea"
        label="추가 요청"
        hint="답변에 꼭 반영하고 싶은 조건이 있으면 적어주세요."
        value={agent.customInstruction}
        maxLength={1000}
        rows={3}
        placeholder="예: 코드 예시를 포함해줘 / 마지막에 3줄 요약해줘"
        onChange={(event) => update({ customInstruction: event.target.value })}
      />
      <RequestChips customInstruction={agent.customInstruction} onChange={(customInstruction) => update({ customInstruction })} />
    </div>
  );
}
