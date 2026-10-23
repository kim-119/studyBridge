import React from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import TextField from '../../components/TextField';
import ChoiceChips from './ChoiceChips';
import { STUDYBRIDGE_ROOM_TITLE } from './agentDrafts';
import {
  CHOICE_COUNT_OPTIONS,
  DEBATE_STRENGTH_OPTIONS,
  DIFFICULTY_OPTIONS,
  HINT_STYLE_OPTIONS,
  LEARNING_MODE_OPTIONS,
  MODE_SETTING_INTRO,
  QUESTION_INTENSITY_OPTIONS,
  SCENARIO_TYPE_OPTIONS,
  summarizeRoomPreset,
} from './learningModes';

const CHOICE_COUNT_CHIPS = CHOICE_COUNT_OPTIONS.map((count) => ({ value: count, label: `${count}개` }));

function ModeCards({ value, onSelect }) {
  return (
    <div className="mobile-field">
      <span className="mobile-field__label">학습 방식 선택</span>
      <p className="mobile-field__hint">같은 질문도 학습 방식에 따라 완전히 다르게 배울 수 있습니다.</p>
      <div className="mobile-mode-cards" role="radiogroup" aria-label="학습 방식">
        {LEARNING_MODE_OPTIONS.map((option) => (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={option.value === value}
            className={option.value === value ? 'mobile-mode-card is-active' : 'mobile-mode-card'}
            onClick={() => onSelect(option.value)}
          >
            <strong>{option.title}</strong>
            <span>{option.desc}</span>
            <span className="mobile-mode-card__result">결과: {option.result}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

function PresetCarousel({ presets, presetIndex, selectedPresetId, onShow, onApply }) {
  if (!presets.length) return null;

  const index = Math.min(presetIndex, presets.length - 1);
  const preset = presets[index];
  const isSelected = selectedPresetId === preset.id;

  return (
    <div className="mobile-field">
      <span className="mobile-field__label">추천 방 설정</span>
      <p className="mobile-field__hint">카드를 누르면 세부 설정과 추천 에이전트가 자동으로 채워집니다.</p>

      <div className="mobile-preset-nav">
        <button type="button" aria-label="이전 추천 방 설정" disabled={index === 0} onClick={() => onShow(index - 1)}>
          <ChevronLeft size={18} />
        </button>
        <span>
          {index + 1} / {presets.length}
        </span>
        <button type="button" aria-label="다음 추천 방 설정" disabled={index === presets.length - 1} onClick={() => onShow(index + 1)}>
          <ChevronRight size={18} />
        </button>
      </div>

      <button
        type="button"
        aria-pressed={isSelected}
        className={isSelected ? 'mobile-mode-card is-active' : 'mobile-mode-card'}
        onClick={() => onApply(preset)}
      >
        <span className="mobile-mode-card__result">
          {preset.label} · {isSelected ? '선택됨' : '누르면 적용'}
        </span>
        <strong>{preset.title}</strong>
        <span>{preset.purpose}</span>
        <span className="mobile-mode-card__result">{summarizeRoomPreset(preset).join(' · ')}</span>
        <span className="mobile-mode-card__result">
          에이전트 {preset.agents.length}명 · {preset.agents.map((agent) => agent.name).join(' · ')}
        </span>
      </button>
    </div>
  );
}

function ModeSettings({ draft, updateConfig }) {
  const intro = MODE_SETTING_INTRO[draft.learningMode];

  return (
    <div className="mobile-mode-settings">
      <strong>{intro.title}</strong>
      <p className="mobile-field__hint">{intro.desc}</p>

      {draft.learningMode === 'socratic' && (
        <>
          <ChoiceChips
            label="질문 강도"
            options={QUESTION_INTENSITY_OPTIONS}
            value={draft.socraticConfig.questionIntensity}
            onChange={(questionIntensity) => updateConfig('socraticConfig', { questionIntensity })}
          />
          <ChoiceChips
            label="힌트 방식"
            options={HINT_STYLE_OPTIONS}
            value={draft.socraticConfig.hintPolicy}
            onChange={(hintPolicy) => updateConfig('socraticConfig', { hintPolicy })}
          />
        </>
      )}

      {draft.learningMode === 'debate' && (
        <ChoiceChips
          label="토론 강도"
          options={DEBATE_STRENGTH_OPTIONS}
          value={draft.debateConfig.debateStrength}
          onChange={(debateStrength) => updateConfig('debateConfig', { debateStrength })}
        />
      )}

      {draft.learningMode === 'simulation' && (
        <>
          <ChoiceChips
            label="상황 유형"
            options={SCENARIO_TYPE_OPTIONS}
            value={draft.simulationConfig.scenarioType}
            onChange={(scenarioType) => updateConfig('simulationConfig', { scenarioType })}
          />
          <ChoiceChips
            label="난이도"
            options={DIFFICULTY_OPTIONS}
            value={draft.simulationConfig.difficulty}
            onChange={(difficulty) => updateConfig('simulationConfig', { difficulty })}
          />
          <ChoiceChips
            label="선택지 개수"
            options={CHOICE_COUNT_CHIPS}
            value={Number(draft.simulationConfig.choiceCount)}
            onChange={(choiceCount) => updateConfig('simulationConfig', { choiceCount })}
          />
        </>
      )}
    </div>
  );
}

export default function RoomSetupStep({ roomDraft }) {
  const { draft, presets } = roomDraft;

  return (
    <>
      <TextField
        label="스터디방 이름"
        value={draft.roomName}
        maxLength={40}
        placeholder={STUDYBRIDGE_ROOM_TITLE}
        onChange={(event) => roomDraft.update({ roomName: event.target.value })}
      />
      <ModeCards value={draft.learningMode} onSelect={roomDraft.selectMode} />
      <PresetCarousel
        presets={presets}
        presetIndex={draft.presetIndex}
        selectedPresetId={draft.selectedPresetId}
        onShow={roomDraft.showPreset}
        onApply={roomDraft.applyPreset}
      />
      <ModeSettings draft={draft} updateConfig={roomDraft.updateConfig} />
      <p className="mobile-field__hint">
        AI 학습메이트는 1~3명까지 구성할 수 있습니다. 다음 버튼으로 학습메이트 #1 → #2 → #3 설정을 확인하세요.
      </p>
    </>
  );
}
