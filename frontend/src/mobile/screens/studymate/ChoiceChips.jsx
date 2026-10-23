import React from 'react';

export default function ChoiceChips({ label, options, value, onChange }) {
  return (
    <div className="mobile-field">
      <span className="mobile-field__label">{label}</span>
      <div className="mobile-choice-chips" role="radiogroup" aria-label={label}>
        {options.map((option) => (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={option.value === value}
            className={option.value === value ? 'mobile-choice-chip is-active' : 'mobile-choice-chip'}
            onClick={() => onChange(option.value)}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}
