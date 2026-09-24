import React, { useRef, useState } from 'react';
import { updatePhoto, updateProfile } from '../api';
import { haptic } from '../telegram';
import { useToast } from './Toast';
import Avatar from './Avatar';

// يقصّ الصورة مربّعًا من المنتصف ويصغّرها إلى 320px (JPEG) قبل الرفع
function toSquareJpeg(file) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const s = Math.min(img.width, img.height);
      const c = document.createElement('canvas');
      c.width = 320;
      c.height = 320;
      c.getContext('2d').drawImage(img, (img.width - s) / 2, (img.height - s) / 2, s, s, 0, 0, 320, 320);
      URL.revokeObjectURL(img.src);
      resolve(c.toDataURL('image/jpeg', 0.86).split(',')[1]);
    };
    img.onerror = reject;
    img.src = URL.createObjectURL(file);
  });
}

/** تعديل الملف الشخصي: الصورة الشخصية (رفع/حذف)، الاسم المستعار، والنوع. */
export default function ProfileEditor({ t, data, onSaved }) {
  const notify = useToast();
  const fileRef = useRef(null);
  const [nickname, setNickname] = useState(data.nickname || '');
  const [avatar, setAvatar] = useState(data.avatar || 'boy');
  const [photo, setPhoto] = useState(data.photo_url || null);
  const [busy, setBusy] = useState('');
  const dirty = nickname.trim() !== (data.nickname || '') || avatar !== (data.avatar || 'boy');
  const valid = nickname.trim().length >= 2 && nickname.trim().length <= 24;

  async function pick(e) {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    setBusy('photo');
    try {
      const r = await updatePhoto(await toSquareJpeg(file));
      setPhoto(r.photo_url);
      haptic.success();
      notify(t.profileSaved, 'success');
      onSaved?.();
    } catch {
      haptic.error();
      notify(t.profileErr, 'error');
    } finally {
      setBusy('');
    }
  }

  async function removePhoto() {
    setBusy('photo');
    try {
      await updatePhoto('');
      setPhoto(null);
      onSaved?.();
    } catch {
      notify(t.profileErr, 'error');
    } finally {
      setBusy('');
    }
  }

  async function save() {
    setBusy('save');
    try {
      await updateProfile({ nickname: nickname.trim(), avatar });
      haptic.success();
      notify(t.profileSaved, 'success');
      onSaved?.();
    } catch {
      haptic.error();
      notify(t.profileErr, 'error');
    } finally {
      setBusy('');
    }
  }

  return (
    <div className="section profile-edit">
      <h2>{t.profileTitle}</h2>
      <div className="pe-photo">
        <button type="button" className="pe-avatar" onClick={() => fileRef.current?.click()} disabled={!!busy} aria-label={t.profileChangePhoto}>
          <Avatar kind={avatar} src={photo} size={84} />
          <span className="pe-badge">{busy === 'photo' ? '…' : '✎'}</span>
        </button>
        <div className="pe-actions">
          <button type="button" className="btn soft small" disabled={!!busy} onClick={() => fileRef.current?.click()}>
            <span>{t.profileChangePhoto}</span>
          </button>
          {photo && (
            <button type="button" className="link" disabled={!!busy} onClick={removePhoto}>{t.profileRemovePhoto}</button>
          )}
        </div>
        <input ref={fileRef} type="file" accept="image/*" hidden onChange={pick} />
      </div>

      <label className="pe-field">
        <span className="row-label">{t.nickname}</span>
        <input value={nickname} maxLength={24} onChange={(e) => setNickname(e.target.value)} />
      </label>
      <div className="pe-gender" role="radiogroup" aria-label={t.profileGender}>
        {['boy', 'girl'].map((k) => (
          <button key={k} type="button" role="radio" aria-checked={avatar === k} className={avatar === k ? 'on' : ''} onClick={() => setAvatar(k)}>
            <Avatar kind={k} size={34} />
            <span>{k === 'boy' ? t.boy : t.girl}</span>
          </button>
        ))}
      </div>
      <div className="actions inline">
        <button type="button" className="btn primary" disabled={!dirty || !valid || !!busy} onClick={save}>
          <span>{busy === 'save' ? t.sending : t.profileSave}</span>
        </button>
      </div>
    </div>
  );
}
