import React, { useEffect, useMemo, useState } from 'react';
import { createShare, getAnalytics } from '../api';
import { fill } from '../i18n';
import { copyText, downloadFile, haptic, openExternal, openTelegramLink, shareToStory } from '../telegram';
import { renderPost, renderStory } from '../story';
import { referralLink, tierFor, TIERS } from '../tiers';
import { fmt } from './Stats';
import { useToast } from './Toast';
import Icon from './Icon';
import friends from '../assets/icons/friends.webp';
import tgIcon from '../assets/icons/telegram.svg';
import waIcon from '../assets/icons/whatsapp.svg';
import xIcon from '../assets/icons/twitter.svg';
import fbIcon from '../assets/icons/facebook.svg';
import igIcon from '../assets/icons/instagram.svg';
import ttIcon from '../assets/icons/tiktok.svg';

const toB64 = (blob) =>
  new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onload = () => resolve(String(fr.result).split(',')[1]);
    fr.onerror = reject;
    fr.readAsDataURL(blob);
  });

const HASHTAGS = '#AWRobot #Forex #MT5 #Trading #TradingBot';

/** صفحة الإحالة: مستوى المستخدم، كوده، بطاقة قصة 9:16 بنقرة، ونصوص جاهزة للمشاركة. */
export default function Referral({ t, lang, data }) {
  const notify = useToast();
  const [refs, setRefs] = useState(null);
  const [media, setMedia] = useState(null); // { story, post, storyUrl, postUrl } صور محلية
  const [share, setShare] = useState(null); // روابط عامة من الخادم { story_url, post_url, page_url }
  const [view, setView] = useState('story');
  const [busy, setBusy] = useState(false);
  const [variant, setVariant] = useState(0);
  const link = referralLink(data);
  const code = data.referral_code || '';
  const r = data.report || {};
  const linked = refs?.linked ?? 0;
  const tier = tierFor(linked);

  useEffect(() => {
    getAnalytics().then((x) => setRefs(x.referrals)).catch(() => setRefs(null));
  }, []);
  useEffect(() => () => {
    if (media) {
      URL.revokeObjectURL(media.storyUrl);
      URL.revokeObjectURL(media.postUrl);
    }
  }, [media]);

  const growth = r.total_growth_pct;
  const captions = useMemo(() => {
    // الرابط في النص = صفحة المنشور (تُظهر الصورة والوصف كمعاينة) إن وُجدت، وإلا رابط الدعوة
    const vars = { code, link: share?.page_url || link || '', growth: growth == null ? '' : `${growth > 0 ? '+' : ''}${fmt(growth)}%` };
    return [t.capGrowth, t.capInvite, t.capShort].map((x) => `${fill(x, vars)}\n\n${HASHTAGS}`);
  }, [t, code, link, growth, share]);

  const storyData = () => ({
    dir: t.dir,
    nickname: data.nickname,
    avatar: data.avatar,
    bigValue: growth == null ? `${linked}` : `${growth > 0 ? '+' : ''}${fmt(growth)}%`,
    bigLabel: growth == null ? t.refShort : t.storyGrowth,
    stats: [
      { label: t.winRate, value: r.win_rate == null ? '—' : `${fmt(r.win_rate, 1)}%` },
      { label: t.closedTrades, value: `${r.trades ?? 0}` },
      { label: t.refShort, value: `${linked}` },
    ],
    tierImg: tier.cur.img,
    tierLabel: t[`tier_${tier.cur.key}`],
    code,
    link,
    codeLabel: t.storyCode,
  });

  // يولّد القصة (9:16) والمنشور (1:1) ويرفعهما لروابط عامة
  async function ensureShare() {
    if (media && share) return { media, share };
    const d = storyData();
    const [storyBlob, postBlob] = await Promise.all([renderStory(d), renderPost(d)]);
    const m = { story: storyBlob, post: postBlob, storyUrl: URL.createObjectURL(storyBlob), postUrl: URL.createObjectURL(postBlob) };
    setMedia(m);
    let sh = null;
    try {
      sh = await createShare(await toB64(storyBlob), await toB64(postBlob), captions[variant]);
      setShare(sh);
    } catch {
      /* بلا روابط عامة: تبقى المشاركة المباشرة للصورة متاحة */
    }
    return { media: m, share: sh };
  }

  async function run(fn) {
    setBusy(true);
    try {
      await fn(await ensureShare());
    } catch (e) {
      if (e?.name !== 'AbortError') notify(t.storyErr, 'error');
    } finally {
      setBusy(false);
    }
  }

  const fileOf = (blob, kind) => new File([blob], `AW-Robot-${code}-${kind}.jpg`, { type: 'image/jpeg' });

  // نافذة المشاركة الأصلية بالصورة + النص؛ وإلا تنزيل الصورة ونسخ النص
  async function nativeShare(m, sh, kind, text) {
    const file = fileOf(kind === 'story' ? m.story : m.post, kind);
    await copyText(text);
    if (navigator.canShare?.({ files: [file] })) {
      await navigator.share({ files: [file], text, title: 'AW Robot' });
      haptic.success();
      return;
    }
    const url = kind === 'story' ? sh?.story_url : sh?.post_url;
    if (!(url && downloadFile(url, file.name))) {
      const a = document.createElement('a');
      a.href = kind === 'story' ? m.storyUrl : m.postUrl;
      a.download = file.name;
      document.body.appendChild(a);
      a.click();
      a.remove();
    }
    notify(t.storySaved, 'success');
  }

  const caption = captions[variant];
  const enc = encodeURIComponent;
  const targets = [
    { key: 'tgStory', label: t.shTgStory, img: tgIcon, story: true, go: ({ media: m, share: sh }) =>
      (sh?.story_url && shareToStory(sh.story_url, caption, link ? { url: link, name: 'AW Robot' } : null)) || nativeShare(m, sh, 'story', caption) },
    { key: 'instagram', label: 'Instagram', img: igIcon, go: ({ media: m, share: sh }) => nativeShare(m, sh, 'story', caption) },
    { key: 'tiktok', label: 'TikTok', img: ttIcon, go: ({ media: m, share: sh }) => nativeShare(m, sh, 'story', caption) },
    { key: 'facebook', label: 'Facebook', img: fbIcon, go: async ({ share: sh }) => {
      await copyText(caption);
      openExternal(`https://www.facebook.com/sharer/sharer.php?u=${enc(sh?.page_url || link)}`);
      notify(t.shCaptionCopied, 'success');
    } },
    { key: 'x', label: 'X', img: xIcon, go: ({ share: sh }) =>
      openExternal(`https://twitter.com/intent/tweet?text=${enc(fill(t.capShort, { code, link: '' }).trim())}&url=${enc(sh?.page_url || link)}&hashtags=AWRobot,Forex,MT5`) },
    { key: 'whatsapp', label: 'WhatsApp', img: waIcon, go: () => openExternal(`https://wa.me/?text=${enc(caption)}`) },
    { key: 'telegram', label: t.shTgPost, img: tgIcon, go: ({ share: sh }) =>
      openTelegramLink(`https://t.me/share/url?url=${enc(sh?.page_url || link)}&text=${enc(caption.replace(sh?.page_url || link || '', '').trim())}`) },
    { key: 'more', label: t.shMore, icon: 'share', go: ({ media: m, share: sh }) => nativeShare(m, sh, 'post', caption) },
  ];

  async function copy(text, msg) {
    if (await copyText(text)) {
      haptic.success();
      notify(msg, 'success');
    }
  }

  return (
    <section className="dash referral">
      <div className="ref-hero">
        <img src={friends} alt="" />
        <div>
          <h1 className="page-title">{t.refTitle}</h1>
          <p className="sub">{fill(t.refSub, { n: data.settings?.referral_days ?? 7 })}</p>
        </div>
      </div>

      <div className="section tier-card">
        <img src={tier.cur.img} alt="" className="tier-badge" />
        <div className="motivate-body">
          <h2>{t[`tier_${tier.cur.key}`]}</h2>
          {tier.next && <div className="progress"><span style={{ width: `${tier.progress * 100}%` }} /></div>}
          <p className="sub">{tier.next ? fill(t.anNextLevel, { n: tier.left, tier: t[`tier_${tier.next.key}`] }) : t.anTopLevel}</p>
        </div>
      </div>
      <div className="tier-strip">
        {TIERS.map((x) => (
          <div key={x.key} className={`tier-step ${linked >= x.min ? 'on' : ''}`}>
            <img src={x.img} alt="" />
            <span>{t[`tier_${x.key}`]}</span>
            <bdi dir="ltr">{x.min}+</bdi>
          </div>
        ))}
      </div>

      <div className="kpis three">
        <div className="kpi"><span className="kpi-label">{t.refInvited}</span><strong className="kpi-value" dir="ltr">{refs?.invited ?? '—'}</strong></div>
        <div className="kpi"><span className="kpi-label">{t.refShort}</span><strong className="kpi-value" dir="ltr">{refs ? linked : '—'}</strong></div>
        <div className="kpi"><span className="kpi-label">{t.refConversion}</span><strong className="kpi-value" dir="ltr">{refs?.conversion_pct == null ? '—' : `${fmt(refs.conversion_pct, 1)}%`}</strong></div>
      </div>

      {code && (
        <div className="section">
          <h2>{t.yourCode}</h2>
          <div className="code-box">
            <strong dir="ltr">{code}</strong>
            <button type="button" className="btn soft small" onClick={() => copy(link || code, t.copied)}>
              <Icon name="copy" size={16} />
              <span>{t.refCopyLink}</span>
            </button>
          </div>
        </div>
      )}

      <div className="section">
        <h2>{t.storyTitle}</h2>
        <p className="sub">{t.storySub}</p>
        {media ? (
          <>
            <div className="seg center">
              <button type="button" className={view === 'story' ? 'on' : ''} onClick={() => setView('story')}>{t.shStoryTab}</button>
              <button type="button" className={view === 'post' ? 'on' : ''} onClick={() => setView('post')}>{t.shPostTab}</button>
            </div>
            <img className={`story-preview ${view === 'post' ? 'is-post' : ''}`} src={view === 'story' ? media.storyUrl : media.postUrl} alt={t.storyTitle} />
          </>
        ) : (
          <div className="actions stack">
            <button type="button" className="btn primary" disabled={busy || !code} onClick={() => run(() => {})}>
              <Icon name="share" size={18} />
              <span>{busy ? t.sending : t.storyPreview}</span>
            </button>
          </div>
        )}
        <div className="share-grid">
          {targets.map((x) => (
            <button key={x.key} type="button" className={`share-target ${x.story ? 'is-story' : ''}`} disabled={busy || !code} onClick={() => run(x.go)}>
              <span className="share-ic">{x.img ? <img src={x.img} alt="" /> : <Icon name={x.icon} size={22} />}</span>
              <small>{x.label}</small>
            </button>
          ))}
        </div>
        <p className="muted small-note">{t.shHint}</p>
      </div>

      <div className="section">
        <div className="section-head">
          <h2>{t.capTitle}</h2>
          <div className="seg">
            {captions.map((_, i) => (
              <button key={i} type="button" className={variant === i ? 'on' : ''} onClick={() => setVariant(i)}>{i + 1}</button>
            ))}
          </div>
        </div>
        <pre className="caption-box">{caption}</pre>
        <div className="actions inline">
          <button type="button" className="btn soft small" onClick={() => copy(caption, t.copied)}>
            <Icon name="copy" size={16} />
            <span>{t.capCopy}</span>
          </button>
        </div>
        <p className="muted small-note">{t.capNote}</p>
      </div>
    </section>
  );
}
