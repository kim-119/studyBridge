import React, { useEffect, useState } from 'react';
import BottomSheet from '../../components/BottomSheet';
import Button from '../../components/Button';
import TextField from '../../components/TextField';
import { useSubmit } from '../../data/useAsync';
import { buildCreateTodoPayload, validateTodoDraft } from './scheduleEvents';

function emptyDraft(defaultDate) {
  return { text: '', startDate: defaultDate, endDate: defaultDate };
}

export default function TodoCreateSheet({ isOpen, defaultDate, onClose, onCreate }) {
  const [draft, setDraft] = useState(() => emptyDraft(defaultDate));
  const [validationMessage, setValidationMessage] = useState(null);

  useEffect(() => {
    if (!isOpen) return;
    setDraft(emptyDraft(defaultDate));
    setValidationMessage(null);
  }, [isOpen, defaultDate]);

  const createTodo = useSubmit(async () => {
    await onCreate(buildCreateTodoPayload(draft));
    onClose();
  });

  const updateDraft = (field) => (event) => {
    const value = event.target.value;
    setDraft((previous) => ({ ...previous, [field]: value }));
  };

  const handleSubmit = () => {
    const message = validateTodoDraft(draft);
    setValidationMessage(message);
    if (message) return;
    createTodo.submit().catch(() => {});
  };

  return (
    <BottomSheet title="일정 추가" isOpen={isOpen} onClose={onClose}>
      <TextField
        label="할 일"
        value={draft.text}
        placeholder="예: 머신러닝 3장 복습"
        onChange={updateDraft('text')}
      />
      <div className="mobile-schedule-dates">
        <TextField
          label="시작 날짜"
          type="date"
          value={draft.startDate}
          onChange={updateDraft('startDate')}
        />
        <TextField
          label="종료 날짜"
          type="date"
          value={draft.endDate}
          min={draft.startDate}
          onChange={updateDraft('endDate')}
        />
      </div>

      {(validationMessage || createTodo.errorMessage) && (
        <p className="mobile-auth__error">{validationMessage || createTodo.errorMessage}</p>
      )}

      <Button fullWidth isLoading={createTodo.isSubmitting} onClick={handleSubmit}>
        추가
      </Button>
    </BottomSheet>
  );
}
