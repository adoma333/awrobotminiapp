import React from 'react';

// شكل هيكلي بسيط (شريط رمادي نابض) لأي مكان محدد الحجم أثناء التحميل.
export function SkeletonBar({ w = '100%', h = 14, radius = 8, style }) {
  return <span className="skel" style={{ width: w, height: h, borderRadius: radius, ...style }} />;
}

// شاشة هيكلية كاملة لأول تحميل للوحة (بديل عن دوّارة التحميل البسيطة).
export function DashboardSkeleton() {
  return (
    <section className="dash" aria-busy="true" aria-label="loading">
      <div className="who">
        <SkeletonBar w={44} h={44} radius={999} />
        <div className="who-text" style={{ display: 'flex', flexDirection: 'column', gap: 6, flex: 1 }}>
          <SkeletonBar w="40%" h={14} />
          <SkeletonBar w="60%" h={11} />
        </div>
      </div>
      <div className="hero">
        <SkeletonBar w="30%" h={12} style={{ marginBottom: 10 }} />
        <SkeletonBar w="55%" h={34} style={{ marginBottom: 10 }} />
        <SkeletonBar w="25%" h={16} />
      </div>
      <div className="section">
        <SkeletonBar w="20%" h={14} style={{ marginBottom: 12 }} />
        <div className="grid2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div className="cell" key={i}>
              <SkeletonBar w="60%" h={11} style={{ marginBottom: 8 }} />
              <SkeletonBar w="45%" h={18} style={{ marginBottom: 6 }} />
              <SkeletonBar w="50%" h={10} />
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// شاشة هيكلية للتحميل الأول العام (قبل معرفة أين يبدأ المستخدم).
export function AppSkeleton() {
  return (
    <div className="app-skel" aria-busy="true" aria-label="loading">
      <SkeletonBar w="70%" h={16} style={{ margin: '0 auto 12px' }} />
      <SkeletonBar w="90%" h={44} style={{ marginBottom: 12 }} />
      <SkeletonBar w="90%" h={44} />
    </div>
  );
}
