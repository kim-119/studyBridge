import React from 'react';
import { ChevronRight } from 'lucide-react';

export default function ListRow({ icon, title, subtitle, meta, onClick, trailing }) {
  const content = (
    <>
      {icon && <span className="mobile-row__icon">{icon}</span>}

      <span className="mobile-row__body">
        <span className="mobile-row__title">{title}</span>
        {subtitle && <span className="mobile-row__subtitle">{subtitle}</span>}
      </span>

      {meta && <span className="mobile-row__meta">{meta}</span>}
      {trailing || (onClick && <ChevronRight size={18} className="mobile-row__chevron" />)}
    </>
  );

  if (!onClick) return <div className="mobile-row">{content}</div>;

  return (
    <button type="button" className="mobile-row mobile-row--tappable" onClick={onClick}>
      {content}
    </button>
  );
}
