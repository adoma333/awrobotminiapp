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

/** يربط المحفظة إن لزم ثم يرسل معاملة الدفع كما أعدّها الخادم (العنوان والمبلغ والتعليق). */
export async function payWithTon(tx, botUsername) {
  const ui = await getUI(botUsername);
  await ui.connectionRestored;
  if (!ui.connected) await connect(ui);
  return ui.sendTransaction({
    validUntil: tx.valid_until,
    messages: [{ address: tx.address, amount: tx.amount_nano, payload: tx.payload }],
  });
}
