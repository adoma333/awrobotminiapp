import React from 'react';

// ثلاث عقد متصلة بمسار، مثل عقد الدوائر في الشعار.
// العقدة المكتملة تمتلئ، والحالية تتوهج، والقادمة خافتة.
export default function Stepper({ step, total = 3 }) {
  const nodes = Array.from({ length: total }, (_, i) => i + 1);

  return (
    <div
      className="stepper"
      role="progressbar"
      aria-valuemin={1}
      aria-valuemax={total}
      aria-valuenow={step}
    >
      {nodes.map((n) => (
        <React.Fragment key={n}>
          <span
            className={`node ${n < step ? 'is-done' : ''} ${n === step ? 'is-active' : ''}`}
          />
          {n < total && (
            <span className="trace">
              <span className="trace-fill" style={{ '--fill': n < step ? 1 : 0 }} />
            </span>
          )}
        </React.Fragment>
      ))}
    </div>
  );
}
