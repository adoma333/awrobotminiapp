export const tg = window.Telegram?.WebApp;
export const initData = tg?.initData || '';
export const tgLang = tg?.initDataUnsafe?.user?.language_code;

export function setupTelegram() {
  if (!tg) return;
  tg.ready();
  tg.expand();
  tg.setHeaderColor?.('#000000');
  tg.setBackgroundColor?.('#000000');
  tg.disableVerticalSwipes?.();
}

export const haptic = {
  select: () => tg?.HapticFeedback?.selectionChanged(),
  success: () => tg?.HapticFeedback?.notificationOccurred('success'),
  error: () => tg?.HapticFeedback?.notificationOccurred('error'),
};

// يطلب إذن مراسلة المستخدم ليصله إشعار القبول/الرفض. لا يعطّل الإرسال إن لم يتوفر.
export function askWriteAccess() {
  return new Promise((resolve) => {
    if (!tg?.requestWriteAccess) return resolve();
    const timer = setTimeout(resolve, 8000);
    try {
      tg.requestWriteAccess(() => {
        clearTimeout(timer);
        resolve();
      });
    } catch {
      clearTimeout(timer);
      resolve();
    }
  });
}

export function closeApp() {
  if (tg) tg.close();
}

export function openExternal(url) {
  if (tg?.openLink) tg.openLink(url);
  else window.open(url, '_blank', 'noopener');
}

// يفتح فاتورة Telegram Stars داخل التطبيق. يرجع false إن لم يكن ذلك متاحًا (متصفح عادي).
export function openInvoice(url, callback) {
  if (!tg?.openInvoice) return false;
  tg.openInvoice(url, callback);
  return true;
}

export function openTelegramLink(url) {
  if (tg?.openTelegramLink) tg.openTelegramLink(url);
  else window.open(url, '_blank', 'noopener');
}

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const el = document.createElement('textarea');
    el.value = text;
    el.style.position = 'fixed';
    el.style.opacity = '0';
    document.body.appendChild(el);
    el.select();
    let ok = false;
    try {
      ok = document.execCommand('copy');
    } catch {
      ok = false;
    }
    document.body.removeChild(el);
    return ok;
  }
}
