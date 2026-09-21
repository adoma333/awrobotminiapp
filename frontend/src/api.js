import { initData } from './telegram';

const API = import.meta.env.VITE_API_URL ?? '';

// خارج تلجرام (معاينة المتصفح أثناء التطوير) نستخدم ردودًا وهمية لعرض كل الشاشات.
const DEV_MOCK = import.meta.env.DEV && !initData;
const mock = { subAt: 0, approved: false, unlinked: false };

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

export async function getPackages() {
  if (DEV_MOCK) {
    await sleep(400);
    return {
      packages: [
        { id: 'p1', name_ar: 'شهري', name_en: 'Monthly', price_usd: 29, duration_days: 30, price_stars: 1500 },
        { id: 'p2', name_ar: 'ربع سنوي', name_en: 'Quarterly', price_usd: 69, duration_days: 90, price_stars: null },
      ],
    };
  }
  return request('GET', '/api/packages');
}

export async function createPayment(packageId) {
  if (DEV_MOCK) {
    await sleep(500);
    mock.subAt = Date.now() + 8000;
    return { invoice_url: 'https://example.com/pay', order_id: 'dev' };
  }
  return request('POST', '/api/payments/create', { init_data: initData, package_id: packageId });
}

export async function createStarsPayment(packageId) {
  if (DEV_MOCK) {
    await sleep(500);
    mock.subAt = Date.now() + 8000;
    return { invoice_link: 'https://t.me/$dev' };
  }
  return request('POST', '/api/payments/create-stars', { init_data: initData, package_id: packageId });
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
