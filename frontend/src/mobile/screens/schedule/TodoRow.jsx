import React from 'react';
import { CheckCircle2, Circle, Trash2 } from 'lucide-react';
import { displayTodoText, isPlannerTodo, isReviewTodo, todoPeriodLabel } from './scheduleEvents';

function TodoSourceBadges({ todo }) {
  return (
    <>
      {isReviewTodo(todo) && <span className="mobile-todo-badge mobile-todo-badge--review">복습</span>}
      {isPlannerTodo(todo) && <span className="mobile-todo-badge mobile-todo-badge--planner">플래너</span>}
    </>
  );
}

export default function TodoRow({ todo, onToggle, onDelete, isBusy }) {
  return (
    <li className="mobile-todo">
      <button
        type="button"
        className="mobile-todo__toggle"
        aria-label={todo.completed ? '완료 취소' : '완료 처리'}
        disabled={isBusy}
        onClick={() => onToggle(todo.id)}
      >
        {todo.completed ? (
          <CheckCircle2 size={20} className="mobile-roadmap__check is-done" />
        ) : (
          <Circle size={20} className="mobile-roadmap__check" />
        )}
        <span className="mobile-todo__body">
          <span className={todo.completed ? 'mobile-todo__text is-completed' : 'mobile-todo__text'}>
            <TodoSourceBadges todo={todo} />
            {displayTodoText(todo.text)}
          </span>
          <span className="mobile-todo__period">{todoPeriodLabel(todo)}</span>
        </span>
      </button>

      <button
        type="button"
        className="mobile-todo__delete"
        aria-label="일정 삭제"
        disabled={isBusy}
        onClick={() => onDelete(todo.id)}
      >
        <Trash2 size={18} />
      </button>
    </li>
  );
}
