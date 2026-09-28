import React, { useState } from 'react';
import Button from '../../components/Button';
import { useBackDismiss } from '../../platform/useBackDismiss';

export default function ConfirmAction({
  label,
  confirmMessage,
  confirmLabel = '확인',
  triggerVariant = 'ghost',
  isLoading = false,
  onConfirm,
}) {
  const [isAsking, setAsking] = useState(false);
  useBackDismiss(isAsking, () => setAsking(false));

  if (!isAsking) {
    return (
      <Button variant={triggerVariant} isLoading={isLoading} onClick={() => setAsking(true)}>
        {label}
      </Button>
    );
  }

  const confirm = () => {
    setAsking(false);
    onConfirm();
  };

  return (
    <div className="mobile-confirm">
      <p className="mobile-confirm__message">{confirmMessage}</p>
      <div className="mobile-card__actions">
        <Button variant="secondary" onClick={() => setAsking(false)}>
          취소
        </Button>
        <Button variant="danger" onClick={confirm}>
          {confirmLabel}
        </Button>
      </div>
    </div>
  );
}
