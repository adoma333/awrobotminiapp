import React, { useState } from 'react';
import { haptic } from '../telegram';

const DATA = {
  system: {
    ar: [
      ['ما هو AW ROBOT وكيف يعمل؟', 'AW ROBOT هو نظام تقني متطور لربط حسابات MetaTrader 5 وإدارتها عبر خوارزميات تداول آلي ذكية، مما يتيح لك تنفيذ الصفقات ومتابعة أداء حسابك ونموه بدقة عالية دون الحاجة للتدخل يدويًا.'],
      ['هل أحتاج إلى ترك هاتفي أو حاسوبي مفتوحًا؟', 'لا، تعمل أنظمة AW ROBOT على خوادم سحابية عالية السرعة على مدار 24/7، مما يعني أن عمليات التداول والمتابعة تستمر بشكل آلي حتى لو كان هاتفك مغلقًا.'],
      ['هل يمكن لـ AW ROBOT السحب والإيداع من حسابي؟', 'لا، نظام AW ROBOT ليس لديه أي صلاحيات وصول لعمليات السحب والإيداع الخاصة بحساب العميل. جميع التعاملات المالية تتم مباشرة بين العميل وشركة الوساطة المالية الخاصة به.'],
      ['ماذا أفعل إذا واجهت مشكلة تقنية أو احتجت للمساعدة؟', 'يمكنك التواصل فورًا مع فريق الدعم الفني المخصص من خلال الضغط على «الدعم الفني Support» في الإعدادات.'],
    ],
    en: [
      ['What is AW ROBOT and how does it work?', 'AW ROBOT is an advanced system that links and manages MetaTrader 5 accounts through smart automated-trading algorithms, so trades are executed and your account’s performance and growth are tracked precisely — with no manual intervention.'],
      ['Do I need to keep my phone or computer on?', 'No. AW ROBOT runs on high-speed cloud servers 24/7, so trading and tracking continue automatically even when your phone is off.'],
      ['Can AW ROBOT withdraw or deposit from my account?', 'No. AW ROBOT has no access to deposits or withdrawals on your account. All financial transactions happen directly between you and your broker.'],
      ['What if I face a technical issue or need help?', 'Contact our dedicated support team right away by tapping “Support” in Settings.'],
    ],
  },
  setup: {
    ar: [
      ['كيف أربط حساب MT5؟', 'من رحلة الإعداد الأولى أو من "فكّ الربط ثم إعادة الربط" في الإعدادات، أدخل رقم الحساب وكلمة المرور واسم السيرفر كما هي في تطبيق MT5.'],
      ['لماذا يُرفض حسابي عند الربط؟', 'الأسباب الشائعة: بيانات دخول غير صحيحة، اسم سيرفر خاطئ، أو نوع الحساب/الرافعة غير مدعوم حسب سياسة المنصة الحالية.'],
      ['هل ربط الحساب قبل الدفع يفعّل المتابعة؟', 'لا. الربط قبل تأكيد الدفع للعرض فقط، والمتابعة الفعلية تبدأ بعد تفعيل الاشتراك.'],
    ],
    en: [
      ['How do I link my MT5 account?', 'From the initial setup flow, or from "Unlink then relink" in Settings, enter the login, password and server name exactly as in your MT5 app.'],
      ['Why is my account rejected when linking?', 'Common reasons: wrong login details, wrong server name, or an account type/leverage not currently supported by policy.'],
      ['Does linking before payment activate tracking?', 'No. Linking before payment confirmation is display-only; actual tracking starts once your subscription is active.'],
    ],
  },
  connection: {
    ar: [
      ['لماذا بياناتي لا تتحدث؟', 'التحديث يحدث كل ساعة تقريبًا. لو ظهرت علامة تحذير، فهذا يعني فشل آخر محاولة مزامنة وستتم إعادة المحاولة تلقائيًا.'],
      ['ما معنى "جارٍ جلب بياناتك الأولى"؟', 'بعد أول ربط ناجح، يحتاج النظام دقيقة تقريبًا لسحب أول لقطة من حسابك قبل عرض اللوحة.'],
      ['حسابي متصل لكن الأرقام تبدو قديمة', 'تحقق من اتصال الإنترنت لديك أولًا؛ لو استمرت المشكلة فقد يكون سيرفر الوسيط بطيئًا مؤقتًا وسيُعاد المحاولة تلقائيًا.'],
    ],
    en: [
      ['Why isn\u2019t my data updating?', 'Data refreshes about every hour. A warning icon means the last sync attempt failed and will be retried automatically.'],
      ['What does "Fetching your first data" mean?', 'After your first successful link, the system needs about a minute to pull an initial snapshot before showing the dashboard.'],
      ['My account is linked but numbers look old', 'Check your own internet connection first; if it persists, your broker\u2019s server may be temporarily slow and will be retried automatically.'],
    ],
  },
  billing: {
    ar: [
      ['ما طرق الدفع المتاحة؟', 'العملات الرقمية (USDT/TON عبر NOWPayments) أو نجوم تلجرام ⭐، حسب ما هو متاح للباقة المختارة.'],
      ['متى يُفعَّل اشتراكي؟', 'فور تأكيد الدفع تلقائيًا، بدون تدخل يدوي. لو دفعت ولم يُفعَّل خلال دقائق راسل الدعم مع رقم العملية.'],
      ['هل يمكنني استرجاع أيام الاشتراك المتبقية عند التجديد المبكر؟', 'التجديد يضيف مدة الباقة الجديدة فوق ما تبقى من اشتراكك الحالي تلقائيًا، دون فقدان أي يوم.'],
    ],
    en: [
      ['What payment methods are available?', 'Crypto (USDT/TON via NOWPayments) or Telegram Stars ⭐, depending on what\u2019s enabled for the chosen plan.'],
      ['When does my subscription activate?', 'Automatically as soon as payment is confirmed. If you paid and it hasn\u2019t activated within minutes, contact support with your transaction reference.'],
      ['Do I lose remaining days if I renew early?', 'Renewing adds the new plan\u2019s duration on top of your current remaining time automatically \u2014 no days are lost.'],
    ],
  },
};

const TABS = [
  { key: 'system', label: { ar: 'نظام التشغيل', en: 'Operating system' } },
  { key: 'setup', label: { ar: 'التثبيت وربط MT5', en: 'Setup & MT5 linking' } },
  { key: 'connection', label: { ar: 'مشاكل الاتصال', en: 'Connection issues' } },
  { key: 'billing', label: { ar: 'الاشتراك والدفع', en: 'Subscription & billing' } },
];

function AccordionItem({ q, a, open, onToggle }) {
  return (
    <div className={`faq-item ${open ? 'open' : ''}`}>
      <button type="button" className="faq-q" onClick={onToggle} aria-expanded={open}>
        <span>{q}</span>
        <svg className="faq-caret" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6" /></svg>
      </button>
      {open && <p className="faq-a">{a}</p>}
    </div>
  );
}

export default function FAQ({ t, lang, onBack }) {
  const [tab, setTab] = useState('system');
  const [openIdx, setOpenIdx] = useState(null);
  const items = DATA[tab][lang] || DATA[tab].en;

  function pick(k) {
    haptic.select();
    setTab(k);
    setOpenIdx(null);
  }

  return (
    <section className="dash">
      <div className="settings-head">
        <button type="button" className="btn ghost" onClick={onBack}>
          <svg className="chev" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M15 6l-6 6 6 6" /></svg>
          <span>{t.back}</span>
        </button>
        <h1>{t.faqTitle}</h1>
      </div>

      <div className="faq-tabs" role="tablist">
        {TABS.map((tb) => (
          <button
            key={tb.key}
            type="button"
            role="tab"
            aria-selected={tab === tb.key}
            className={`faq-tab ${tab === tb.key ? 'on' : ''}`}
            onClick={() => pick(tb.key)}
          >
            {tb.label[lang] || tb.label.en}
          </button>
        ))}
      </div>

      <div className="section faq-list">
        {items.map(([q, a], i) => (
          <AccordionItem key={i} q={q} a={a} open={openIdx === i} onToggle={() => setOpenIdx(openIdx === i ? null : i)} />
        ))}
      </div>
    </section>
  );
}
