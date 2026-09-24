import { initData } from './telegram';

const API = import.meta.env.VITE_API_URL ?? '';

// خارج تلجرام (معاينة المتصفح أثناء التطوير) نستخدم ردودًا وهمية لعرض كل الشاشات.
const DEV_MOCK = import.meta.env.DEV && !initData;
const mock = { subAt: 0, approved: false, unlinked: false, prize: null, revealed: false };

async function request(method, path, body) {
  let res;
  try {
    res = await fetch(`${API}${path}`, {
      method,
      headers: { 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    const err = new Error('network');
    err.status = 0;
    throw err;
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(typeof data.detail === 'string' ? data.detail : 'request_failed');
    err.status = res.status;
    err.detail = data.detail;
    throw err;
  }
  return data;
}

// يحوّل أي خطأ إلى رمز نص: network | invalid_input | أو قيمة detail القادمة من الباك اند
export function errorCodeOf(e) {
  if (!e || e.status === 0 || e.status === undefined) return 'network';
  if ([499, 502, 504].includes(e.status) && typeof e.detail !== 'string') return 'network';
  return typeof e.detail === 'string' ? e.detail : 'invalid_input';
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// بيانات تجريبية للمعاينة خارج تلجرام فقط
function devReport(now) {
  const series = Array.from({ length: 90 }, (_, i) => {
    const d = new Date((now - (89 - i) * 86400) * 1000).toISOString().slice(0, 10);
    return { d, pnl: Math.round((Math.sin(i / 5) * 40 + 18) * 100) / 100 };
  });
  return {
    daily_pnl: 42.1, daily_growth_pct: 0.31, weekly_pnl: 180.4, weekly_growth_pct: 1.37, monthly_pnl: 620.3,
    monthly_growth_pct: 4.86, total_pnl: 3395.59, total_growth_pct: 33.96, net_deposits: 10000, trades: 214,
    wins: 131, losses: 83, win_rate: 61.21, profit_factor: 1.84, avg_win: 58.2, avg_loss: 49.6, payoff_ratio: 1.17,
    expectancy: 15.9, best_trade: 412.5, worst_trade: -280.1, gross_profit: 7624.2, gross_loss: 4116.8,
    max_drawdown: 902.3, max_drawdown_pct: 7.1, series,
  };
}

export async function getStatus() {
  if (DEV_MOCK) {
    await sleep(300);
    const now = Math.floor(Date.now() / 1000);
    const subActive = mock.subAt && Date.now() > mock.subAt;
    const base = {
      subscription: subActive
        ? { active: true, expires_at: now + 30 * 86400, days_left: 30, package_name_ar: 'شهري', package_name_en: 'Monthly' }
        : null,
      referral_code: 'AB12CD',
      bot_username: 'awfxapp_bot',
      settings: { kill_switch: false, referral_enabled: true, referral_days: 7 },
    };
    if (!mock.approved) {
      // مستخدم جديد بلا ملف شخصي؛ بعد فكّ الربط يبقى اسمه وصورته (كما يعيد الخادم)
      const who = mock.unlinked ? { nickname: 'Ahmed', avatar: 'boy' } : {};
      return { status: mock.unlinked ? 'unlinked' : 'none', ...who, bot_username: 'awfxapp_bot', ...base };
    }
    return {
      status: 'approved', nickname: 'Ahmed', avatar: 'boy', language: 'ar', ...base,
      account: { login: '51234567', server: 'Exness-MT5Trial16' },
      live: { balance: 13395.59, equity: 13352.1, profit: -43.49, margin: 210.5, margin_free: 13141.6, margin_level: 6343.2, leverage: 2000, currency: 'USD', updated_at: now - 300 },
      report: devReport(now),
      sync: { state: 'ok', last_ok: now - 300 },
    };
  }
  return request('POST', '/api/status', { init_data: initData });
}

// بث لحظي لحالة الحساب والدفع (SSE). يعيد الاتصال تلقائيًا بتراجع أُسّي (1ث، 2ث، 4ث ... حتى 30ث).
// onUp(true|false) يبلّغ بحالة الاتصال كي تعود الواجهة للاستعلام الدوري مؤقتًا عند انقطاعه.
export function openStatusStream(onStatus, onUp) {
  if (DEV_MOCK || typeof EventSource === 'undefined') return () => {};
  let es;
  let timer;
  let attempt = 0;
  let stopped = false;
  const connect = () => {
    es = new EventSource(`${API}/api/stream?init_data=${encodeURIComponent(initData)}`);
    es.onopen = () => {
      attempt = 0;
      onUp?.(true);
    };
    es.addEventListener('status', (e) => {
      try {
        onStatus(JSON.parse(e.data));
      } catch {
        /* رسالة تالفة: نتجاهلها */
      }
    });
    es.onerror = () => {
      es.close();
      onUp?.(false);
      if (stopped) return;
      timer = setTimeout(connect, Math.min(30000, 1000 * 2 ** attempt++));
    };
  };
  connect();
  return () => {
    stopped = true;
    clearTimeout(timer);
    es?.close();
  };
}

export async function getPackages() {
  if (DEV_MOCK) {
    await sleep(400);
    return {
      packages: [
        { id: 'p1', name_ar: 'AW Starter', name_en: 'AW Starter', price_usd: 19, duration_days: 30, price_ton: 5.43, tagline_ar: 'مناسب للمبتدئين', tagline_en: 'Great for beginners',
          features_ar: ['مدة الاشتراك 30 يومًا', 'مناسب للمبتدئين', 'تشغيل آلي كامل للخدمة'], features_en: ['30-day subscription', 'Great for beginners', 'Fully automated operation'] },
        { id: 'p2', name_ar: 'AW Pro', name_en: 'AW Pro', price_usd: 129, duration_days: 30, price_ton: 36.86, price_stars: 6500, featured: true, tagline_ar: 'الأكثر طلبًا', tagline_en: 'Most popular',
          features_ar: ['مدة الاشتراك 30 يومًا', 'نماذج تشغيل متعددة', 'إمكانية تشغيل وإيقاف النموذج', 'خدمة دعم ذكية عبر شات AI'], features_en: ['30-day subscription', 'Multiple trading models', 'Start / stop the model anytime', 'Smart AI chat support'] },
        { id: 'p3', name_ar: 'AW Premium', name_en: 'AW Premium', price_usd: 449, duration_days: 90, price_ton: 128.29, tagline_ar: 'للمحترفين', tagline_en: 'For professionals',
          features_ar: ['مدة الاشتراك 90 يومًا', 'إمكانية ربط حسابين تداول', 'إمكانية تشغيل وإيقاف النموذج', 'إعدادات تحكم متقدمة', 'خدمة دعم ذكية عبر شات AI'], features_en: ['90-day subscription', 'Link two trading accounts', 'Start / stop the model anytime', 'Advanced control settings', 'Smart AI chat support'] },
      ],
      ton_enabled: true,
    };
  }
  return request('GET', '/api/packages');
}

export async function createPayment(packageId, rewardId) {
  if (DEV_MOCK) {
    await sleep(500);
    mock.subAt = Date.now() + 8000;
    return { invoice_url: 'https://example.com/pay', order_id: 'dev', widget_url: 'about:blank' };
  }
  return request('POST', '/api/payments/create', { init_data: initData, package_id: packageId, reward_id: rewardId || null });
}

export async function createStarsPayment(packageId, rewardId) {
  if (DEV_MOCK) {
    await sleep(500);
    mock.subAt = Date.now() + 8000;
    return { invoice_link: 'https://t.me/$dev' };
  }
  return request('POST', '/api/payments/create-stars', { init_data: initData, package_id: packageId, reward_id: rewardId || null });
}

export async function createTonPayment(packageId, rewardId) {
  if (DEV_MOCK) {
    await sleep(500);
    mock.subAt = Date.now() + 8000;
    return { order_id: 'dev-ton', address: 'UQ-dev', amount_nano: '8000000000', payload: '', valid_until: 0 };
  }
  return request('POST', '/api/payments/create-ton', { init_data: initData, package_id: packageId, reward_id: rewardId || null });
}

export async function checkTonPayment(orderId) {
  if (DEV_MOCK) return { status: 'waiting' };
  return request('POST', '/api/payments/ton-check', { init_data: initData, order_id: orderId });
}

export async function register(payload) {
  // payload.terms_accepted: موافقة Terms & Risks (يرفض الخادم الربط بدونها)
  if (DEV_MOCK) {
    await sleep(3500);
    mock.approved = true;
    return { status: 'approved' };
  }
  return request('POST', '/api/register', { init_data: initData, ...payload });
}

export async function unlink() {
  if (DEV_MOCK) {
    await sleep(700);
    mock.approved = false;
    mock.unlinked = true;
    return { ok: true };
  }
  return request('POST', '/api/unlink', { init_data: initData });
}

export async function searchServers(q) {
  if (DEV_MOCK) {
    const all = [
      { id: 'exnessmt5trial16', name: 'Exness-MT5Trial16', type: 'demo', verified: true },
      { id: 'exnessmt5real21', name: 'Exness-MT5Real21', type: 'real', verified: true },
      { id: 'dukascopydemomt5', name: 'Dukascopy-Demo-MT5', type: 'demo', verified: false },
      { id: 'metaquotesdemo', name: 'MetaQuotes-Demo', type: 'demo', verified: true },
    ];
    const k = q.toLowerCase().replace(/[^a-z0-9]/g, '');
    return { servers: all.filter((s) => s.id.includes(k.slice(0, 5))).map((s) => ({ ...s, exact: s.id === k })) };
  }
  return request('GET', `/api/servers?q=${encodeURIComponent(q)}`);
}

export async function updatePhoto(photoB64) {
  if (DEV_MOCK) return { ok: true, photo_url: photoB64 ? `data:image/jpeg;base64,${photoB64}` : null };
  return request('POST', '/api/profile/photo', { init_data: initData, photo: photoB64 });
}

export async function updateProfile(patch) {
  if (DEV_MOCK) return { ok: true };
  return request('POST', '/api/profile', { init_data: initData, ...patch });
}

export async function getBillingHistory() {
  if (DEV_MOCK) {
    await sleep(300);
    return {
      payments: [
        { order_id: 'demo-1', date: Date.now() / 1000 - 86400 * 3, amount: 49, currency: 'USD', plan_name_ar: 'شهري', plan_name_en: 'Monthly', status: 'finished', tx_id: 'demo-tx-1' },
        { order_id: 'demo-2', date: Date.now() / 1000 - 86400 * 33, amount: 300, currency: 'XTR', plan_name_ar: 'شهري', plan_name_en: 'Monthly', status: 'finished', tx_id: 'demo-tx-2' },
      ],
    };
  }
  return request('GET', `/api/billing/history?init_data=${encodeURIComponent(initData)}`);
}

export async function sendFeedback(rating, message) {
  if (DEV_MOCK) {
    await sleep(400);
    return { ok: true };
  }
  return request('POST', '/api/feedback', { init_data: initData, rating, message });
}

// ───────── بطاقات الخدش والمكافآت ─────────
export async function completeOnboarding() {
  if (DEV_MOCK) return { ok: true };
  return request('POST', '/api/onboarding/complete', { init_data: initData });
}

export async function getRewards() {
  if (DEV_MOCK) {
    await sleep(300);
    const now = Date.now() / 1000;
    return {
      cards: mock.revealed ? [] : [{ id: 'dev_welcome', event: 'welcome', created_at: now }],
      rewards: mock.revealed
        ? [{ id: 'dev_welcome', event: 'welcome', type: 'discount', value: 20, earned_at: now, expires_at: now + 24 * 3600, status: 'active' }]
        : [],
      phone_verified: true,
      ttl_hours: 24,
    };
  }
  return request('GET', `/api/rewards?init_data=${encodeURIComponent(initData)}`);
}

export async function claimScratch(cardId) {
  if (DEV_MOCK) {
    await sleep(300);
    const token = btoa(JSON.stringify({ card: cardId, type: 'discount', value: 20 }));
    return { card_id: cardId, token, sig: 'dev' };
  }
  return request('POST', '/api/scratch/claim', { init_data: initData, card_id: cardId || null });
}

export async function revealScratch(cardId) {
  if (DEV_MOCK) {
    mock.revealed = true;
    const now = Date.now() / 1000;
    return { id: cardId, type: 'discount', value: 20, earned_at: now, expires_at: now + 24 * 3600, status: 'active' };
  }
  return request('POST', '/api/scratch/reveal', { init_data: initData, card_id: cardId });
}

export async function redeemReward(rewardId) {
  if (DEV_MOCK) return { ok: true };
  return request('POST', '/api/rewards/redeem', { init_data: initData, reward_id: rewardId });
}

// الجائزة تصل من الخادم مختومة (token + توقيع)؛ الواجهة تفكّها للعرض فقط ولا تولّد أي جائزة
export function openSealedPrize(token) {
  const b64 = token.replace(/-/g, '+').replace(/_/g, '/');
  const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
  return JSON.parse(new TextDecoder().decode(bytes));
}

// ───────── التحليلات والإحالة ─────────
export async function getAnalytics() {
  if (DEV_MOCK) {
    await sleep(300);
    return { referrals: { invited: 12, linked: 8, paid: 5, conversion_pct: 66.7 } };
  }
  return request('GET', `/api/analytics?init_data=${encodeURIComponent(initData)}`);
}

// ───────── بوابة العملات الرقمية المخصّصة ─────────
export async function getCurrencies() {
  if (DEV_MOCK) {
    return { currencies: [
      { code: 'usdttrc20', symbol: 'USDT', network: 'TRON (TRC20)' },
      { code: 'usdtbsc', symbol: 'USDT', network: 'BNB Smart Chain (BEP20)' },
      { code: 'ton', symbol: 'TON', network: 'TON' },
      { code: 'btc', symbol: 'BTC', network: 'Bitcoin' },
    ] };
  }
  return request('GET', '/api/payments/currencies');
}

export async function createCryptoPayment(packageId, rewardId, payCurrency) {
  if (DEV_MOCK) {
    await sleep(500);
    mock.subAt = Date.now() + 20000;
    return {
      order_id: 'dev-np', amount_usd: 129, payment_id: 1, pay_address: 'TQ4hQv9cVx7sX2Y1nP8mJrD5Gk3LwE6Fa1', pay_amount: 129.42,
      pay_currency: payCurrency, payin_extra_id: payCurrency === 'ton' ? '482913' : null, network: 'TRON (TRC20)',
      expires_at: new Date(Date.now() + 20 * 60000).toISOString(),
    };
  }
  return request('POST', '/api/payments/create', {
    init_data: initData, package_id: packageId, reward_id: rewardId || null, pay_currency: payCurrency,
  });
}

export async function paymentStatus(orderId) {
  if (DEV_MOCK) return { status: mock.subAt && Date.now() > mock.subAt - 10000 ? 'confirming' : 'waiting' };
  return request('POST', '/api/payments/status', { init_data: initData, order_id: orderId });
}

// يرفع صورتي القصة والمنشور ويعيد روابط عامة (قصة تلجرام + صفحة مشاركة بمعاينة كاملة)
export async function createShare(storyB64, postB64, caption, captions) {
  if (DEV_MOCK) {
    await sleep(400);
    return { id: 'dev', story_url: '', post_url: '', page_url: 'https://example.com/p/dev' };
  }
  return request('POST', '/api/share/create', { init_data: initData, story: storyB64, post: postB64, caption, captions });
}

export async function getLeaderboard() {
  if (DEV_MOCK) {
    await sleep(300);
    const names = ['Omar Al-Rashid', 'Layla Haddad', 'Yousef Nasser', 'Sara Mansour', 'Karim Aziz', 'Noor Khalil', 'Tariq Saleh', 'Mira Fares'];
    const usd = [812450, 604210, 318900, 84200, 61750, 43980, 27400, 12650];
    const rows = names.map((n, i) => ({ id: `sim${i}`, name: n, avatar: i % 2 ? 'girl' : 'boy', usd: usd[i], delta: i % 3 ? 900 : -400, simulated: true, tier: ['master', 'diamond', 'platinum', 'platinum', 'gold', 'gold', 'gold', 'silver'][i] }));
    rows.splice(5, 0, { id: 'me', name: 'Ahmed', avatar: 'boy', usd: 52340.5, delta: 0, simulated: false, you: true });
    rows.forEach((r, i) => { r.rank = i + 1; });
    return { week: '2026-W39', rows, me: rows[5], total: rows.length, has_simulated: true };
  }
  return request('GET', `/api/leaderboard?init_data=${encodeURIComponent(initData)}`);
}
