import React, { useEffect } from 'react';
import { ChevronRight, FileText, FileUp, HelpCircle, Route } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { ErrorState, LoadingState } from '../components/ScreenState';
import MobileScreen from '../shell/MobileScreen';
import { todoService } from '../../services/api';
import { useAuth } from '../../hooks/useAuth';
import { useAsync } from '../data/useAsync';
import { registerAppStateChange } from '../platform/nativeShell';
import { currentWeekBounds, formatDuration } from './report/reportStats';
import { buildReport, loadWeeklyReport } from './report/weeklyReport';
import {
  countCompleted,
  displayTodoText,
  toLocalIsoDate,
  todoPeriodLabel,
  todosOnDate,
  todosOverlappingRange,
} from './schedule/scheduleEvents';

const LEARNING_FLOW = [
  { label: '자료', description: '학습자료 업로드', path: '/archive', Icon: FileUp },
  { label: '요약', description: '자료별 AI 핵심 요약', path: '/archive', Icon: FileText },
  { label: '계획', description: '로드맵 · 플래너', path: '/planner', Icon: Route },
  { label: '복습', description: '퀴즈 오답노트', path: '/review-notes', Icon: HelpCircle },
];

function TodayScheduleBody({ todos, todayIsoDate }) {
  if (todos.isLoading && todos.data == null) return <LoadingState label="오늘 일정을 불러오는 중입니다" />;
  if (todos.isError) return <ErrorState message={todos.errorMessage} onRetry={todos.reload} />;

  const todaysTodos = todosOnDate(todos.data, todayIsoDate);
  if (todaysTodos.length === 0) return <p className="mobile-card__meta">오늘 등록된 일정이 없습니다.</p>;

  return (
    <ul className="mobile-home-schedule">
      {todaysTodos.map((todo) => (
        <li key={todo.id} className={todo.completed ? 'is-completed' : undefined}>
          <span className="mobile-home-schedule__title">{displayTodoText(todo.text)}</span>
          <span className="mobile-home-schedule__meta">
            {todo.completed ? '완료' : '진행 중'} · {todoPeriodLabel(todo)}
          </span>
        </li>
      ))}
    </ul>
  );
}

function WeeklyStudyBody({ weeklyReport, todos, todayIsoDate }) {
  if (weeklyReport.isLoading && weeklyReport.data == null) {
    return <LoadingState label="이번 주 학습을 불러오는 중입니다" />;
  }
  if (weeklyReport.isError) return <ErrorState message={weeklyReport.errorMessage} onRetry={weeklyReport.reload} />;

  const report = buildReport(weeklyReport.data);
  const { firstDate, lastDate } = currentWeekIsoRange(todayIsoDate);
  const weekTodos = Array.isArray(todos.data) ? todosOverlappingRange(todos.data, firstDate, lastDate) : null;

  return (
    <dl className="mobile-home-metrics">
      <div>
        <dt>총 학습시간</dt>
        <dd>{formatDuration(report.summary.totalSeconds)}</dd>
      </div>
      <div>
        <dt>학습일수</dt>
        <dd>{report.attendanceDays == null ? '-' : `${report.attendanceDays}일`}</dd>
      </div>
      <div>
        <dt>완료한 일정</dt>
        <dd>{weekTodos ? `${countCompleted(weekTodos)}/${weekTodos.length}` : '-'}</dd>
      </div>
    </dl>
  );
}

function currentWeekIsoRange(todayIsoDate) {
  const today = new Date(`${todayIsoDate}T00:00:00`);
  const { start, end } = currentWeekBounds(today);
  return { firstDate: toLocalIsoDate(start), lastDate: toLocalIsoDate(end) };
}

export default function HomeScreen() {
  const navigate = useNavigate();
  const { user, userId } = useAuth();
  const todayIsoDate = toLocalIsoDate(new Date());

  const weeklyReport = useAsync(() => loadWeeklyReport(userId), [userId]);
  const todos = useAsync(() => todoService.getTodos(userId), [userId]);
  const reloadWeeklyReport = weeklyReport.reload;
  const reloadTodos = todos.reload;

  useEffect(() => {
    return registerAppStateChange(({ isActive }) => {
      if (!isActive) return;
      reloadWeeklyReport().catch(() => {});
      reloadTodos().catch(() => {});
    });
  }, [reloadWeeklyReport, reloadTodos]);

  return (
    <MobileScreen>
      <section className="mobile-section">
        <h2 className="mobile-greeting">안녕하세요, {user?.displayName || '학습자'}님.</h2>
        <p className="mobile-greeting__sub">오늘도 학습을 이어가세요.</p>
      </section>

      <section className="mobile-card mobile-section">
        <p className="mobile-card__meta">StudyBridge 학습 플로우</p>
        <ol className="mobile-flow">
          {LEARNING_FLOW.map(({ label, description, path, Icon }) => (
            <li key={label}>
              <button
                type="button"
                className="mobile-flow__step"
                aria-label={`${label}: ${description}`}
                onClick={() => navigate(path)}
              >
                <span className="mobile-flow__icon">
                  <Icon size={18} />
                </span>
                <span className="mobile-flow__label">{label}</span>
              </button>
            </li>
          ))}
        </ol>
      </section>

      <section className="mobile-card mobile-section" aria-label="오늘의 일정">
        <button type="button" className="mobile-card__header-link" onClick={() => navigate('/weekly-schedule')}>
          <span className="mobile-card__meta">오늘의 일정</span>
          <ChevronRight size={16} />
        </button>
        <TodayScheduleBody todos={todos} todayIsoDate={todayIsoDate} />
      </section>

      <section className="mobile-card mobile-section" aria-label="이번 주 학습">
        <button type="button" className="mobile-card__header-link" onClick={() => navigate('/study-report')}>
          <span className="mobile-card__meta">이번 주 학습</span>
          <ChevronRight size={16} />
        </button>
        <WeeklyStudyBody weeklyReport={weeklyReport} todos={todos} todayIsoDate={todayIsoDate} />
      </section>
    </MobileScreen>
  );
}
