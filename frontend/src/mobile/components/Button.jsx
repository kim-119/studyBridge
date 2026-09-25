import React from 'react';

const VARIANT_CLASS = {
  primary: 'mobile-button mobile-button--primary',
  secondary: 'mobile-button mobile-button--secondary',
  ghost: 'mobile-button mobile-button--ghost',
  danger: 'mobile-button mobile-button--danger',
};

export default function Button({
  variant = 'primary',
  type = 'button',
  isLoading = false,
  disabled = false,
  fullWidth = false,
  children,
  ...rest
}) {
  const className = [VARIANT_CLASS[variant], fullWidth ? 'mobile-button--block' : '']
    .filter(Boolean)
    .join(' ');

  return (
    <button type={type} className={className} disabled={disabled || isLoading} {...rest}>
      {isLoading ? <span className="mobile-button__spinner" /> : children}
    </button>
  );
}
