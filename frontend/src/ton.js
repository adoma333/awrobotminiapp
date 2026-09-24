// TON Connect: تُحمَّل المكتبة عند أول دفع بـ TON فقط كي لا تثقل التحميل الأول للتطبيق.
const API = import.meta.env.VITE_API_URL ?? '';
let uiPromise = null;

function getUI(botUsername) {
  if (!uiPromise) {
    uiPromise = import('@tonconnect/ui').then(({ TonConnectUI, THEME }) => {
      const ui = new TonConnectUI({
        manifestUrl: `${API || window.location.origin}/api/tonconnect-manifest.json`,
        uiPreferences: { theme: THEME.DARK },
      });
      if (botUsername) ui.uiOptions = { actionsConfiguration: { twaReturnUrl: `https://t.me/${botUsername}` } };
      return ui;
    });
  }
  return uiPromise;
}

// يفتح نافذة اختيار المحفظة وينتظر الربط؛ يرفض بـ 'ton_cancelled' إن أُغلقت النافذة بلا ربط
function connect(ui) {
  return new Promise((resolve, reject) => {
    const offStatus = ui.onStatusChange((wallet) => {
      if (wallet) {
        cleanup();
        resolve();
      }
    });
    const offModal = ui.onModalStateChange((state) => {
      if (state.status === 'closed' && !ui.connected) {
        cleanup();
        reject(new Error('ton_cancelled'));
      }
    });
    function cleanup() {
      offStatus();
      offModal();
    }
    ui.openModal().catch((e) => {
      cleanup();
      reject(e);
    });
  });
}

const IDLE_DISCONNECT_MS = 3 * 60 * 1000;
let idleTimer = null;

// فصل المحفظة بعد كل عملية (أو بعد 3 دقائق خمول) كي يختار المستخدم أي محفظة في المرة القادمة بلا تعارض
async function release(ui) {
  clearTimeout(idleTimer);
  try {
    if (ui.connected) await ui.disconnect();
  } catch {
    /* الجلسة انتهت أصلًا */
  }
}

/** يربط المحفظة ثم يرسل معاملة الدفع كما أعدّها الخادم (العنوان والمبلغ والتعليق)، ثم يفصلها دائمًا. */
export async function payWithTon(tx, botUsername) {
  const ui = await getUI(botUsername);
  await ui.connectionRestored;
  if (!ui.connected) await connect(ui);
  clearTimeout(idleTimer);
  idleTimer = setTimeout(() => release(ui), IDLE_DISCONNECT_MS);
  try {
    return await ui.sendTransaction({
      validUntil: tx.valid_until,
      messages: [{ address: tx.address, amount: tx.amount_nano, payload: tx.payload }],
    });
  } finally {
    await release(ui);
  }
}
