import React from 'react';
import { Users, Video } from 'lucide-react';
import SettingRow from './SettingRow';
import { ToggleRow } from './ToggleSwitch';
import {
  STUDY_TYPES, STUDY_TYPE_OPTIONS, TARGET_STUDY_MINUTE_OPTIONS,
  JOIN_QUESTION_MAX_LENGTH, NICKNAME_RULE_MAX_LENGTH, formatTargetMinutes,
} from '../../utils/groupStudy';

export const DEFAULT_SETTINGS_FORM = Object.freeze({
  studyType: STUDY_TYPES.GENERAL,
  targetStudyMinutes: 240,
  joinQuestionEnabled: false,
  joinQuestion: '',
  nicknameRuleEnabled: false,
  nicknameRule: '',
  studyIconId: null,
});

// 운영 정책 입력 섹션(스터디 방식 / 학습 목표 / 가입 설정 / 그룹 닉네임).
// 생성 폼과 수정 모달이 같은 컴포넌트를 쓴다. value 는 DEFAULT_SETTINGS_FORM 모양, onChange(patch) 로 부분 갱신.
export default function GroupSettingsFields({ value, onChange, showSectionTitles = true }) {
  const patch = (p) => onChange({ ...value, ...p });

  return (
    <>
      {/* 스터디 방식 */}
      {showSectionTitles && <h3 className="gs-section-title">스터디 방식</h3>}
      <SettingRow label="스터디 방식" required hint="캠 스터디는 캠 중심 운영 그룹임을 표시합니다. 영상/음성 기능은 두 방식 모두 기존과 동일하게 사용할 수 있습니다.">
        <div className="gs-segment" role="group" aria-label="스터디 방식">
          {STUDY_TYPE_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              className="gs-segment-option"
              aria-pressed={value.studyType === opt.value ? 'true' : 'false'}
              onClick={() => patch({ studyType: opt.value })}
            >
              <span className="gs-segment-option-title">
                {opt.value === STUDY_TYPES.CAM ? <Video size={15} /> : <Users size={15} />}
                {opt.label}
              </span>
              <span className="gs-segment-option-desc">{opt.description}</span>
            </button>
          ))}
        </div>
      </SettingRow>

      {/* 학습 목표 */}
      {showSectionTitles && <h3 className="gs-section-title">학습 목표</h3>}
      <SettingRow label="하루 목표시간" required hint="그룹원이 하루에 채우기로 약속하는 공부시간입니다. (4시간 ~ 10시간)">
        <div className="gs-chip-group" role="group" aria-label="하루 목표 공부시간">
          {TARGET_STUDY_MINUTE_OPTIONS.map((minutes) => (
            <button
              key={minutes}
              type="button"
              className="gs-chip"
              aria-pressed={Number(value.targetStudyMinutes) === minutes ? 'true' : 'false'}
              onClick={() => patch({ targetStudyMinutes: minutes })}
            >
              {formatTargetMinutes(minutes)}
            </button>
          ))}
        </div>
      </SettingRow>

      {/* 가입 설정 */}
      {showSectionTitles && <h3 className="gs-section-title">가입 설정</h3>}
      <SettingRow label="가입 질문">
        <ToggleRow
          title="가입 질문 받기"
          description={value.joinQuestionEnabled ? '가입 신청 시 아래 질문에 답해야 합니다.' : '질문 없이 기존 가입 절차를 그대로 사용합니다.'}
          checked={value.joinQuestionEnabled}
          onChange={(checked) => patch({ joinQuestionEnabled: checked })}
        />
        {value.joinQuestionEnabled && (
          <>
            <textarea
              className="gs-textarea"
              placeholder="예) 어떤 목표를 가지고 있나요?"
              value={value.joinQuestion}
              maxLength={JOIN_QUESTION_MAX_LENGTH}
              onChange={(e) => patch({ joinQuestion: e.target.value })}
              aria-label="가입 질문"
            />
            <div className="gs-counter">{value.joinQuestion.length} / {JOIN_QUESTION_MAX_LENGTH}</div>
          </>
        )}
      </SettingRow>

      {/* 그룹 닉네임 */}
      {showSectionTitles && <h3 className="gs-section-title">그룹 닉네임</h3>}
      <SettingRow label="닉네임 규칙">
        <ToggleRow
          title="그룹 닉네임 규칙"
          description={value.nicknameRuleEnabled ? '가입 시 규칙에 맞는 그룹 닉네임을 입력받습니다.' : '기존 사용자 표시명을 그대로 사용합니다.'}
          checked={value.nicknameRuleEnabled}
          onChange={(checked) => patch({ nicknameRuleEnabled: checked })}
        />
        {value.nicknameRuleEnabled && (
          <>
            <input
              type="text"
              className="gs-input"
              placeholder="예) 학교/학년/닉네임 형식으로 입력해주세요."
              value={value.nicknameRule}
              maxLength={NICKNAME_RULE_MAX_LENGTH}
              onChange={(e) => patch({ nicknameRule: e.target.value })}
              aria-label="그룹 닉네임 규칙"
            />
            <div className="gs-counter">{value.nicknameRule.length} / {NICKNAME_RULE_MAX_LENGTH}</div>
          </>
        )}
      </SettingRow>
    </>
  );
}
