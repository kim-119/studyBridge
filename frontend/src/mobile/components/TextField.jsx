import React, { useId } from 'react';

export default function TextField({ label, hint, error, as = 'input', ...rest }) {
  const id = useId();
  const Element = as;

  return (
    <div className="mobile-field">
      <label className="mobile-field__label" htmlFor={id}>
        {label}
      </label>
      <Element
        id={id}
        className={error ? 'mobile-field__input mobile-field__input--error' : 'mobile-field__input'}
        aria-invalid={error ? 'true' : undefined}
        {...rest}
      />
      {error ? (
        <p className="mobile-field__error">{error}</p>
      ) : (
        hint && <p className="mobile-field__hint">{hint}</p>
      )}
    </div>
  );
}
