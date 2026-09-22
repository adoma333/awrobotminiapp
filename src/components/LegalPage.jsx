import React from 'react';

// نصوص ثابتة (عربي/إنجليزي) للشروط والأحكام وسياسة الخصوصية.
const CONTENT = {
  terms: {
    ar: {
      title: 'الشروط والأحكام',
      sections: [
        ['نطاق الخدمة', 'AW Robot أداة متابعة تعرض بيانات حساب MT5 الخاص بك (الرصيد، النمو، الصفقات) بعد ربطه. الخدمة للعرض والمتابعة، وليست توصية استثمارية.'],
        ['التداول الآلي وتأكيد الدفع', 'ربط حسابك بالتطبيق قبل إتمام الدفع هو للعرض فقط ولا يفعّل أي متابعة أو تداول آلي. يبدأ التداول الآلي على حسابك فقط بعد تأكيد الدفع وتفعيل الاشتراك.'],
        ['مسؤولية الحساب', 'أنت مسؤول عن دقة بيانات دخولك لحساب MT5 وعن أي نشاط يجري على وسيطك. لا تنفّذ AW Robot صفقات دون تفعيل صريح ضمن نطاق الخدمة المتفق عليه.'],
        ['المدفوعات والاشتراك', 'الاشتراك يُفعَّل فور تأكيد الدفع عبر إحدى وسائل الدفع المتاحة (عملات رقمية أو نجوم تلجرام). المدد والأسعار كما تظهر داخل التطبيق وقت الدفع.'],
        ['التعديلات', 'قد تُحدَّث هذه الشروط من وقت لآخر، وسيُعلن عن أي تغيير جوهري داخل التطبيق أو عبر قناة الدعم.'],
      ],
    },
    en: {
      title: 'Terms & Conditions',
      sections: [
        ['Scope of service', 'AW Robot is a tracking tool that displays your linked MT5 account data (balance, growth, trades). It is for monitoring only and is not investment advice.'],
        ['Automated trading and payment confirmation', 'Linking your account before completing payment is for display purposes only and does not activate any monitoring or automated trading. Automated trading on your account starts only after payment is confirmed and the subscription is active.'],
        ['Account responsibility', 'You are responsible for the accuracy of your MT5 login details and for any activity with your broker. AW Robot does not execute trades without explicit activation within the agreed scope of service.'],
        ['Payments and subscription', 'Your subscription activates as soon as payment is confirmed via an available payment method (crypto or Telegram Stars). Durations and prices are as shown in the app at the time of payment.'],
        ['Changes', 'These terms may be updated from time to time. Material changes will be announced in the app or via the support channel.'],
      ],
    },
  },
  privacy: {
    ar: {
      title: 'سياسة الخصوصية',
      sections: [
        ['البيانات التي نجمعها', 'اسمك المستعار، لغتك، ومعرّف حساب MT5 (رقم الدخول والسيرفر) اللازم لقراءة بيانات حسابك، بالإضافة إلى بيانات الاستخدام العامة داخل التطبيق.'],
        ['كيف نستخدمها', 'نستخدم بيانات MT5 للقراءة فقط: عرض الرصيد والنمو وإحصاءات الصفقات. لا نبيع بياناتك ولا نشاركها مع أي طرف ثالث لأغراض تسويقية.'],
        ['التخزين والأمان', 'تُخزَّن البيانات في قاعدة بيانات مؤمَّنة (Firestore) ولا تُعرض كلمة مرور حسابك لأي طرف داخل واجهة الإدارة.'],
        ['فكّ الربط وحذف البيانات', 'يمكنك فكّ ربط حسابك في أي وقت من الإعدادات، وتُحذف عندها بياناته الحية وإحصاءاته المرتبطة بذلك الحساب.'],
        ['التواصل', 'لأي استفسار حول بياناتك يمكنك التواصل معنا عبر قناة الدعم داخل تلجرام.'],
      ],
    },
    en: {
      title: 'Privacy Policy',
      sections: [
        ['Data we collect', 'Your nickname, language, and MT5 account identifiers (login and server) needed to read your account data, plus general in-app usage data.'],
        ['How we use it', 'We use MT5 data for read-only purposes: showing balance, growth, and trade statistics. We do not sell your data or share it with third parties for marketing.'],
        ['Storage and security', 'Data is stored in a secured database (Firestore) and your account password is never shown to anyone inside the admin interface.'],
        ['Unlinking and data removal', 'You can unlink your account at any time from Settings; its live data and related statistics are then removed.'],
        ['Contact', 'For any question about your data, reach us via the support channel on Telegram.'],
      ],
    },
  },
};

export default function LegalPage({ t, lang, page, onBack }) {
  const c = CONTENT[page][lang] || CONTENT[page].en;
  return (
    <section className="dash">
      <div className="settings-head">
        <button type="button" className="btn ghost" onClick={onBack}>
          <svg className="chev" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M15 6l-6 6 6 6" /></svg>
          <span>{t.back}</span>
        </button>
        <h1>{c.title}</h1>
      </div>
      {c.sections.map(([heading, body]) => (
        <div className="section" key={heading}>
          <h2>{heading}</h2>
          <p className="sub">{body}</p>
        </div>
      ))}
    </section>
  );
}
