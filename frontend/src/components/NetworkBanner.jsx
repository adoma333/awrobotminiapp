import React, { useEffect, useRef, useState } from 'react';
import useOnlineStatus from '../hooks/useOnlineStatus';

// شريط علوي يظهر عند فقدان الاتصال، ورسالة عودة قصيرة عند رجوعه.
export default function NetworkBanner({ t }) {
  const online = useOnlineStatus();
  const [showBack, setShowBack] = useState(false);
  const wasOffline = useRef(false);

  useEffect(() => {
    if (!online) {
      wasOffline.current = true;
      setShowBack(false);
    } else if (wasOffline.current) {
      wasOffline.current = false;
      setShowBack(true);
      const id = setTimeout(() => setShowBack(false), 2500);
      return () => clearTimeout(id);
    }
    return undefined;
  }, [online]);

  if (!online) {
    return (
      <div className="net-banner net-offline" role="status">
        <span className="net-dot" />
        {t.offline}
      </div>
    );
  }
  if (showBack) {
    return (
      <div className="net-banner net-online" role="status">
        <span className="net-dot" />
        {t.backOnline}
      </div>
    );
  }
  return null;
}
