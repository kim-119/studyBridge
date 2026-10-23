import React from 'react';
import { CheckCircle2, Circle, Trash2 } from 'lucide-react';
import BottomSheet from '../../components/BottomSheet';
import Button from '../../components/Button';
import { displayTodoText, isPlannerTodo, isReviewTodo, todoPeriodLabel } from './scheduleEvents';

function sourceLabel(todo) {
  if (isReviewTodo(todo)) return '복습 일정';
  if (isPlannerTodo(todo)) return '플래너 일정';
  return '할 일';
}

export default function TodoActionSheet({ todo, onClose, onToggle, onDelete, isBusy, errorMessage }) {
  return (
    <BottomSheet title="일정" isOpen={Boolean(todo)} onClose={onClose}>
      {todo && (
        <>
          <p className="mobile-card__meta">
            {sourceLabel(todo)} · {todoPeriodLabel(todo)}
          </p>
          <p className="mobile-paragraph mobile-section">{displayTodoText(todo.text)}</p>

          {errorMessage && <p className="mobile-auth__error">{errorMessage}</p>}

          <div className="mobile-schedule-sheet__actions">
            <Button fullWidth isLoading={isBusy} onClick={() => onToggle(todo.id)}>
              {todo.completed ? <Circle size={16} /> : <CheckCircle2 size={16} />}
              {todo.completed ? '완료 취소' : '완료 처리'}
            </Button>
            <Button fullWidth variant="danger" disabled={isBusy} onClick={() => onDelete(todo.id)}>
              <Trash2 size={16} />
              삭제
            </Button>
          </div>
        </>
      )}
    </BottomSheet>
  );
}
