import React, { useMemo } from 'react';
import { Archive, BookMarked, CalendarDays, Sparkles, Upload } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { ErrorState } from '../components/ScreenState';
import MobileScreen from '../shell/MobileScreen';
import { studyTimeService, todoService } from '../../services/api';
import { useAuth } from '../../hooks/useAuth';
import { useAsync } from '../data/useAsync';

const FLOW_STEPS = ['자료', 'AI 분석', '계획', '학습'];

const SHORTCUTS = [
  { label: '자료 업로드', path: '/archive', icon: <Upload size={22} /> },
  { label: 'AI 학습', path: '/studymate', icon: <Sparkles size={22} /> },
  { label: '플래너', path: '/planner', icon: <CalendarDays size={22} /> },
  { label: '오답노트', path: '/review-notes', icon: <BookMarked size={22} /> },
];

function formatMinutes(minutes) {
  if (!minutes || minutes < 0) return '0m';
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return hours > 0 ? `${hours}h ${rest}m` : `${rest}m`;
}

// TimerDTO.WeeklyStudyTimeResponse 계약: { totalSeconds, averageSeconds, attendanceDays, dailyStats }
function weeklyMinutes(weekly) {
  if (typeof weekly?.totalSeconds === 'number') return Math.round(weekly.totalSeconds / 60);

  return (weekly?.dailyStats || []).reduce(
    (total, day) => total + Math.round((day.seconds ?? day.studySeconds ?? 0) / 60),
    0
  );
}

export default function HomeScreen() {
  const navigate = useNavigate();
  const { user, userId } = useAuth();

  const weekly = useAsync(() => studyTimeService.getWeekly(userId), [userId]);
  const todos = useAsync(() => todoService.getTodos(userId), [userId]);

  const todaySchedule = useMemo(() => {
    const today = new Date().toISOString().slice(0, 10);
    const list = Array.isArray(todos.data) ? todos.data : [];

    return list.filter((todo) => {
      const date = String(todo.scheduleDate || todo.endDate || todo.startDate || '').slice(0, 10);
      return date === today;
    });
  }, [todos.data]);

  const totalMinutes = weeklyMinutes(weekly.data);

  return (
    <MobileScreen title="홈">
      <section className="mobile-section">
        <h2 className="mobile-greeting">안녕하세요, {user?.displayName || '학습자'}님.</h2>
        <p className="mobile-greeting__sub">오늘도 학습을 이어가세요.</p>
      </section>

      <section className="mobile-card mobile-section">
        <p className="mobile-card__meta">StudyBridge 학습 플로우</p>
        <ol className="mobile-flow">
          {FLOW_STEPS.map((step) => (
            <li key={step}>{step}</li>
          ))}
        </ol>
      </section>

      <section className="mobile-section">
        <ul className="mobile-shortcuts">
          {SHORTCUTS.map(({ label, path, icon }) => (
            <li key={path}>
              <button type="button" onClick={() => navigate(path)}>
                <span className="mobile-shortcuts__icon">{icon}</span>
                {label}
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section className="mobile-card mobile-section">
        <p className="mobile-card__meta">오늘의 일정</p>

        {todos.isError ? (
          <ErrorState message={todos.errorMessage} onRetry={todos.reload} />
        ) : todaySchedule.length === 0 ? (
          <p className="mobile-card__meta">오늘 등록된 일정이 없습니다.</p>
        ) : (
          <ul className="mobile-bullets">
            {todaySchedule.map((todo) => (
              <li key={todo.id}>{todo.text}</li>
            ))}
          </ul>
        )}
      </section>

      <section className="mobile-card mobile-section">
        <p className="mobile-card__meta">이번 주 학습</p>

        {weekly.isError ? (
          <ErrorState message={weekly.errorMessage} onRetry={weekly.reload} />
        ) : (
          <p className="mobile-stat">{formatMinutes(totalMinutes)}</p>
        )}
      </section>

      <button type="button" className="mobile-row mobile-row--tappable" onClick={() => navigate('/archive')}>
        <span className="mobile-row__icon">
          <Archive size={20} />
        </span>
        <span className="mobile-row__body">
          <span className="mobile-row__title">자료보관함 열기</span>
          <span className="mobile-row__subtitle">학습자료와 AI 분석 결과를 확인하세요</span>
        </span>
      </button>
    </MobileScreen>
  );
}
