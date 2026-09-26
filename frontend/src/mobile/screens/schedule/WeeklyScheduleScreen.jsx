import React, { useMemo, useState } from 'react';
import { CheckCircle2, ChevronLeft, ChevronRight, Circle, Trash2 } from 'lucide-react';
import Button from '../../components/Button';
import ScreenState, { EmptyState } from '../../components/ScreenState';
import SubTabs from '../../components/SubTabs';
import TextField from '../../components/TextField';
import MobileScreen from '../../shell/MobileScreen';
import { todoService } from '../../../services/api';
import { useAuth } from '../../../hooks/useAuth';
import { useAsync, useSubmit } from '../../data/useAsync';

const VIEW_TABS = [
  { key: 'week', label: '주간' },
  { key: 'month', label: '월간' },
];

function toIsoDate(date) {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 10);
}

function todoDate(todo) {
  const value = todo.scheduleDate || todo.endDate || todo.startDate || todo.createdAt;
  return value ? String(value).slice(0, 10) : '';
}

function startOfWeek(date) {
  const start = new Date(date);
  start.setDate(start.getDate() - start.getDay());
  start.setHours(0, 0, 0, 0);
  return start;
}

function buildWeekRange(anchor) {
  const start = startOfWeek(anchor);
  return Array.from({ length: 7 }, (_, index) => {
    const day = new Date(start);
    day.setDate(start.getDate() + index);
    return toIsoDate(day);
  });
}

function buildMonthRange(anchor) {
  const year = anchor.getFullYear();
  const month = anchor.getMonth();
  const days = new Date(year, month + 1, 0).getDate();

  return Array.from({ length: days }, (_, index) => toIsoDate(new Date(year, month, index + 1)));
}

function formatPeriod(view, anchor) {
  if (view === 'month') {
    return `${anchor.getFullYear()}년 ${anchor.getMonth() + 1}월`;
  }

  const range = buildWeekRange(anchor);
  return `${range[0]} ~ ${range[6]}`;
}

export default function WeeklyScheduleScreen() {
  const { userId } = useAuth();
  const todos = useAsync(() => todoService.getTodos(userId), [userId]);
  const [view, setView] = useState(VIEW_TABS[0].key);
  const [anchor, setAnchor] = useState(() => new Date());
  const [text, setText] = useState('');
  const [dueDate, setDueDate] = useState(toIsoDate(new Date()));

  const visibleDates = useMemo(
    () => (view === 'month' ? buildMonthRange(anchor) : buildWeekRange(anchor)),
    [view, anchor]
  );

  const grouped = useMemo(() => {
    const list = Array.isArray(todos.data) ? todos.data : [];
    const allowed = new Set(visibleDates);
    const byDate = new Map();

    list.forEach((todo) => {
      const key = todoDate(todo);
      if (!allowed.has(key)) return;
      if (!byDate.has(key)) byDate.set(key, []);
      byDate.get(key).push(todo);
    });

    return [...byDate.entries()].sort(([left], [right]) => left.localeCompare(right));
  }, [todos.data, visibleDates]);

  const periodTodos = grouped.flatMap(([, items]) => items);
  const completedCount = periodTodos.filter((todo) => todo.completed).length;

  const shiftPeriod = (direction) => {
    setAnchor((previous) => {
      const next = new Date(previous);
      if (view === 'month') next.setMonth(next.getMonth() + direction);
      else next.setDate(next.getDate() + direction * 7);
      return next;
    });
  };

  const addTodo = useSubmit(async () => {
    await todoService.createTodo(userId, {
      text: text.trim(),
      completed: false,
      endDate: dueDate ? `${dueDate}T23:59:59` : null,
    });
    setText('');
    await todos.reload();
  });

  const toggleTodo = useSubmit(async (todoId) => {
    await todoService.toggleTodo(todoId);
    await todos.reload();
  });

  const removeTodo = useSubmit(async (todoId) => {
    await todoService.deleteTodo(todoId);
    await todos.reload();
  });

  const actionError = toggleTodo.errorMessage || removeTodo.errorMessage;

  return (
    <MobileScreen title="주간일정" showBackButton>
      <SubTabs tabs={VIEW_TABS} activeKey={view} onChange={setView} />

      <div className="mobile-period">
        <button type="button" aria-label="이전 기간" onClick={() => shiftPeriod(-1)}>
          <ChevronLeft size={18} />
        </button>
        <span>{formatPeriod(view, anchor)}</span>
        <button type="button" aria-label="다음 기간" onClick={() => shiftPeriod(1)}>
          <ChevronRight size={18} />
        </button>
      </div>

      <section className="mobile-card mobile-section">
        <div className="mobile-period__today">
          <div>
            <p className="mobile-card__meta">이 기간 할 일</p>
            <p className="mobile-stat">
              {completedCount}/{periodTodos.length}
            </p>
          </div>
          <Button variant="secondary" onClick={() => setAnchor(new Date())}>
            오늘
          </Button>
        </div>
      </section>

      <section className="mobile-card mobile-section">
        <TextField
          label="일정 추가"
          value={text}
          placeholder="예: 머신러닝 3장 복습"
          onChange={(event) => setText(event.target.value)}
        />
        <TextField
          label="종료 날짜"
          type="date"
          value={dueDate}
          error={addTodo.errorMessage}
          onChange={(event) => setDueDate(event.target.value)}
        />
        <Button
          fullWidth
          isLoading={addTodo.isSubmitting}
          disabled={!text.trim()}
          onClick={() => addTodo.submit().catch(() => {})}
        >
          일정 추가
        </Button>
      </section>

      {actionError && <p className="mobile-auth__error">{actionError}</p>}

      <ScreenState query={todos} loadingLabel="일정을 불러오는 중입니다">
        {grouped.length === 0 ? (
          <EmptyState message="이 기간에 등록된 일정이 없습니다." />
        ) : (
          grouped.map(([date, items]) => (
            <section key={date} className="mobile-section">
              <h3 className="mobile-section__title">{date}</h3>

              <ul className="mobile-list">
                {items.map((todo) => (
                  <li key={todo.id} className="mobile-todo">
                    <button
                      type="button"
                      className="mobile-todo__toggle"
                      aria-label={todo.completed ? '완료 취소' : '완료 처리'}
                      onClick={() => toggleTodo.submit(todo.id).catch(() => {})}
                    >
                      {todo.completed ? (
                        <CheckCircle2 size={20} className="mobile-roadmap__check is-done" />
                      ) : (
                        <Circle size={20} className="mobile-roadmap__check" />
                      )}
                      <span className={todo.completed ? 'is-completed' : ''}>{todo.text}</span>
                    </button>

                    <button
                      type="button"
                      className="mobile-todo__delete"
                      aria-label="일정 삭제"
                      onClick={() => removeTodo.submit(todo.id).catch(() => {})}
                    >
                      <Trash2 size={18} />
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          ))
        )}
      </ScreenState>
    </MobileScreen>
  );
}
