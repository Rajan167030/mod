import React, { useMemo, useState } from 'react';
import { WeatherDataPoint } from '../../types/api';
import { toKt, zuluTime } from './format';

interface WindChartProps {
  points: WeatherDataPoint[];
  windWarnKmh: number;
  windCritKmh: number;
}

const W = 900;
const H = 270;
const M = { top: 12, right: 60, bottom: 22, left: 34 };

/** Sustained wind and gusts (kt) against the warning / critical limits used by the alert rules. */
export const WindChart: React.FC<WindChartProps> = ({ points, windWarnKmh, windCritKmh }) => {
  const [hover, setHover] = useState<number | null>(null);

  const series = useMemo(
    () =>
      points.map((p) => ({
        t: p.forecast_timestamp,
        wind: toKt(p.wind_speed_kmh),
        gust: toKt(p.wind_gust_kmh),
      })),
    [points],
  );

  if (series.length < 2) return null;

  const warn = toKt(windWarnKmh)!;
  const crit = toKt(windCritKmh)!;
  const maxVal = Math.max(crit + 5, ...series.map((s) => Math.max(s.wind ?? 0, s.gust ?? 0)));
  const yMax = Math.ceil(maxVal / 10) * 10;

  const iw = W - M.left - M.right;
  const ih = H - M.top - M.bottom;
  const x = (i: number) => M.left + (i / (series.length - 1)) * iw;
  const y = (v: number) => M.top + ih - (v / yMax) * ih;

  const path = (key: 'wind' | 'gust') =>
    series
      .map((s, i) => (s[key] == null ? null : `${x(i).toFixed(1)},${y(s[key]!).toFixed(1)}`))
      .filter(Boolean)
      .join(' L');

  const yTicks = Array.from({ length: yMax / 10 + 1 }, (_, i) => i * 10);
  const xTicks = series.map((s, i) => ({ i, h: new Date(s.t).getUTCHours() })).filter((d) => d.h % 6 === 0);

  const onMove = (e: React.MouseEvent<SVGRectElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const ratio = (e.clientX - rect.left) / rect.width;
    setHover(Math.max(0, Math.min(series.length - 1, Math.round(ratio * (series.length - 1)))));
  };

  const h = hover != null ? series[hover] : null;

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto block" role="img" aria-label="Wind and gust forecast in knots">
        {yTicks.map((v) => (
          <g key={v}>
            <line x1={M.left} x2={W - M.right} y1={y(v)} y2={y(v)} className="stroke-slate-800" strokeWidth={1} />
            <text x={M.left - 6} y={y(v) + 3} textAnchor="end" fontSize={10} className="fill-slate-500" fontFamily="IBM Plex Mono">
              {v}
            </text>
          </g>
        ))}
        {xTicks.map(({ i, h: hr }) => (
          <text key={i} x={x(i)} y={H - 6} textAnchor="middle" fontSize={10} className="fill-slate-500" fontFamily="IBM Plex Mono">
            {String(hr).padStart(2, '0')}Z
          </text>
        ))}

        {[
          { v: warn, c: 'warn', l: 'WARN' },
          { v: crit, c: 'crit', l: 'CRIT' },
        ].map((th) => (
          <g key={th.l}>
            <line x1={M.left} x2={W - M.right} y1={y(th.v)} y2={y(th.v)} className={th.c === 'warn' ? 'stroke-warn' : 'stroke-crit'} strokeWidth={1} strokeDasharray="4 3" opacity={0.8} />
            <text x={W - M.right + 4} y={y(th.v) + 3} fontSize={10} className={th.c === 'warn' ? 'fill-warn' : 'fill-crit'} fontFamily="IBM Plex Mono">
              {th.l} {th.v}
            </text>
          </g>
        ))}

        <path d={`M${path('gust')}`} fill="none" className="stroke-slate-400" strokeWidth={1.25} strokeDasharray="2 2" />
        <path d={`M${path('wind')}`} fill="none" className="stroke-indigo-400" strokeWidth={2} />

        {h && hover != null && (
          <line x1={x(hover)} x2={x(hover)} y1={M.top} y2={M.top + ih} className="stroke-slate-600" strokeWidth={1} />
        )}
        <rect
          x={M.left}
          y={M.top}
          width={iw}
          height={ih}
          fill="transparent"
          onMouseMove={onMove}
          onMouseLeave={() => setHover(null)}
        />
      </svg>

      <div className="absolute top-1 left-10 flex items-center gap-4 text-[10px] text-slate-400 font-mono pointer-events-none">
        <span className="flex items-center gap-1.5">
          <span className="w-4 h-0.5 bg-indigo-400" /> Sustained
        </span>
        <span className="flex items-center gap-1.5">
          <span className="w-4 border-t border-dashed border-slate-400" /> Gust
        </span>
        {h && (
          <span className="text-slate-200">
            {zuluTime(h.t)} · {h.wind ?? '—'} kt G{h.gust ?? '—'}
          </span>
        )}
      </div>
    </div>
  );
};
