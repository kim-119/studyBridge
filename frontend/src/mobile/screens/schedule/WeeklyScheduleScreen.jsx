import React, { useMemo, useState } from 'react';
import Fab from '../../components/Fab';
import ScreenState, { EmptyState } from '../../components/ScreenState';
import MobileScreen from '../../shell/MobileScreen';
import { todoService } from '../../../services/api';
import { useAuth } from '../../../hooks/useAuth';
import { useAsync, useSubmit } from '../../data/useAsync';
import ScheduleCalendar from './ScheduleCalendar';
import TodoActionSheet from './TodoActionSheet';
import TodoCreateSheet from './TodoCreateSheet';
import TodoRow from './TodoRow';
import {
  countCompleted,
  toCalendarEvents,
  toLocalIsoDate,
  todosOnDate,
  todosOverlappingRange,
} from './scheduleEvents';
import './schedule.css';

function asTodoList(data) {
  return Array.isArray(data) ? data : [];
}

function isSameVisibleRange(previous, next) {
  return (
    previous?.type === next.type &&
    previous?.title === next.title &&
    previous?.firstDate === next.firstDate &&
    previous?.lastDate === next.lastDate
  );
}

function formatSelectedDate(isoDate) {
  const [, month, day] = isoDate.split('-').map(Number);
  return `${month}월 ${day}일`;
}

function PeriodSummary({ visibleRange, periodTodos }) {
  if (!visibleRange) return null;

  return (
    <section className="mobile-card mobile-section mobile-schedule-summary">
      <div>
        <p className="mobile-card__meta">이 기간 할 일</p>
        <p className="mobile-stat">{periodTodos.length}</p>
      </div>
      <div>
        <p className="mobile-card__meta">완료</p>
        <p className="mobile-stat">
          {countCompleted(periodTodos)}/{periodTodos.length}
        </p>
      </div>
    </section>
  );
}

export default function WeeklyScheduleScreen() {
  const { userId } = useAuth();
  const todos = useAsync(() => todoService.getTodos(userId), [userId]);
  const [selectedDate, setSelectedDate] = useState(() => toLocalIsoDate(new Date()));
  const [visibleRange, setVisibleRange] = useState(null);
  const [isCreateOpen, setCreateOpen] = useState(false);
  const [activeTodoId, setActiveTodoId] = useState(null);

  const todoList = asTodoList(todos.data);
  const events = useMemo(() => toCalendarEvents(todos.data), [todos.data]);
  const dayTodos = todosOnDate(todoList, selectedDate);
  const periodTodos = visibleRange
    ? todosOverlappingRange(todoList, visibleRange.firstDate, visibleRange.lastDate)
    : [];
  const activeTodo = todoList.find((todo) => String(todo.id) === String(activeTodoId)) || null;

  const createTodo = async (payload) => {
    await todoService.createTodo(userId, payload);
    setSelectedDate(payload.startDate.slice(0, 10));
    await todos.reload();
  };

  const updateVisibleRange = (nextRange) => {
    setVisibleRange((previous) => (isSameVisibleRange(previous, nextRange) ? previous : nextRange));
  };

  const toggleTodo = useSubmit(async (todoId) => {
    await todoService.toggleTodo(todoId);
    await todos.reload();
  });

  const removeTodo = useSubmit(async (todoId) => {
    await todoService.deleteTodo(todoId);
    setActiveTodoId(null);
    await todos.reload();
  });

  const isMutating = toggleTodo.isSubmitting || removeTodo.isSubmitting;
  const actionError = toggleTodo.errorMessage || removeTodo.errorMessage;

  const handleToggle = (todoId) => toggleTodo.submit(todoId).catch(() => {});
  const handleDelete = (todoId) => removeTodo.submit(todoId).catch(() => {});

  const closeActionSheet = () => {
    toggleTodo.clearError();
    removeTodo.clearError();
    setActiveTodoId(null);
  };

  return (
    <MobileScreen title="주간일정" showBackButton>
      <ScreenState query={todos} loadingLabel="일정을 불러오는 중입니다">
        <>
          <ScheduleCalendar
            events={events}
            selectedDate={selectedDate}
            visibleRange={visibleRange}
            onSelectDate={setSelectedDate}
            onSelectEvent={setActiveTodoId}
            onVisibleRangeChange={updateVisibleRange}
          />

          <PeriodSummary visibleRange={visibleRange} periodTodos={periodTodos} />

          <section className="mobile-section">
            <h3 className="mobile-section__title">
              {formatSelectedDate(selectedDate)} 할 일 · 완료 {countCompleted(dayTodos)}/{dayTodos.length}
            </h3>

            {!activeTodo && actionError && <p className="mobile-auth__error">{actionError}</p>}

            {dayTodos.length === 0 ? (
              <EmptyState message="이 날짜에 등록된 일정이 없습니다." />
            ) : (
              <ul className="mobile-list">
                {dayTodos.map((todo) => (
                  <TodoRow
                    key={todo.id}
                    todo={todo}
                    isBusy={isMutating}
                    onToggle={handleToggle}
                    onDelete={handleDelete}
                  />
                ))}
              </ul>
            )}
          </section>
        </>
      </ScreenState>

      <Fab label="일정 추가" onClick={() => setCreateOpen(true)} />

      <TodoCreateSheet
        isOpen={isCreateOpen}
        defaultDate={selectedDate}
        onClose={() => setCreateOpen(false)}
        onCreate={createTodo}
      />

      <TodoActionSheet
        todo={activeTodo}
        isBusy={isMutating}
        errorMessage={actionError}
        onClose={closeActionSheet}
        onToggle={handleToggle}
        onDelete={handleDelete}
      />
    </MobileScreen>
  );
}
