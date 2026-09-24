import React, { useEffect, useMemo, useState } from 'react';
import { getAnalytics } from '../api';
import { fill } from '../i18n';
import { copyText, haptic, openExternal, openTelegramLink } from '../telegram';
import { renderStory } from '../story';
import { referralLink, tierFor, TIERS } from '../tiers';
import { fmt } from './Stats';
import { useToast } from './Toast';
import Icon from './Icon';
import friends from '../assets/icons/friends.webp';
import tgIcon from '../assets/icons/telegram.svg';
import waIcon from '../assets/icons/whatsapp.svg';
import xIcon from '../assets/icons/twitter.svg';
import fbIcon from '../assets/icons/facebook.svg';

const HASHTAGS = '#AWRobot #Forex #MT5 #Trading #TradingBot';

/** صفحة الإحالة: مستوى المستخدم، كوده، بطاقة قصة 9:16 بنقرة، ونصوص جاهزة للمشاركة. */
export default function Referral({ t, lang, data }) {
  const notify = useToast();
  const [refs, setRefs] = useState(null);
  const [story, setStory] = useState(null); // { blob, url }
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
  useEffect(() => () => story && URL.revokeObjectURL(story.url), [story]);

  const growth = r.total_growth_pct;
  const captions = useMemo(() => {
    const vars = { code, link: link || '', growth: growth == null ? '' : `${growth > 0 ? '+' : ''}${fmt(growth)}%` };
    return [t.capGrowth, t.capInvite, t.capShort].map((x) => `${fill(x, vars)}\n\n${HASHTAGS}`);
  }, [t, code, link, growth]);
  const caption = captions[variant];

  async function buildStory() {
    const blob = await renderStory({
      dir: t.dir,
      nickname: data.nickname,
      avatar: data.avatar,
      bigValue: growth == null ? `${linked}` : `${growth > 0 ? '+' : ''}${fmt(growth)}%`,
      bigLabel: growth == null ? t.anReferrals : t.storyGrowth,
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
    const next = { blob, url: URL.createObjectURL(blob) };
    setStory(next);
    return next;
  }

  // نقرة واحدة: تولّد الصورة ثم تفتح نافذة المشاركة الأصلية (Web Share API) بالصورة والنص
  async function shareStory() {
    setBusy(true);
    try {
      const s = story || (await buildStory());
      const file = new File([s.blob], `AW-Robot-${code}.png`, { type: 'image/png' });
      if (navigator.canShare?.({ files: [file] })) {
        await navigator.share({ files: [file], text: caption, title: 'AW Robot' });
        haptic.success();
      } else {
        await copyText(caption);
        notify(t.storyFallback, 'success');
      }
    } catch (e) {
      if (e?.name !== 'AbortError') notify(t.storyErr, 'error');
    } finally {
      setBusy(false);
    }
  }

  async function download() {
    const s = story || (await buildStory());
    const a = document.createElement('a');
    a.href = s.url;
    a.download = `AW-Robot-${code}.png`;
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  async function copy(text, msg) {
    if (await copyText(text)) {
      haptic.success();
      notify(msg, 'success');
    }
  }

  const enc = encodeURIComponent;
  const social = link
    ? [
        { key: 'telegram', img: tgIcon, go: () => openTelegramLink(`https://t.me/share/url?url=${enc(link)}&text=${enc(caption)}`) },
        { key: 'whatsapp', img: waIcon, go: () => openExternal(`https://wa.me/?text=${enc(caption)}`) },
        { key: 'x', img: xIcon, go: () => openExternal(`https://twitter.com/intent/tweet?text=${enc(caption)}`) },
        { key: 'facebook', img: fbIcon, go: () => openExternal(`https://www.facebook.com/sharer/sharer.php?u=${enc(link)}&quote=${enc(caption)}`) },
      ]
    : [];

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
        {story && <img className="story-preview" src={story.url} alt={t.storyTitle} />}
        <div className="actions stack">
          <button type="button" className="btn primary" disabled={busy || !code} onClick={shareStory}>
            <Icon name="share" size={18} />
            <span>{busy ? t.sending : t.storyShare}</span>
          </button>
          <button type="button" className="btn soft" disabled={busy || !code} onClick={story ? download : buildStory}>
            <Icon name="download" size={18} />
            <span>{story ? t.storyDownload : t.storyPreview}</span>
          </button>
        </div>
        {story && <p className="muted small-note">{t.storyHint}</p>}
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
        {social.length > 0 && (
          <div className="social-row">
            {social.map((sn) => (
              <button key={sn.key} type="button" className={`social-btn is-${sn.key}`} onClick={sn.go} aria-label={sn.key}>
                <img src={sn.img} alt="" />
              </button>
            ))}
          </div>
        )}
        <p className="muted small-note">{t.capNote}</p>
      </div>
    </section>
  );
}
