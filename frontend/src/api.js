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
    if (!mock.approved) return { status: mock.unlinked ? 'unlinked' : 'none', nickname: 'Ahmed', avatar: 'boy', bot_username: 'awfxapp_bot', ...base };
    return {
      status: 'approved', nickname: 'Ahmed', avatar: 'boy', language: 'ar', ...base,
      account: { login: '51234567', server: 'Exness-MT5Trial16' },
      live: { balance: 13395.59, equity: 13352.1, profit: -43.49, margin: 210.5, margin_free: 13141.6, margin_level: 6343.2, leverage: 2000, currency: 'USD', updated_at: now - 300 },
      report: null,
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
        { id: 'p1', name_ar: 'شهري', name_en: 'Monthly', price_usd: 29, duration_days: 30, price_stars: 1500, price_ton: 8 },
        { id: 'p2', name_ar: 'ربع سنوي', name_en: 'Quarterly', price_usd: 69, duration_days: 90, price_stars: null },
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
