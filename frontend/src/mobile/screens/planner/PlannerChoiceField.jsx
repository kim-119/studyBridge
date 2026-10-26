import React from 'react';

export default function PlannerChoiceField({ label, options, value, onChange }) {
  return (
    <div className="mobile-field">
      <span className="mobile-field__label">{label}</span>
      <div className="mobile-choice" role="radiogroup" aria-label={label}>
        {options.map((option) => {
          const isSelected = option === value;

          return (
            <button
              key={option}
              type="button"
              role="radio"
              aria-checked={isSelected}
              className={isSelected ? 'is-active' : ''}
              onClick={() => onChange(isSelected ? '' : option)}
            >
              {option}
            </button>
          );
        })}
      </div>
    </div>
  );
}
