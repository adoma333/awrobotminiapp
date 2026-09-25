import React, { useMemo, useState } from 'react';
import PageHead from './PageHead';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts';

const DAILY_RATE = 0.02; // 2% يوميًا (مركّب) — للمحاكاة فقط

function buildSeries(capital, days) {
  const points = [];
  let value = capital;
  for (let d = 0; d <= days; d++) {
    points.push({ day: d, value: Math.round(value * 100) / 100 });
    value *= 1 + DAILY_RATE;
  }
  return points;
}

export default function InterestCalculator({ t, lang, onBack }) {
  const [capital, setCapital] = useState('1000');
  const [days, setDays] = useState('30');

  const cap = Math.max(0, Number(capital) || 0);
  const d = Math.max(1, Math.min(3650, Math.round(Number(days)) || 0));
  const series = useMemo(() => buildSeries(cap, d), [cap, d]);
  const final = series[series.length - 1]?.value ?? cap;
  const profit = final - cap;

  const nf = (n) => new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 }).format(n);

  return (
    <section className="dash">
      <PageHead t={t} title={t.calcTitle} onBack={onBack} />

      <div className="section">
        <p className="sub">{t.calcSub}</p>

        <div className="calc-inputs">
          <label className="field">
            <span>{t.calcCapital}</span>
            <input inputMode="decimal" value={capital} onChange={(e) => setCapital(e.target.value.replace(/[^\d.]/g, ''))} />
          </label>
          <label className="field">
            <span>{t.calcDays}</span>
            <input inputMode="numeric" value={days} onChange={(e) => setDays(e.target.value.replace(/[^\d]/g, ''))} />
          </label>
        </div>

        <div className="calc-result">
          <div>
            <span className="row-label">{t.calcFinal}</span>
            <strong dir="ltr">{nf(final)}</strong>
          </div>
          <div>
            <span className="row-label">{t.calcProfit}</span>
            <strong dir="ltr" className="up">+{nf(profit)}</strong>
          </div>
        </div>

        <div className="calc-chart">
          <ResponsiveContainer width="100%" height={200}>
            <LineChart data={series} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.08)" />
              <XAxis dataKey="day" tick={{ fill: '#8c8378', fontSize: 11 }} tickLine={false} axisLine={false} />
              <YAxis tick={{ fill: '#8c8378', fontSize: 11 }} tickLine={false} axisLine={false} width={54} />
              <Tooltip
                contentStyle={{ background: '#100e0c', border: '1px solid rgba(255,138,0,0.28)', borderRadius: 10, fontSize: 12 }}
                labelFormatter={(day) => `${t.calcDay} ${day}`}
                formatter={(value) => [nf(value), t.calcBalance]}
              />
              <Line type="monotone" dataKey="value" stroke="#ff8a00" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>

        <p className="note warn calc-disclaimer" role="note">{t.calcDisclaimer}</p>
      </div>
    </section>
  );
}
