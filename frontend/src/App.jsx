import React, { useCallback, useEffect, useMemo, useState } from 'react';
import logo from './assets/logo.png';
import { messages } from './i18n';
import { setupTelegram, tgLang, haptic, askWriteAccess, closeApp } from './telegram';
import { errorCodeOf, getStatus, register } from './api';
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
import Onboarding from './components/Onboarding';
import BottomNav from './components/BottomNav';
import FeedbackButton from './components/FeedbackButton';
import NetworkBanner from './components/NetworkBanner';
import { AppSkeleton } from './components/Skeleton';

const ONBOARD_KEY = 'aw_onboarded';
const EMPTY_MT5 = { login: '', password: '', server: '' };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export default function App() {
  const [lang, setLang] = useState(tgLang === 'ar' ? 'ar' : 'en');
  const [phase, setPhase] = useState('loading'); // loading | flow | dashboard | status
  const [step, setStep] = useState('lang'); // lang | profile | plan | mt5
  const [needsPlan, setNeedsPlan] = useState(true);
  const [view, setView] = useState('main'); // داخل اللوحة: main | plans | settings | terms | privacy | faq | calc
  const [profile, setProfile] = useState({ nickname: '', avatar: 'boy' });
  const [mt5, setMt5] = useState(EMPTY_MT5);
  const [info, setInfo] = useState({ status: 'none' }); // آخر رد من /api/status
  const [submitting, setSubmitting] = useState(false);
  const [errorCode, setErrorCode] = useState('');
  const [showOnboarding, setShowOnboarding] = useState(false);

  const t = messages[lang];
  const steps = useMemo(
    () => (needsPlan ? ['lang', 'profile', 'plan', 'mt5'] : ['lang', 'profile', 'mt5']),
    [needsPlan]
  );
  const sub = info.subscription || null;

  useEffect(() => {
    setupTelegram();
  }, []);

  useEffect(() => {
    document.documentElement.lang = lang;
    document.documentElement.dir = t.dir;
  }, [lang, t.dir]);

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
        setNeedsPlan(!s.subscription?.active);
        if (s.status === 'approved') setPhase('dashboard');
        else if (s.status === 'rejected' || s.status === 'pending') setPhase('status');
        else {
          // none / unlinked: يبدأ رحلة الربط (يتجاوز الدفع إن كان اشتراكه فعّالًا)
          if (!localStorage.getItem(ONBOARD_KEY)) setShowOnboarding(true);
          setPhase('flow');
        }
      })
      .catch(() => setPhase('flow'));
  }, []);

  // ───────── استعلام دوري ─────────
  //   طلب معلّق (قديم): كل 4ث · اللوحة: كل دقيقة، وكل 5ث حتى تصل أول بيانات
  useEffect(() => {
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
  }, [phase, info.status, Boolean(info.live)]);

  // ───────── التسجيل ─────────
  async function finishLinked() {
    const s = await refreshStatus();
    if (s.status === 'approved') {
      haptic.success();
      setMt5(EMPTY_MT5);
      setView('main');
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
      });
      await finishLinked();
    } catch (e) {
      const code = errorCodeOf(e);
      if (code === 'approved') {
        await finishLinked();
      } else if (code === 'subscription_required') {
        haptic.error();
        setNeedsPlan(true);
        setStep('plan');
        refreshStatus().catch(() => {});
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
    const active = Boolean(s.subscription?.active);
    setNeedsPlan(!active);
    if (s.nickname) setProfile({ nickname: s.nickname, avatar: s.avatar || 'boy' });
    setMt5(EMPTY_MT5);
    setErrorCode('');
    setStep(active ? 'mt5' : 'plan');
    setView('main');
    setPhase('flow');
  }

  function retry() {
    setErrorCode('');
    if (info.nickname) setProfile({ nickname: info.nickname, avatar: info.avatar || 'boy' });
    setStep(info.subscription?.active ? 'mt5' : 'plan');
    setPhase('flow');
  }

  const idx = steps.indexOf(step);
  const go = (delta) => setStep(steps[Math.min(steps.length - 1, Math.max(0, idx + delta))]);
  const isHero = phase === 'flow' && step === 'lang';

  return (
    <main className="app" dir={t.dir}>
      <NetworkBanner t={t} />
      <header className={`brand ${isHero ? 'is-hero' : ''}`}>
        <img src={logo} alt="AW" />
      </header>

      {phase === 'loading' && <AppSkeleton />}

      {phase === 'flow' && showOnboarding && (
        <div className="stage">
          <Onboarding
            t={t}
            onDone={() => {
              localStorage.setItem(ONBOARD_KEY, '1');
              setShowOnboarding(false);
            }}
          />
        </div>
      )}

      {phase === 'flow' && !showOnboarding && (
        <>
          <Stepper step={idx + 1} total={steps.length} />
          <div key={step} className="stage">
            {step === 'lang' && <LanguageStep t={t} lang={lang} setLang={setLang} onNext={() => go(1)} />}
            {step === 'profile' && (
              <ProfileStep t={t} profile={profile} setProfile={setProfile} onNext={() => go(1)} onBack={() => go(-1)} />
            )}
            {step === 'plan' && (
              <Plans
                t={t}
                lang={lang}
                mode="flow"
                sub={sub}
                refreshStatus={refreshStatus}
                onContinue={() => go(1)}
                onBack={() => go(-1)}
              />
            )}
            {step === 'mt5' && (
              <MT5FormStep
                t={t}
                mt5={mt5}
                setMt5={setMt5}
                submitting={submitting}
                errorCode={errorCode}
                onSubmit={submit}
                onBack={() => go(-1)}
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
          {view === 'main' && <FeedbackButton t={t} />}
          {view === 'terms' || view === 'privacy' ? (
            <LegalPage t={t} lang={lang} page={view} onBack={() => setView('settings')} />
          ) : view === 'faq' ? (
            <FAQ t={t} lang={lang} onBack={() => setView('settings')} />
          ) : view === 'calc' ? (
            <InterestCalculator t={t} lang={lang} onBack={() => setView('settings')} />
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
            />
          ) : view === 'plans' ? (
            <Plans
              t={t}
              lang={lang}
              mode="renew"
              sub={sub}
              refreshStatus={refreshStatus}
              onContinue={() => setView('main')}
              onBack={() => setView('main')}
            />
          ) : (
            <Dashboard t={t} lang={lang} data={info} onRenew={() => setView('plans')} onSettings={() => setView('settings')} />
          )}
        </div>
      )}

      {phase === 'dashboard' && <BottomNav t={t} view={view} onSelect={setView} />}
    </main>
  );
}
