import React, { createContext, useCallback, useContext, useRef, useState } from 'react';

const ToastCtx = createContext(() => {});

let uid = 0;

// إشعارات مخصّصة داخل التطبيق (تظهر أسفل الشاشة وتختفي تلقائيًا).
// ملاحظة: تليجرام لا يسمح بإشعارات نظام حقيقية (Web Push) داخل الـ Mini App،
// فالإشعارات الفعلية بعد إغلاق التطبيق تصل عبر رسائل البوت في تلجرام نفسه.
export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const timers = useRef({});

  const notify = useCallback((text, kind = 'info', ms = 3200) => {
    const id = ++uid;
    setToasts((list) => [...list, { id, text, kind }]);
    timers.current[id] = setTimeout(() => {
      setToasts((list) => list.filter((x) => x.id !== id));
      delete timers.current[id];
    }, ms);
  }, []);

  return (
    <ToastCtx.Provider value={notify}>
      {children}
      <div className="toast-stack" aria-live="polite">
        {toasts.map((tst) => (
          <div key={tst.id} className={`toast toast-${tst.kind}`}>{tst.text}</div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}

export function useToast() {
  return useContext(ToastCtx);
}
