import React from 'react';
import Field from './Field';
import Avatar from './Avatar';
import { haptic } from '../telegram';
import { NICKNAME_MAX, NICKNAME_MIN } from '../i18n';

export default function ProfileStep({ t, profile, setProfile, onNext, onBack }) {
  const valid = profile.nickname.trim().length >= NICKNAME_MIN;

  return (
    <section className="step">
      <h1>{t.profileTitle}</h1>

      <Field
        label={t.nickname}
        placeholder={t.nicknamePh}
        hint={t.nicknameHint}
        value={profile.nickname}
        maxLength={NICKNAME_MAX}
        onChange={(v) => setProfile({ ...profile, nickname: v })}
        autoFocus
      />

      <div className="field">
        <span className="label" id="avatar-label">{t.avatar}</span>
        <div className="avatars" role="radiogroup" aria-labelledby="avatar-label">
          {['boy', 'girl'].map((kind) => (
            <button
              key={kind}
              type="button"
              role="radio"
              aria-checked={profile.avatar === kind}
              className={`avatar-tile ${profile.avatar === kind ? 'is-selected' : ''}`}
              onClick={() => {
                haptic.select();
                setProfile({ ...profile, avatar: kind });
              }}
            >
              <Avatar kind={kind} size={64} />
              <span>{t[kind]}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="actions">
        <button type="button" className="btn ghost" onClick={onBack}>
          <svg className="chev" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M15 6l-6 6 6 6" /></svg>
          <span>{t.back}</span>
        </button>
        <button type="button" className="btn primary" disabled={!valid} onClick={onNext}>
          <span>{t.next}</span>
        </button>
      </div>
    </section>
  );
}
