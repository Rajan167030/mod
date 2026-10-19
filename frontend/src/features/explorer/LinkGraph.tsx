import React, { useEffect, useMemo, useRef, useState } from 'react';
import { GraphEdge, GraphNode, ObjectType } from '../../types/api';

interface LinkGraphProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  selectedKey: string | null;
  onSelect: (node: GraphNode) => void;
}

type Pos = { x: number; y: number };

const W = 1000;
const H = 640;

// Columns give the layout a readable left-to-right story: capability ← aircraft ← task → site
const COLUMN: Record<ObjectType, number> = { capability: 0.15, aircraft: 0.38, task: 0.62, site: 0.86 };
const ORDER: ObjectType[] = ['capability', 'aircraft', 'task', 'site'];
const TOP = 34;

/**
 * Layered layout: each column is ordered by the average position of its neighbours
 * (barycentre heuristic, a few sweeps), which keeps crossing lines down, then spread evenly.
 */
const layout = (nodes: GraphNode[], edges: GraphEdge[]): Record<string, Pos> => {
  const cols: Record<string, GraphNode[]> = {};
  nodes.forEach((n) => (cols[n.type] ||= []).push(n));
  const neighbours: Record<string, string[]> = {};
  edges.forEach((e) => {
    (neighbours[e.source] ||= []).push(e.target);
    (neighbours[e.target] ||= []).push(e.source);
  });
  const pos: Record<string, Pos> = {};
  const place = (type: ObjectType) => {
    const list = cols[type] ?? [];
    list.forEach((n, i) => {
      pos[n.key] = { x: COLUMN[type] * W, y: TOP + ((i + 0.5) / list.length) * (H - TOP - 10) };
    });
  };
  ORDER.forEach(place);
  const sweep = (type: ObjectType) => {
    const list = cols[type];
    if (!list) return;
    const centre = (n: GraphNode) => {
      const ys = (neighbours[n.key] ?? []).map((k) => pos[k]?.y).filter((y): y is number => y != null);
      return ys.length ? ys.reduce((a, b) => a + b, 0) / ys.length : pos[n.key].y;
    };
    const scored = list.map((n) => ({ n, c: centre(n) }));
    scored.sort((a, b) => a.c - b.c);
    cols[type] = scored.map((x) => x.n);
    place(type);
  };
  for (let i = 0; i < 4; i++) ORDER.forEach(sweep);
  return pos;
};

const statusStroke = (status: string): string => {
  if (['CONFLICT', 'GROUNDED', 'UNAVAILABLE', 'CRITICAL', 'NONE'].includes(status)) return 'stroke-crit';
  if (['WEATHER_RISK', 'UNASSIGNED', 'WARNING', 'SINGLE_POINT', 'MAINTENANCE'].includes(status)) return 'stroke-warn';
  return 'stroke-slate-500';
};

const Shape: React.FC<{ n: GraphNode; selected: boolean; dim: boolean }> = ({ n, selected, dim }) => {
  const cls = `fill-slate-900 ${statusStroke(n.status)} ${dim ? 'opacity-25' : ''}`;
  const sw = selected ? 3 : 1.75;
  if (n.type === 'aircraft') return <rect x={-8} y={-8} width={16} height={16} className={cls} strokeWidth={sw} />;
  if (n.type === 'site') return <polygon points="0,-10 10,8 -10,8" className={cls} strokeWidth={sw} />;
  if (n.type === 'capability') return <polygon points="0,-8 8,0 0,8 -8,0" className={cls} strokeWidth={sw} />;
  const r = n.priority === 'CRITICAL' ? 8 : n.priority === 'HIGH' ? 7 : 6;
  return <circle r={r} className={cls} strokeWidth={sw} />;
};

export const LinkGraph: React.FC<LinkGraphProps> = ({ nodes, edges, selectedKey, onSelect }) => {
  const pos = useMemo(() => layout(nodes, edges), [nodes, edges]);
  const [hover, setHover] = useState<string | null>(null);
  const [view, setView] = useState({ x: 0, y: 0, k: 1 });
  const drag = useRef<{ x: number; y: number } | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const focus = hover ?? selectedKey;
  const linked = useMemo(() => {
    if (!focus) return null;
    const set = new Set([focus]);
    edges.forEach((e) => {
      if (e.source === focus) set.add(e.target);
      if (e.target === focus) set.add(e.source);
    });
    return set;
  }, [focus, edges]);

  useEffect(() => {
    const el = svgRef.current;
    if (!el) return;
    const onWheel = (ev: WheelEvent) => {
      ev.preventDefault();
      setView((v) => ({ ...v, k: Math.max(0.5, Math.min(3, v.k * (ev.deltaY < 0 ? 1.1 : 0.9))) }));
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, []);

  return (
    <div className="relative">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        className="w-full h-auto block select-none cursor-grab active:cursor-grabbing"
        role="img"
        aria-label="Link graph of aircraft, tasks, sites and capabilities"
        onMouseDown={(e) => (drag.current = { x: e.clientX, y: e.clientY })}
        onMouseMove={(e) => {
          if (!drag.current) return;
          const dx = e.clientX - drag.current.x;
          const dy = e.clientY - drag.current.y;
          drag.current = { x: e.clientX, y: e.clientY };
          setView((v) => ({ ...v, x: v.x + dx / v.k, y: v.y + dy / v.k }));
        }}
        onMouseUp={() => (drag.current = null)}
        onMouseLeave={() => (drag.current = null)}
      >
        <g transform={`translate(${W / 2} ${H / 2}) scale(${view.k}) translate(${-W / 2 + view.x} ${-H / 2 + view.y})`}>
          {(['capability', 'aircraft', 'task', 'site'] as ObjectType[]).map((t) => (
            <text key={t} x={COLUMN[t] * W} y={10} textAnchor="middle" fontSize={11} className="fill-slate-500 uppercase" letterSpacing={1}>
              {t === 'capability' ? 'capabilities' : t === 'aircraft' ? 'aircraft' : `${t}s`}
            </text>
          ))}
          {edges.map((e, i) => {
            const a = pos[e.source];
            const b = pos[e.target];
            if (!a || !b) return null;
            const on = linked ? linked.has(e.source) && linked.has(e.target) : false;
            return (
              <line
                key={i}
                x1={a.x}
                y1={a.y}
                x2={b.x}
                y2={b.y}
                className={on ? 'stroke-indigo-400' : 'stroke-slate-700'}
                strokeWidth={on ? 1.5 : 0.75}
                strokeDasharray={e.relation === 'holds' || e.relation === 'requires' ? '3 3' : undefined}
                opacity={linked && !on ? 0.15 : 0.9}
              />
            );
          })}
          {nodes.map((n) => {
            const p = pos[n.key];
            const dim = !!linked && !linked.has(n.key);
            const labelRight = n.type === 'site' || n.type === 'task';
            return (
              <g
                key={n.key}
                transform={`translate(${p.x} ${p.y})`}
                className="cursor-pointer"
                onMouseEnter={() => setHover(n.key)}
                onMouseLeave={() => setHover(null)}
                onClick={(ev) => {
                  ev.stopPropagation();
                  onSelect(n);
                }}
              >
                <circle r={14} fill="transparent" />
                <Shape n={n} selected={n.key === selectedKey} dim={dim} />
                <text
                  x={labelRight ? 13 : -13}
                  y={4}
                  textAnchor={labelRight ? 'start' : 'end'}
                  fontSize={n.type === 'task' ? 10 : 11}
                  className={`${n.key === selectedKey ? 'fill-slate-100' : 'fill-slate-300'} ${dim ? 'opacity-25' : ''}`}
                  fontFamily={n.type === 'task' || n.type === 'aircraft' ? 'IBM Plex Mono' : undefined}
                >
                  {n.label}
                </text>
              </g>
            );
          })}
        </g>
      </svg>

      {hover && (() => {
        const n = nodes.find((x) => x.key === hover);
        if (!n) return null;
        const degree = edges.filter((e) => e.source === hover || e.target === hover).length;
        return (
          <div className="absolute top-2 right-2 panel px-2.5 py-1.5 text-[11px] pointer-events-none max-w-xs">
            <div className="text-slate-100">{n.full ?? n.label}</div>
            <div className="text-slate-400 font-mono">
              {n.type} · {n.status.toLowerCase().replace('_', ' ')} · {degree} links
            </div>
          </div>
        );
      })()}

      <div className="flex flex-wrap items-center gap-3 px-3 py-1.5 border-t border-slate-800 text-[10px] text-slate-400">
        <span className="flex items-center gap-1"><svg width="10" height="10"><rect x="1" y="1" width="8" height="8" className="fill-slate-900 stroke-slate-400" /></svg> aircraft</span>
        <span className="flex items-center gap-1"><svg width="10" height="10"><circle cx="5" cy="5" r="4" className="fill-slate-900 stroke-slate-400" /></svg> task (size = priority)</span>
        <span className="flex items-center gap-1"><svg width="10" height="10"><polygon points="5,0 10,9 0,9" className="fill-slate-900 stroke-slate-400" /></svg> site</span>
        <span className="flex items-center gap-1"><svg width="10" height="10"><polygon points="5,0 10,5 5,10 0,5" className="fill-slate-900 stroke-slate-400" /></svg> capability</span>
        <span className="pl-2 border-l border-slate-800 flex items-center gap-1"><span className="w-2 h-2 border-2 border-crit" /> conflict / grounded / critical wx</span>
        <span className="flex items-center gap-1"><span className="w-2 h-2 border-2 border-warn" /> unassigned / wx risk / single source</span>
        <span className="text-slate-600">scroll to zoom · drag to pan</span>
      </div>
    </div>
  );
};
