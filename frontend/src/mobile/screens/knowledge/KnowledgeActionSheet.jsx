import React, { useState } from 'react';
import BottomSheet from '../../components/BottomSheet';
import Button from '../../components/Button';
import TextField from '../../components/TextField';
import { useSubmit } from '../../data/useAsync';
import { REPORT_REASONS } from './knowledgeModel';

const TARGET_LABEL = { post: '게시글', comment: '댓글' };

function sheetTitleOf(target) {
  if (!target) return '';
  return `${TARGET_LABEL[target.kind]} ${target.isMine ? '삭제' : '신고'}`;
}

function DeleteConfirmation({ target, onCancel, onDelete }) {
  const removal = useSubmit(() => onDelete(target));

  return (
    <>
      <p className="mobile-paragraph">이 {TARGET_LABEL[target.kind]}을 삭제할까요? 되돌릴 수 없습니다.</p>
      {removal.errorMessage && <p className="mobile-auth__error">{removal.errorMessage}</p>}
      <div className="mobile-card__actions">
        <Button variant="secondary" onClick={onCancel}>
          취소
        </Button>
        <Button variant="danger" isLoading={removal.isSubmitting} onClick={() => removal.submit().catch(() => {})}>
          삭제
        </Button>
      </div>
    </>
  );
}

function ReasonChoices({ value, onChange }) {
  return (
    <div className="mobile-field">
      <span className="mobile-field__label">신고 사유</span>
      <div className="mobile-choice" role="radiogroup" aria-label="신고 사유">
        {REPORT_REASONS.map((reason) => (
          <button
            key={reason.value}
            type="button"
            role="radio"
            aria-checked={reason.value === value}
            className={reason.value === value ? 'is-active' : ''}
            onClick={() => onChange(reason.value)}
          >
            {reason.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function ReportForm({ target, onReport }) {
  const [reason, setReason] = useState('');
  const [details, setDetails] = useState('');
  const duplicateMessage = `이미 신고한 ${TARGET_LABEL[target.kind]}입니다.`;
  const report = useSubmit(() => onReport(target, { reason, details: details.trim() }), {
    errorMessages: { 409: duplicateMessage },
  });

  return (
    <>
      <ReasonChoices value={reason} onChange={setReason} />
      <TextField
        as="textarea"
        label="상세 내용 (선택)"
        value={details}
        maxLength={500}
        placeholder="신고 사유를 자세히 적어주세요"
        error={report.errorMessage}
        onChange={(event) => setDetails(event.target.value)}
      />
      <Button
        variant="danger"
        fullWidth
        disabled={!reason}
        isLoading={report.isSubmitting}
        onClick={() => report.submit().catch(() => {})}
      >
        신고하기
      </Button>
    </>
  );
}

export default function KnowledgeActionSheet({ target, onClose, onDelete, onReport }) {
  const targetKey = target ? `${target.kind}-${target.id}` : 'none';

  return (
    <BottomSheet title={sheetTitleOf(target)} isOpen={Boolean(target)} onClose={onClose}>
      {target?.isMine && (
        <DeleteConfirmation key={targetKey} target={target} onCancel={onClose} onDelete={onDelete} />
      )}
      {target && !target.isMine && <ReportForm key={targetKey} target={target} onReport={onReport} />}
    </BottomSheet>
  );
}
