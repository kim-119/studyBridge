import React, { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import Button from '../../components/Button';
import ScreenState from '../../components/ScreenState';
import TextField from '../../components/TextField';
import MobileScreen from '../../shell/MobileScreen';
import { plannerService } from '../../../services/api';
import { useAsync, useSubmit } from '../../data/useAsync';
import TimeTableGrid from './TimeTableGrid';
import {
  PRIORITY_OPTIONS,
  STUDY_TYPE_OPTIONS,
  formatMinutes,
  plannedMinutes,
  toPlannerDetail,
  toPlannerForm,
  toPlannerRequest,
  toggleSlot,
} from './plannerAdapter';

const EMPTY_FORM = {
  title: '',
  subject: '',
  term: '',
  studyType: STUDY_TYPE_OPTIONS[0],
  priority: PRIORITY_OPTIONS[1],
  goalTime: '',
  date: '',
  content: '',
};

export default function PlannerFormScreen({ mode }) {
  const { plannerId } = useParams();
  const navigate = useNavigate();
  const isEdit = mode === 'edit';

  const [form, setForm] = useState(EMPTY_FORM);
  const [timeTable, setTimeTable] = useState({});

  const existing = useAsync(
    async () => (isEdit ? toPlannerDetail(await plannerService.getPlanner(plannerId)) : null),
    [plannerId, isEdit],
    { immediate: isEdit }
  );

  useEffect(() => {
    if (!existing.data) return;
    setForm(toPlannerForm(existing.data));
    setTimeTable(existing.data.timeTable || {});
  }, [existing.data]);

  const updateField = (field) => (event) =>
    setForm((previous) => ({ ...previous, [field]: event.target.value }));

  const savePlanner = useSubmit(async () => {
    const payload = toPlannerRequest(form, timeTable);

    if (isEdit) {
      await plannerService.updatePlanner(plannerId, payload);
      navigate(`/planner/${plannerId}`, { replace: true });
      return;
    }

    const created = await plannerService.createPlanner(payload);
    navigate(created?.id ? `/planner/${created.id}` : '/planner', { replace: true });
  });

  const handleSubmit = (event) => {
    event.preventDefault();
    savePlanner.submit().catch(() => {});
  };

  const body = (
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

      <section className="mobile-section">
        <h3 className="mobile-section__title">
          학습 시간표 · {formatMinutes(plannedMinutes(timeTable))}
        </h3>
        <p className="mobile-field__hint">10분 단위로 공부할 시간을 눌러 표시하세요.</p>
        <TimeTableGrid
          timeTable={timeTable}
          onToggle={(hour, slot) => setTimeTable((previous) => toggleSlot(previous, hour, slot))}
        />
      </section>

      <TextField
        as="textarea"
        label="상세 학습 목표"
        value={form.content}
        error={savePlanner.errorMessage}
        onChange={updateField('content')}
      />

      <Button type="submit" fullWidth isLoading={savePlanner.isSubmitting} disabled={!form.title.trim()}>
        {isEdit ? '플래너 수정' : '플래너 만들기'}
      </Button>
    </form>
  );

  return (
    <MobileScreen title={isEdit ? '플래너 수정' : '새 플래너'} showBackButton>
      {isEdit ? (
        <ScreenState query={existing} loadingLabel="플래너를 불러오는 중입니다">
          {body}
        </ScreenState>
      ) : (
        body
      )}
    </MobileScreen>
  );
}
