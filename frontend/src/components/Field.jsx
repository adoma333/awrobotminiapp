import React, { useId, useState } from 'react';

const EyeIcon = ({ off }) => (
  <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z" />
    <circle cx="12" cy="12" r="3" />
    {off && <path d="M4 4l16 16" />}
  </svg>
);

export default function Field({
  label,
  value,
  onChange,
  placeholder,
  hint,
  error,
  type = 'text',
  inputMode,
  maxLength,
  toggleLabels, // { show, hide } لحقل كلمة المرور
  autoFocus,
}) {
  const id = useId();
  const [visible, setVisible] = useState(false);
  const isPassword = type === 'password';

  return (
    <div className={`field ${error ? 'has-error' : ''}`}>
      <label htmlFor={id}>{label}</label>
      <div className={`control ${isPassword ? 'has-eye' : ''}`}>
        <input
          id={id}
          dir={isPassword ? 'ltr' : 'auto'}
          type={isPassword && visible ? 'text' : type}
          inputMode={inputMode}
          maxLength={maxLength}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          autoComplete="off"
          autoCapitalize="off"
          autoCorrect="off"
          spellCheck={false}
          autoFocus={autoFocus}
          aria-invalid={!!error}
          aria-describedby={error || hint ? `${id}-msg` : undefined}
        />
        {isPassword && (
          <button
            type="button"
            className="eye"
            onClick={() => setVisible((v) => !v)}
            aria-label={visible ? toggleLabels?.hide : toggleLabels?.show}
          >
            <EyeIcon off={visible} />
          </button>
        )}
      </div>
      {(error || hint) && (
        <p id={`${id}-msg`} className={error ? 'msg error' : 'msg'}>
          {error || hint}
        </p>
      )}
    </div>
  );
}
