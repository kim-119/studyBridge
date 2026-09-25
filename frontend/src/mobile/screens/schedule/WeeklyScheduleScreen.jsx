import React, { useMemo, useState } from 'react';
import { CheckCircle2, Circle, Trash2 } from 'lucide-react';
import Button from '../../components/Button';
import ScreenState, { EmptyState } from '../../components/ScreenState';
import TextField from '../../components/TextField';
import MobileScreen from '../../shell/MobileScreen';
import { todoService } from '../../../services/api';
import { useAsync, useSubmit } from '../../data/useAsync';
import { useAuth } from '../../../hooks/useAuth';

function todoDate(todo) {
  const value = todo.scheduleDate || todo.endDate || todo.startDate || todo.createdAt;
  return value ? String(value).slice(0, 10) : '';
}

export default function WeeklyScheduleScreen() {
  const { userId } = useAuth();
  const todos = useAsync(() => todoService.getTodos(userId), [userId]);
  const [text, setText] = useState('');
  const [dueDate, setDueDate] = useState('');

  const grouped = useMemo(() => {
    const list = Array.isArray(todos.data) ? todos.data : [];
    const byDate = new Map();

    list.forEach((todo) => {
      const key = todoDate(todo) || '날짜 미지정';
      if (!byDate.has(key)) byDate.set(key, []);
      byDate.get(key).push(todo);
    });

    return [...byDate.entries()].sort(([left], [right]) => left.localeCompare(right));
  }, [todos.data]);

  const completedCount = (todos.data || []).filter((todo) => todo.completed).length;
  const totalCount = (todos.data || []).length;

  const addTodo = useSubmit(async () => {
    await todoService.createTodo(userId, {
      text: text.trim(),
      completed: false,
      endDate: dueDate ? `${dueDate}T23:59:59` : null,
    });
    setText('');
    setDueDate('');
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

  return (
    <MobileScreen title="주간일정" showBackButton>
      <section className="mobile-card mobile-section">
        <p className="mobile-card__meta">오늘 할 일</p>
        <p className="mobile-stat">
          {completedCount}/{totalCount}
        </p>
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

      <ScreenState query={todos} loadingLabel="일정을 불러오는 중입니다">
        {grouped.length === 0 ? (
          <EmptyState message="등록된 일정이 없습니다." />
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
