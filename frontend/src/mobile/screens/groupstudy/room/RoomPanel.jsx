import React from 'react';
import { X } from 'lucide-react';

export default function RoomPanel({ title, onClose, tabs, children }) {
  return (
    <section className="mobile-room-panel" role="dialog" aria-label={title}>
      <header className="mobile-room-panel__header">
        <h2 className="mobile-sheet__title">{title}</h2>
        <button type="button" className="mobile-sheet__close" aria-label="닫기" onClick={onClose}>
          <X size={20} />
        </button>
      </header>
      {tabs}
      <div className="mobile-room-panel__body">{children}</div>
    </section>
  );
}
