import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Button from '../../components/Button';
import TextField from '../../components/TextField';
import MobileScreen from '../../shell/MobileScreen';
import { plannerService } from '../../../services/api';
import { useSubmit } from '../../data/useAsync';
import { PRIORITY_OPTIONS, STUDY_TYPE_OPTIONS, toPlannerRequest } from './plannerAdapter';

export default function PlannerCreateScreen() {
  const navigate = useNavigate();
  const [form, setForm] = useState({
    title: '',
    subject: '',
    term: '',
    studyType: STUDY_TYPE_OPTIONS[0],
    priority: PRIORITY_OPTIONS[1],
    goalTime: '',
    date: '',
    content: '',
  });

  const updateField = (field) => (event) =>
    setForm((previous) => ({ ...previous, [field]: event.target.value }));

  const createPlanner = useSubmit(async () => {
    const created = await plannerService.createPlanner(toPlannerRequest(form));
    navigate(created?.id ? `/planner/${created.id}` : '/planner', { replace: true });
  });

  const handleSubmit = (event) => {
    event.preventDefault();
    createPlanner.submit().catch(() => {});
  };

  return (
    <MobileScreen title="새 플래너" showBackButton>
      <form onSubmit={handleSubmit}>
        <TextField label="제목" value={form.title} onChange={updateField('title')} />
        <TextField label="과목명" value={form.subject} onChange={updateField('subject')} />
        <TextField label="학기/주차" value={form.term} hint="예: 2학기 3주차" onChange={updateField('term')} />

        <div className="mobile-field">
          <label className="mobile-field__label" htmlFor="planner-study-type">
            학습 유형
          </label>
          <select
            id="planner-study-type"
            className="mobile-field__input"
            value={form.studyType}
            onChange={updateField('studyType')}
          >
            {STUDY_TYPE_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </div>

        <div className="mobile-field">
          <label className="mobile-field__label" htmlFor="planner-priority">
            우선순위
          </label>
          <select
            id="planner-priority"
            className="mobile-field__input"
            value={form.priority}
            onChange={updateField('priority')}
          >
            {PRIORITY_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </div>

        <TextField label="목표 학습 시간" value={form.goalTime} hint="예: 3시간" onChange={updateField('goalTime')} />
        <TextField label="마감일" type="date" value={form.date} onChange={updateField('date')} />

        <TextField
          as="textarea"
          label="상세 학습 목표"
          value={form.content}
          error={createPlanner.errorMessage}
          onChange={updateField('content')}
        />

        <Button type="submit" fullWidth isLoading={createPlanner.isSubmitting} disabled={!form.title.trim()}>
          플래너 만들기
        </Button>
      </form>
    </MobileScreen>
  );
}
