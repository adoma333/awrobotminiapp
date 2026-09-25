// ناقل أخطاء عام: أي جزء من التطبيق (طلبات الشبكة، استثناءات الواجهة، أخطاء العمليات) يبلّغ هنا،
// ومكوّن ErrorCenter يعرض رسالة موحّدة مع زر "تواصل مع الدعم".
const subs = new Set();
let last = { key: '', at: 0 };

export function onAppError(fn) {
  subs.add(fn);
  return () => subs.delete(fn);
}

/** kind: network | server | operation | ui */
export function emitAppError(e) {
  const err = { at: Date.now(), ...e };
  const key = `${err.kind}:${err.code}`;
  if (key === last.key && err.at - last.at < 4000) return; // منع التكرار المتلاحق لنفس الخطأ
  last = { key, at: err.at };
  subs.forEach((fn) => fn(err));
}
