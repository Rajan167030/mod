import React, { useState } from 'react';
import { CourseOfAction } from '../../types/api';

interface TradeoffChartProps {
  courses: CourseOfAction[];
  selectedKey: string | null;
  onSelect: (key: CourseOfAction['key']) => void;
}

const W = 420;
const H = 250;
const M = { top: 16, right: 20, bottom: 36, left: 44 };

const niceMax = (v: number) => {
  if (v <= 0) return 1;
  const step = Math.pow(10, Math.floor(Math.log10(v)));
  return Math.ceil((v * 1.15) / step) * step;
};

/**
 * One point per distinct plan: total delay (x) against assignments changed (y).
 * Lower-left is better on both. Points are labelled directly, so no legend is needed.
 */
export const TradeoffChart: React.FC<TradeoffChartProps> = ({ courses, selectedKey, onSelect }) => {
  const [hover, setHover] = useState<string | null>(null);
  const pts = courses
    .filter((c) => c.metrics && !c.same_as)
    .map((c) => ({
      c,
      x: c.metrics!.total_delay_minutes,
      y: c.metrics!.reassigned + c.metrics!.retimed,
      dropped: c.metrics!.unassigned,
    }));
  if (!pts.length) return null;

  const xMax = niceMax(Math.max(...pts.map((p) => p.x)));
  const yMax = niceMax(Math.max(...pts.map((p) => p.y)));
  const iw = W - M.left - M.right;
  const ih = H - M.top - M.bottom;
  const sx = (v: number) => M.left + (v / xMax) * iw;
  const sy = (v: number) => M.top + ih - (v / yMax) * ih;
  const xTicks = [0, xMax / 2, xMax];
  const yTicks = [0, yMax / 2, yMax];
  const hovered = pts.find((p) => p.c.key === hover);

  // Nudge labels apart when points sit close together, and draw a leader line to the point
  const LINE = 13;
  const placed: { x: number; y: number }[] = [];
  const labelY: Record<string, number> = {};
  [...pts]
    .sort((a, b) => sy(a.y) - sy(b.y) || sx(a.x) - sx(b.x))
    .forEach((p) => {
      let y = sy(p.y) + 3;
      while (placed.some((q) => Math.abs(q.y - y) < LINE && Math.abs(q.x - sx(p.x)) < 150)) y += LINE;
      placed.push({ x: sx(p.x), y });
      labelY[p.c.key] = y;
    });

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto block" role="img" aria-label="Trade-off between total delay and assignments changed for each plan">
        {yTicks.map((v) => (
          <g key={`y${v}`}>
            <line x1={M.left} x2={W - M.right} y1={sy(v)} y2={sy(v)} className="stroke-slate-800" />
            <text x={M.left - 6} y={sy(v) + 3} textAnchor="end" fontSize={10} className="fill-slate-500" fontFamily="IBM Plex Mono">
              {Math.round(v)}
            </text>
          </g>
        ))}
        {xTicks.map((v) => (
          <text key={`x${v}`} x={sx(v)} y={H - M.bottom + 14} textAnchor="middle" fontSize={10} className="fill-slate-500" fontFamily="IBM Plex Mono">
            {Math.round(v)}
          </text>
        ))}
        <text x={M.left + iw / 2} y={H - 4} textAnchor="middle" fontSize={10} className="fill-slate-400">
          Total delay (min) →
        </text>
        <text x={12} y={M.top + ih / 2} textAnchor="middle" fontSize={10} className="fill-slate-400" transform={`rotate(-90 12 ${M.top + ih / 2})`}>
          Assignments changed →
        </text>
        <text x={M.left + 4} y={M.top + ih - 6} fontSize={9} className="fill-slate-600">
          better
        </text>

        {pts.map((p) => {
          const selected = p.c.key === selectedKey;
          const labelLeft = sx(p.x) > W - M.right - 110;
          return (
            <g
              key={p.c.key}
              className="cursor-pointer"
              onMouseEnter={() => setHover(p.c.key)}
              onMouseLeave={() => setHover(null)}
              onClick={() => onSelect(p.c.key)}
            >
              {/* Larger invisible hit target */}
              <circle cx={sx(p.x)} cy={sy(p.y)} r={14} fill="transparent" />
              <circle
                cx={sx(p.x)}
                cy={sy(p.y)}
                r={selected ? 7 : 5}
                className={`${p.c.recommended ? 'fill-indigo-400' : 'fill-slate-400'} stroke-slate-925`}
                strokeWidth={2}
              />
              {selected && <circle cx={sx(p.x)} cy={sy(p.y)} r={10} fill="none" className="stroke-indigo-400" strokeWidth={1} />}
              {Math.abs(labelY[p.c.key] - 3 - sy(p.y)) > 1 && (
                <line
                  x1={sx(p.x)}
                  y1={sy(p.y)}
                  x2={sx(p.x) + (labelLeft ? -10 : 10)}
                  y2={labelY[p.c.key] - 3}
                  className="stroke-slate-600"
                  strokeWidth={1}
                />
              )}
              <text
                x={sx(p.x) + (labelLeft ? -12 : 12)}
                y={labelY[p.c.key]}
                textAnchor={labelLeft ? 'end' : 'start'}
                fontSize={11}
                className={selected ? 'fill-slate-100' : 'fill-slate-300'}
              >
                {p.c.label}
                {p.dropped > 0 && <tspan className="fill-warn"> · {p.dropped} dropped</tspan>}
              </text>
            </g>
          );
        })}
      </svg>
      {hovered && (
        <div className="absolute top-1 right-1 panel px-2 py-1.5 text-[11px] pointer-events-none">
          <div className="text-slate-100">{hovered.c.label}</div>
          <div className="font-mono text-slate-400">
            {hovered.x} min delay · {hovered.y} changed · {hovered.dropped} dropped
          </div>
        </div>
      )}
    </div>
  );
};
