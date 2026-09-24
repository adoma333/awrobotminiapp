import React from 'react';

// شروط الاستخدام وإخلاء المسؤولية (Terms & Risks) — تُقرأ ويوافق عليها المستخدم قبل ربط الحساب
const CONTENT = {
  ar: {
    intro: 'الرجاء قراءة البنود التالية بعناية قبل المتابعة:',
    items: [
      ['الالتزام بالتداول الآلي وعدم التدخل اليدوي', 'يقر العميل بأن حساب التداول المربوط يُدار آلياً بواسطة خوارزميات AW ROBOT. يُحظر تماماً فتح أو إغلاق الصفقات يدوياً، أو تعديل أوامر أخذ الأرباح وإيقاف الخسارة. أي تدخل يدوي يُعد إخلالاً بالمعايير الإحصائية وقد يؤدي إلى نتائج عكسية وخسائر يتحمل العميل مسؤوليتها الكاملة.'],
      ['عدم التدخل في عمليات الإيداع والسحب', 'تؤكد المنصة أن نظام AW ROBOT ليس لديه أي صلاحيات وصول لعمليات السحب والإيداع الخاصة بحساب العميل. جميع التعاملات المالية تتم مباشرة بين العميل وشركة الوساطة المالية الخاصة به، ولا تتحمل المنصة أي مسؤولية عن أي تأخير أو قيود تُفرض على عمليات السحب والإيداع.'],
      ['حماية وأمان بيانات الاعتماد', 'تلتزم المنصة بتشفير بياناتك وحمايتها عبر أنظمة أمان متطورة، وتقتصر صلاحية الاطلاع عليها على المالك والمنصة فقط. كما يتحمل العميل المسؤولية الكاملة عن حفظ بيانات تسجيل حساب التداول، وتُخلي المنصة مسؤوليتها من أي خسائر ناتجة عن مشاركتها مع طرف ثالث.'],
      ['طبيعة الأسواق المالية والمخاطر', 'يتفهم العميل أن التداول في أسواق الفوركس ينطوي على مخاطر بطبيعته، لذا تعتمد AW ROBOT على خوارزميات متطورة ونماذج مدعومة بإدارة مخاطر صارمة تهدف إلى حماية رأس المال وتعزيز الاستقرارية وتحقيق أفضل النتائج الإيجابية في مختلف ظروف السوق.'],
    ],
    ackTitle: '⚖️ إقرار وموافقة',
    ack: 'بضغطك على "موافقة ومتابعة" وإكمال عملية الربط فإنك تؤكد اطلاعك وموافقتك على شروط الاستخدام المعتمدة لدى AW ROBOT.',
  },
  en: {
    intro: 'Please read the following terms carefully before continuing:',
    items: [
      ['Automated trading only — no manual intervention', 'The client acknowledges that the linked trading account is managed automatically by AW ROBOT algorithms. Opening or closing trades manually, or editing take-profit and stop-loss orders, is strictly prohibited. Any manual intervention breaks the statistical model and may lead to adverse results and losses for which the client bears full responsibility.'],
      ['No access to deposits or withdrawals', 'AW ROBOT has no access to deposits or withdrawals on the client’s account. All financial transactions take place directly between the client and their broker, and the platform bears no responsibility for any delays or restrictions imposed on deposits or withdrawals.'],
      ['Protection of credentials', 'The platform protects your data with advanced security systems, and access is limited to the owner and the platform. The client is fully responsible for safeguarding their trading account credentials, and the platform is not liable for any losses resulting from sharing them with a third party.'],
      ['Nature of financial markets and risk', 'The client understands that forex trading is inherently risky. AW ROBOT therefore relies on advanced algorithms and models backed by strict risk management, aiming to protect capital, improve stability and achieve the best possible results across market conditions.'],
    ],
    ackTitle: '⚖️ Acknowledgement & consent',
    ack: 'By tapping “Agree & continue” and completing the account link, you confirm that you have read and accepted the AW ROBOT terms of use.',
  },
};

export default function TermsRisks({ t, lang, onAgree, onBack }) {
  const c = CONTENT[lang] || CONTENT.en;
  return (
    <section className="step legal terms-risks">
      <h1>{t.termsRisksTitle}</h1>
      <p className="sub">{c.intro}</p>
      <ol className="terms-list">
        {c.items.map(([title, body]) => (
          <li key={title}>
            <h2>{title}</h2>
            <p>{body}</p>
          </li>
        ))}
      </ol>
      <div className="terms-ack">
        <h2>{c.ackTitle}</h2>
        <p>{c.ack}</p>
      </div>
      <div className="actions">
        <button type="button" className="btn ghost" onClick={onBack}>
          <svg className="chev" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M15 6l-6 6 6 6" /></svg>
          <span>{t.back}</span>
        </button>
        <button type="button" className="btn primary" onClick={onAgree}>
          <span>{t.termsAgree}</span>
        </button>
      </div>
    </section>
  );
}
