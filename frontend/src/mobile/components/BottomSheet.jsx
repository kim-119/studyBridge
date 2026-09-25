import React, { useEffect } from 'react';
import { X } from 'lucide-react';

export default function BottomSheet({ title, isOpen, onClose, children }) {
  useEffect(() => {
    if (!isOpen) return undefined;

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <div className="mobile-sheet" role="dialog" aria-modal="true" aria-label={title}>
      <button type="button" className="mobile-sheet__scrim" aria-label="닫기" onClick={onClose} />

      <div className="mobile-sheet__panel">
        <div className="mobile-sheet__header">
          <h2 className="mobile-sheet__title">{title}</h2>
          <button type="button" className="mobile-sheet__close" aria-label="닫기" onClick={onClose}>
            <X size={20} />
          </button>
        </div>

        <div className="mobile-sheet__body">{children}</div>
      </div>
    </div>
  );
}
