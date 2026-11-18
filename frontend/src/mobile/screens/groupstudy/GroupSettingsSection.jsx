import React from 'react';
import TextField from '../../components/TextField';
import {
  JOIN_QUESTION_MAX_LENGTH,
  NICKNAME_RULE_MAX_LENGTH,
  STUDY_TYPE_OPTIONS,
  TARGET_STUDY_MINUTE_OPTIONS,
  formatTargetMinutes,
  normalizeStudyType,
} from '../../../utils/groupStudy.js';

function StudyTypePicker({ studyType, onChange }) {
  const selectedType = normalizeStudyType(studyType);
  const selectedOption = STUDY_TYPE_OPTIONS.find((option) => option.value === selectedType);

  return (
    <>
      <span className="mobile-field__label">스터디 방식</span>
      <div className="mobile-segmented">
        {STUDY_TYPE_OPTIONS.map((option) => (
          <button
            key={option.value}
            type="button"
            className={option.value === selectedType ? 'is-active' : ''}
            aria-pressed={option.value === selectedType}
            onClick={() => onChange(option.value)}
          >
            {option.label}
          </button>
        ))}
      </div>
      <p className="mobile-field__hint">{selectedOption.description}</p>
    </>
  );
}

function TargetMinutesPicker({ targetStudyMinutes, onChange }) {
  return (
    <>
      <span className="mobile-field__label">하루 목표 공부 시간</span>
      <div className="mobile-segmented mobile-group-settings__target">
        {TARGET_STUDY_MINUTE_OPTIONS.map((minutes) => (
          <button
            key={minutes}
            type="button"
            className={Number(targetStudyMinutes) === minutes ? 'is-active' : ''}
            aria-pressed={Number(targetStudyMinutes) === minutes}
            onClick={() => onChange(minutes)}
          >
            {formatTargetMinutes(minutes)}
          </button>
        ))}
      </div>
    </>
  );
}

function PolicyToggle({ label, isEnabled, onChange }) {
  return (
    <label className="mobile-checkbox mobile-group-settings__toggle">
      <input
        type="checkbox"
        aria-label={label}
        checked={isEnabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span>{label}</span>
    </label>
  );
}

export default function GroupSettingsSection({ form, error, onChange }) {
  return (
    <section className="mobile-card mobile-section">
      <h2 className="mobile-section__title">스터디 운영 방식</h2>

      <StudyTypePicker studyType={form.studyType} onChange={(value) => onChange('studyType', value)} />
      <TargetMinutesPicker
        targetStudyMinutes={form.targetStudyMinutes}
        onChange={(value) => onChange('targetStudyMinutes', value)}
      />

      <PolicyToggle
        label="가입 질문 사용"
        isEnabled={form.joinQuestionEnabled}
        onChange={(value) => onChange('joinQuestionEnabled', value)}
      />
      {form.joinQuestionEnabled && (
        <TextField
          as="textarea"
          label="가입 질문"
          value={form.joinQuestion}
          maxLength={JOIN_QUESTION_MAX_LENGTH}
          placeholder="예: 이번 스터디에서 이루고 싶은 목표는 무엇인가요?"
          hint={`${form.joinQuestion.length} / ${JOIN_QUESTION_MAX_LENGTH}`}
          onChange={(event) => onChange('joinQuestion', event.target.value)}
        />
      )}

      <PolicyToggle
        label="그룹 닉네임 규칙 사용"
        isEnabled={form.nicknameRuleEnabled}
        onChange={(value) => onChange('nicknameRuleEnabled', value)}
      />
      {form.nicknameRuleEnabled && (
        <TextField
          label="닉네임 규칙 안내"
          value={form.nicknameRule}
          maxLength={NICKNAME_RULE_MAX_LENGTH}
          placeholder="예: 학교/학년/이름"
          hint={`${form.nicknameRule.length} / ${NICKNAME_RULE_MAX_LENGTH}`}
          onChange={(event) => onChange('nicknameRule', event.target.value)}
        />
      )}

      {error && <p className="mobile-field__error">{error}</p>}
    </section>
  );
}
