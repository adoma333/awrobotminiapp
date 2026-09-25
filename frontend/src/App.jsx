import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import logo from './assets/logo-wordmark.png';
import { messages } from './i18n';
import { setupTelegram, tgLang, haptic, askWriteAccess, closeApp, openExternal } from './telegram';
import { completeOnboarding, errorCodeOf, getAnnouncement, getNotifications, getStatus, markAnnouncementSeen, openStatusStream, register } from './api';
import { openSupport, setSupportConfig, setSupportPage } from './support';
import Stepper from './components/Stepper';
import LanguageStep from './components/LanguageStep';
import ProfileStep from './components/ProfileStep';
import Plans from './components/Plans';
import MT5FormStep from './components/MT5FormStep';
import StatusScreen from './components/StatusScreen';
import Dashboard from './components/Dashboard';
import Settings from './components/Settings';
import LegalPage from './components/LegalPage';
import FAQ from './components/FAQ';
import InterestCalculator from './components/InterestCalculator';
import BillingHistory from './components/BillingHistory';
import RewardsHub from './components/RewardsHub';
import Onboarding from './components/Onboarding';
import BottomNav from './components/BottomNav';
import Analytics from './components/Analytics';
import Referral from './components/Referral';
import TermsRisks from './components/TermsRisks';
import NetworkBanner from './components/NetworkBanner';
import { AppSkeleton } from './components/Skeleton';
import TopBar from './components/TopBar';
import ErrorCenter, { ErrorBoundary } from './components/ErrorCenter';
import WhatsNew from './components/WhatsNew';
import Notifications from './components/Notifications';

const ONBOARD_KEY = 'aw_onboarded';
const EMPTY_MT5 = { login: '', password: '', server: '' };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// زر "تجديد الآن" في تذكير التجديد يفتح التطبيق على ?renew=ton: شاشة الباقات + TON Connect مباشرة
const RENEW_TON = new URLSearchParams(window.location.search).get('renew') === 'ton';

export default function App() {
  const [lang, setLang] = useState(tgLang === 'ar' ? 'ar' : 'en');
  const [phase, setPhase] = useState('loading'); // loading | flow | dashboard | status
  const [step, setStep] = useState('lang'); // lang | profile | mt5  (شراء الباقة بعد الربط)
  const [view, setView] = useState('main'); // داخل اللوحة: main | plans | settings | terms | privacy | faq | calc | billing
  const [profile, setProfile] = useState({ nickname: '', avatar: 'boy' });
  const [mt5, setMt5] = useState(EMPTY_MT5);
  const [info, setInfo] = useState({ status: 'none' }); // آخر رد من /api/status
  const [submitting, setSubmitting] = useState(false);
  const [errorCode, setErrorCode] = useState('');
  const [showOnboarding, setShowOnboarding] = useState(false);
  const [termsOk, setTermsOk] = useState(false); // موافقة Terms & Risks قبل الربط
  const [showTerms, setShowTerms] = useState(false);
  const [preferredReward, setPreferredReward] = useState(null); // جائزة اختارها من محفظة المكافآت
  const [streaming, setStreaming] = useState(false); // بث SSE متصل = لا حاجة للاستعلام الدوري
  const [unread, setUnread] = useState(0); // شارة 🔔
  const [ann, setAnn] = useState(null); // نافذة "ما الجديد"
  const annAsked = useRef(false);
  const phaseRef = useRef(phase);
  phaseRef.current = phase;

  const t = messages[lang];
  // الاسم والصورة والنوع تُطلب مرة واحدة فقط (أول فتح): بعد فكّ الربط يعود مباشرة لربط الحساب
  const [returning, setReturning] = useState(false);
  const steps = useMemo(() => (returning ? ['mt5'] : ['lang', 'profile', 'mt5']), [returning]);
  const sub = info.subscription || null;

  useEffect(() => {
    setupTelegram();
  }, []);

  useEffect(() => {
    document.documentElement.lang = lang;
    document.documentElement.dir = t.dir;
  }, [lang, t.dir]);

  // رابط الدعم يُحفظ محليًا ليعمل زر الدعم حتى مع انقطاع الخادم
  useEffect(() => {
    setSupportConfig(info.settings, info.bot_username);
  }, [info.settings, info.bot_username]);

  useEffect(() => {
    setSupportPage(phase === 'dashboard' ? view : `${phase}:${step}`);
  }, [phase, view, step]);

  // عدد الإشعارات غير المقروءة (كل دقيقة أثناء فتح اللوحة)
  const refreshUnread = useCallback(() => {
    getNotifications().then((d) => setUnread(d.unread || 0)).catch(() => {});
  }, []);
  useEffect(() => {
    if (phase !== 'dashboard') return undefined;
    refreshUnread();
    const id = setInterval(refreshUnread, 60000);
    return () => clearInterval(id);
  }, [phase, refreshUnread]);

  // نافذة التحديثات: تُطلب مرة واحدة لكل فتح للتطبيق، والخادم يقرر إن كان يحين عرضها
  useEffect(() => {
    if (annAsked.current || phase === 'loading' || showOnboarding) return;
    annAsked.current = true;
    getAnnouncement().then((r) => r?.announcement && setAnn(r.announcement)).catch(() => {});
  }, [phase, showOnboarding]);

  function closeAnnouncement(action, never) {
    const a = ann;
    setAnn(null);
    markAnnouncementSeen(a.id, never).catch(() => {});
    if (action === 'plans' && phase === 'dashboard') setView('plans');
    else if (action === 'support') openSupport();
    else if (action === 'url' && a.cta_url) openExternal(a.cta_url);
  }

  const refreshStatus = useCallback(async () => {
    const s = await getStatus();
    setInfo(s);
    return s;
  }, []);

  // ───────── التحميل الأول: نقرّر أين يبدأ المستخدم ─────────
  useEffect(() => {
    getStatus()
      .then((s) => {
        setInfo(s);
        if (s.language) setLang(s.language);
        if (s.status === 'approved') {
          if (RENEW_TON) setView('plans');
          setPhase('dashboard');
        }
        else if (s.status === 'rejected' || s.status === 'pending') setPhase('status');
        else {
          // none / unlinked: يبدأ رحلة الربط (الدفع يأتي بعد الربط)
          if (s.nickname) {
            setProfile({ nickname: s.nickname, avatar: s.avatar || 'boy' });
            setReturning(true);
            setStep('mt5');
          } else if (!localStorage.getItem(ONBOARD_KEY)) setShowOnboarding(true);
          setPhase('flow');
        }
      })
      .catch(() => setPhase('flow'));
  }, []);

  // ───────── تحديث لحظي عبر SSE (الرصيد، الاشتراك/الدفع، المزامنة) ─────────
  const started = phase !== 'loading';
  useEffect(() => {
    if (!started) return undefined;
    return openStatusStream((s) => {
      const ph = phaseRef.current;
      if (ph === 'flow') {
        setInfo((prev) => ({ ...prev, subscription: s.subscription })); // لا نقاطع رحلة الربط
        return;
      }
      if (s.status && s.status !== 'none') setInfo(s);
      if (ph === 'status' && s.status === 'approved') setPhase('dashboard');
    }, setStreaming);
  }, [started]);

  // ───────── استعلام دوري (احتياطي فقط أثناء انقطاع البث) ─────────
  //   طلب معلّق (قديم): كل 4ث · اللوحة: كل دقيقة، وكل 5ث حتى تصل أول بيانات
  useEffect(() => {
    if (streaming) return undefined;
    const st = info.status;
    let ms = null;
    if (phase === 'status' && st === 'pending') ms = 4000;
    else if (phase === 'dashboard') ms = info.live ? 60000 : 5000;
    if (!ms) return undefined;
    const id = setInterval(() => {
      getStatus()
        .then((s) => {
          if (s.status && s.status !== 'none') setInfo(s);
          if (phase === 'status' && s.status === 'approved') setPhase('dashboard');
        })
        .catch(() => {});
    }, ms);
    return () => clearInterval(id);
  }, [phase, info.status, Boolean(info.live), streaming]);

  // ───────── التسجيل ─────────
  async function finishLinked() {
    const s = await refreshStatus();
    if (s.status === 'approved') {
      haptic.success();
      setMt5(EMPTY_MT5);
      // بلا اشتراك فعّال: نعرض الباقات مباشرة بعد نجاح الربط
      setView(s.subscription?.active ? 'main' : 'plans');
      setPhase('dashboard');
    }
  }

  // اتصال انقطع أو انتهت مهلته وقد يكون الربط تمّ فعلًا: نراقب الحالة بضع دقائق
  async function waitForApproval(maxMs) {
    const until = Date.now() + maxMs;
    while (Date.now() < until) {
      await sleep(3000);
      try {
        const s = await getStatus();
        if (s.status === 'approved') return true;
      } catch {
        /* نتابع */
      }
    }
    return false;
  }

  async function submit() {
    setSubmitting(true);
    setErrorCode('');
    try {
      await askWriteAccess();
      await register({
        language: lang,
        profile: { nickname: profile.nickname.trim(), avatar: profile.avatar },
        mt5: { login: mt5.login.trim(), password: mt5.password, server: mt5.server.trim() },
        terms_accepted: termsOk,
      });
      await finishLinked();
    } catch (e) {
      const code = errorCodeOf(e);
      if (code === 'approved') {
        await finishLinked();
      } else if (code === 'network') {
        if (await waitForApproval(150000)) await finishLinked();
        else {
          haptic.error();
          setErrorCode('verification_temporarily_unavailable');
        }
      } else {
        haptic.error();
        setErrorCode(code);
      }
    } finally {
      setSubmitting(false);
    }
  }

  // بعد فكّ الربط: نعود لرحلة الربط لحساب جديد، والاشتراك باقٍ
  async function afterUnlink() {
    const s = await refreshStatus();
    if (s.nickname) setProfile({ nickname: s.nickname, avatar: s.avatar || 'boy' });
    setReturning(Boolean(s.nickname));
    setMt5(EMPTY_MT5);
    setErrorCode('');
    setStep('mt5');
    setView('main');
    setPhase('flow');
  }

  function retry() {
    setErrorCode('');
    if (info.nickname) setProfile({ nickname: info.nickname, avatar: info.avatar || 'boy' });
    setReturning(Boolean(info.nickname));
    setStep('mt5');
    setPhase('flow');
  }

  const idx = steps.indexOf(step);
  const go = (delta) => setStep(steps[Math.min(steps.length - 1, Math.max(0, idx + delta))]);
  const isHero = phase === 'flow' && step === 'lang';

  return (
    <main className="app" dir={t.dir}>
      <NetworkBanner t={t} />
      {isHero ? (
        <header className="brand is-hero" dir="ltr">
          <img src={logo} alt="AW" />
        </header>
      ) : (
        <TopBar t={t} showBell={phase === 'dashboard'} unread={unread} onBell={() => setView('notifications')} />
      )}
      <ErrorBoundary t={t}>

      {phase === 'loading' && <AppSkeleton />}

      {phase === 'flow' && showOnboarding && (
        <div className="stage">
          <Onboarding
            t={t}
            onDone={() => {
              localStorage.setItem(ONBOARD_KEY, '1');
              setShowOnboarding(false);
              completeOnboarding().catch(() => {}); // أول خطوة: بطاقة خدش الترحيب
            }}
          />
        </div>
      )}

      {phase === 'flow' && !showOnboarding && showTerms && (
        <div className="stage">
          <TermsRisks
            t={t}
            lang={lang}
            onBack={() => setShowTerms(false)}
            onAgree={() => {
              setTermsOk(true);
              setShowTerms(false);
            }}
          />
        </div>
      )}

      {phase === 'flow' && !showOnboarding && !showTerms && (
        <>
          {steps.length > 1 && <Stepper step={idx + 1} total={steps.length} />}
          <div key={step} className="stage">
            {step === 'lang' && <LanguageStep t={t} lang={lang} setLang={setLang} onNext={() => go(1)} />}
            {step === 'profile' && (
              <ProfileStep t={t} profile={profile} setProfile={setProfile} onNext={() => go(1)} onBack={() => go(-1)} />
            )}
            {step === 'mt5' && (
              <MT5FormStep
                t={t}
                mt5={mt5}
                setMt5={setMt5}
                submitting={submitting}
                errorCode={errorCode}
                onSubmit={submit}
                termsOk={termsOk}
                setTermsOk={setTermsOk}
                onOpenTerms={() => setShowTerms(true)}
                onBack={idx > 0 ? () => go(-1) : undefined}
              />
            )}
          </div>
        </>
      )}

      {phase === 'status' && (
        <div className="stage">
          <StatusScreen t={t} status={info.status} reason={info.reason} onRetry={retry} onClose={closeApp} />
        </div>
      )}

      {phase === 'dashboard' && (
        <div className="stage has-bottom-nav">
          {view === 'terms' || view === 'privacy' ? (
            <LegalPage t={t} lang={lang} page={view} onBack={() => setView('settings')} />
          ) : view === 'notifications' ? (
            <Notifications t={t} lang={lang} onBack={() => setView('main')} onRead={() => setUnread(0)} />
          ) : view === 'faq' ? (
            <FAQ t={t} lang={lang} onBack={() => setView('settings')} />
          ) : view === 'calc' ? (
            <InterestCalculator t={t} lang={lang} onBack={() => setView('settings')} />
          ) : view === 'billing' ? (
            <BillingHistory t={t} lang={lang} onBack={() => setView('settings')} />
          ) : view === 'settings' ? (
            <Settings
              t={t}
              lang={lang}
              setLang={setLang}
              data={info}
              onBack={() => setView('main')}
              onRenew={() => setView('plans')}
              onUnlinked={afterUnlink}
              onLegal={(page) => setView(page)}
              onFaq={() => setView('faq')}
              onCalc={() => setView('calc')}
              onBilling={() => setView('billing')}
              onRewards={() => setView('rewards')}
              onProfileSaved={() => refreshStatus().catch(() => {})}
            />
          ) : view === 'analytics' ? (
            <Analytics t={t} lang={lang} data={info} onReferral={() => setView('referral')} />
          ) : view === 'referral' ? (
            <Referral t={t} lang={lang} data={info} />
          ) : view === 'rewards' ? (
            <RewardsHub
              t={t}
              onBack={() => setView('main')}
              onUse={(id) => {
                setPreferredReward(id);
                setView('plans');
              }}
              onRedeemed={() => refreshStatus().catch(() => {})}
            />
          ) : view === 'plans' ? (
            <Plans
              t={t}
              lang={lang}
              mode="renew"
              sub={sub}
              botUsername={info.bot_username}
              autoTon={RENEW_TON}
              settings={info.settings}
              preferredReward={preferredReward}
              refreshStatus={refreshStatus}
              onContinue={() => setView('main')}
              onBack={() => setView('main')}
            />
          ) : (
            <Dashboard t={t} lang={lang} data={info} onRenew={() => setView('plans')} onRewards={() => setView('rewards')} />
          )}
        </div>
      )}

      </ErrorBoundary>
      {phase === 'dashboard' && <BottomNav t={t} view={view} onSelect={setView} />}
      <ErrorCenter t={t} />
      {ann && <WhatsNew t={t} lang={lang} ann={ann} onClose={closeAnnouncement} />}
    </main>
  );
}
