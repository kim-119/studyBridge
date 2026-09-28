import React, { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import Button from '../../components/Button';
import ScreenState from '../../components/ScreenState';
import TextField from '../../components/TextField';
import MobileScreen from '../../shell/MobileScreen';
import { plannerService } from '../../../services/api';
import { useAsync, useSubmit } from '../../data/useAsync';
import PlannerChoiceField from './PlannerChoiceField';
import TimeTableGrid from './TimeTableGrid';
import {
  DAY_OF_WEEK_OPTIONS,
  PLANNER_TYPE,
  PRIORITY_OPTIONS,
  STUDY_TYPE_OPTIONS,
  countCheckedSlots,
  createBlankPlannerForm,
  dayOfWeekOf,
  parseTimeTable,
  resolvePlannerType,
  toPlannerForm,
  toPlannerRequest,
  toggleSlot,
} from './plannerAdapter';

export default function PlannerFormScreen({ mode }) {
  const { plannerId } = useParams();
  const navigate = useNavigate();
  const isEdit = mode === 'edit';

  const [form, setForm] = useState(createBlankPlannerForm);
  const [timeTable, setTimeTable] = useState({});

  const existing = useAsync(
    async () => (isEdit ? plannerService.getPlanner(plannerId) : null),
    [plannerId, isEdit],
    { immediate: isEdit }
  );

  useEffect(() => {
    if (!existing.data) return;
    setForm(toPlannerForm(existing.data));
    setTimeTable(parseTimeTable(existing.data.timeTableJson));
  }, [existing.data]);

  const setField = (field, value) => setForm((previous) => ({ ...previous, [field]: value }));
  const updateField = (field) => (event) => setField(field, event.target.value);

  const updatePlannerDate = (event) => {
    const plannerDate = event.target.value;
    setForm((previous) => ({
      ...previous,
      plannerDate,
      dayOfWeek: dayOfWeekOf(plannerDate) || previous.dayOfWeek,
    }));
  };

  const savePlanner = useSubmit(async () => {
    const plannerType = isEdit ? resolvePlannerType(existing.data) : PLANNER_TYPE.USER;
    const payload = toPlannerRequest(form, timeTable, plannerType);

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
      <TextField label="플래너 제목" value={form.title} onChange={updateField('title')} />

      <div className="mobile-planner-form__row">
        <TextField label="날짜" type="date" value={form.plannerDate} onChange={updatePlannerDate} />

        <div className="mobile-field">
          <label className="mobile-field__label" htmlFor="planner-day-of-week">
            요일
          </label>
          <select
            id="planner-day-of-week"
            className="mobile-field__input"
            value={form.dayOfWeek}
            onChange={updateField('dayOfWeek')}
          >
            <option value="">-</option>
            {DAY_OF_WEEK_OPTIONS.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </div>
      </div>

      <TextField
        label="학기 / 주차"
        placeholder="예: 2026-1학기 · 3주차"
        value={form.term}
        onChange={updateField('term')}
      />
      <TextField
        label="과목명"
        placeholder="예: 모바일 앱 개발"
        value={form.subject}
        onChange={updateField('subject')}
      />

      <PlannerChoiceField
        label="학습 유형"
        options={STUDY_TYPE_OPTIONS}
        value={form.studyType}
        onChange={(value) => setField('studyType', value)}
      />
      <PlannerChoiceField
        label="우선순위"
        options={PRIORITY_OPTIONS}
        value={form.priority}
        onChange={(value) => setField('priority', value)}
      />

      <TextField
        label="목표 학습 시간"
        placeholder="예: 2시간"
        value={form.goalTime}
        onChange={updateField('goalTime')}
      />
      <TextField
        label="실제 학습 시간"
        placeholder="예: 1시간 30분"
        value={form.netStudyTime}
        onChange={updateField('netStudyTime')}
      />
      <TextField
        label="마감일 / 시험일"
        placeholder="예: 2026-06-20"
        value={form.dDay}
        onChange={updateField('dDay')}
      />

      <TextField
        as="textarea"
        label="학습 목표"
        placeholder="예: Retrofit2 개념 정리 및 실습 코드 완성"
        value={form.content}
        onChange={updateField('content')}
      />
      <TextField
        as="textarea"
        label="세부 할 일"
        placeholder="예: 강의자료 1~5p 복습, 실습 코드 실행, 오류 메모"
        value={form.tmi}
        onChange={updateField('tmi')}
      />

      <TextField
        label="기상 시간 (선택)"
        placeholder="예: 07:00"
        value={form.wakeUpTime}
        onChange={updateField('wakeUpTime')}
      />

      <section className="mobile-section">
        <h3 className="mobile-section__title">
          시간 체크표 (10분 단위) · 체크 {countCheckedSlots(timeTable)}칸
        </h3>
        <TimeTableGrid
          timeTable={timeTable}
          onToggle={(hour, slot) => setTimeTable((previous) => toggleSlot(previous, hour, slot))}
        />
      </section>

      {savePlanner.errorMessage && <p className="mobile-auth__error">{savePlanner.errorMessage}</p>}

      <Button type="submit" fullWidth isLoading={savePlanner.isSubmitting} disabled={!form.title.trim()}>
        {isEdit ? '플래너 수정' : '플래너 저장'}
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
