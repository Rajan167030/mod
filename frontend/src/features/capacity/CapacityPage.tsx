import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '../../api/client';
import { CapacityReport, Scenario } from '../../types/api';
import { Badge, EmptyState, ErrorState, PageHeader, Panel, SkeletonTable, StatStrip, fmtZulu, fmtZuluTime, humanize } from '../../components/ui';

const pct = (v: number | null | undefined) => (v == null ? '—' : `${Math.round(v * 100)}%`);

/** One bar per value; amber past 85% so the stretched resources stand out, with the number beside it. */
const UseBar: React.FC<{ value: number | null }> = ({ value }) => {
  const v = Math.min(1, value ?? 0);
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-24 bg-slate-800 rounded-sm overflow-hidden">
        <div className={`h-full rounded-sm ${v >= 0.85 ? 'bg-warn' : 'bg-indigo-400'}`} style={{ width: `${v * 100}%` }} />
      </div>
      <span className={`font-mono ${v >= 0.85 ? 'text-warn' : 'text-slate-300'}`}>{pct(value)}</span>
    </div>
  );
};

/** Aircraft free in each hour of the planning horizon: bars on one axis, hover for the hour's breakdown. */
const FreeByHour: React.FC<{ data: CapacityReport['hourly']; total: number }> = ({ data, total }) => {
  const [hover, setHover] = useState<number | null>(null);
  const W = 960, H = 200, L = 32, B = 26, T = 12;
  const max = Math.max(1, total);
  const bw = (W - L - 8) / Math.max(1, data.length);
  const y = (v: number) => T + (H - T - B) * (1 - v / max);
  const ticks = [0, Math.round(max / 2), max];
  const now = Date.now();
  const nowIdx = data.findIndex((d) => {
    const t = new Date(d.hour).getTime();
    return t <= now && now < t + 3600e3;
  });
  const h = hover != null ? data[hover] : null;
  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" role="img" aria-label="Aircraft free in each hour of the plan">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={L} x2={W - 8} y1={y(t)} y2={y(t)} stroke="rgb(var(--slate-800))" strokeWidth="1" />
            <text x={L - 6} y={y(t) + 3} textAnchor="end" fontSize="10" fill="rgb(var(--slate-500))" fontFamily="IBM Plex Mono">{t}</text>
          </g>
        ))}
        {data.map((d, i) => {
          const x = L + i * bw;
          const top = y(d.free);
          const height = Math.max(0, H - B - top);
          return (
            <g key={d.hour} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <rect x={x} y={T} width={bw} height={H - T - B} fill="transparent" />
              {height > 0 && (
                <path
                  d={`M${x + 1} ${H - B} V${top + 4} q0 -4 4 -4 H${x + bw - 5} q4 0 4 4 V${H - B} Z`}
                  fill={hover === i ? 'rgb(var(--accent-400))' : 'rgb(var(--accent-400) / 0.75)'}
                />
              )}
              {i % Math.ceil(data.length / 12) === 0 && (
                <text x={x + bw / 2} y={H - 8} textAnchor="middle" fontSize="10" fill="rgb(var(--slate-500))" fontFamily="IBM Plex Mono">
                  {fmtZuluTime(d.hour).slice(0, 2)}Z
                </text>
              )}
            </g>
          );
        })}
        <line x1={L} x2={W - 8} y1={H - B} y2={H - B} stroke="rgb(var(--slate-700))" strokeWidth="1" />
        {nowIdx >= 0 && (
          <g>
            <line x1={L + nowIdx * bw + bw / 2} x2={L + nowIdx * bw + bw / 2} y1={T} y2={H - B} stroke="rgb(var(--slate-300))" strokeDasharray="3 3" />
            <text x={L + nowIdx * bw + bw / 2 + 4} y={T + 10} fontSize="10" fill="rgb(var(--slate-300))">now</text>
          </g>
        )}
      </svg>
      {h && (
        <div
          className="absolute top-0 pointer-events-none bg-slate-950 border border-slate-700 px-2 py-1.5 text-[11px] shadow-lg"
          style={{ left: `${Math.min(80, ((L + (hover! + 1) * bw) / W) * 100)}%` }}
        >
          <div className="font-mono text-slate-100">{fmtZulu(h.hour)}</div>
          <div className="text-slate-300">{h.free} of {total} aircraft free</div>
          {Object.entries(h.by_type).map(([k, v]) => (
            <div key={k} className="text-slate-500">{humanize(k)}: {v}</div>
          ))}
        </div>
      )}
    </div>
  );
};

export const CapacityPage: React.FC = () => {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenarioId, setScenarioId] = useState('');
  const [cap, setCap] = useState<CapacityReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.getScenarios().then((s) => {
      setScenarios(s);
      if (s[0]) setScenarioId(s.find((x) => x.name.startsWith('Northern Sector'))?.id ?? s[0].id);
    }).catch((e) => setError(e?.message || 'Could not load scenarios.'));
  }, []);

  const load = useCallback(async () => {
    if (!scenarioId) return;
    setError(null);
    setCap(null);
    try {
      setCap(await api.getCapacity(scenarioId));
    } catch (e: any) {
      setError(e?.message || 'Could not load capacity.');
    }
  }, [scenarioId]);
  useEffect(() => { load(); }, [load]);

  const s = cap?.summary;
  const minFree = useMemo(() => (cap?.hourly.length ? Math.min(...cap.hourly.map((h) => h.free)) : null), [cap]);

  return (
    <div className="space-y-4">
      <PageHeader
        title="Capacity"
        subtitle="What the force has and how much the active plan uses: flying hours available, planned and spare, by aircraft and by type, aircraft free hour by hour, crew duty and stores left."
        actions={
          <>
            <select className="field max-w-[280px]" value={scenarioId} onChange={(e) => setScenarioId(e.target.value)} aria-label="Scenario">
              {scenarios.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
            </select>
            <button onClick={load} className="btn-secondary">Refresh</button>
          </>
        }
      />
      {error && <ErrorState message={error} onRetry={load} />}

      <StatStrip
        loading={!cap && !error}
        items={[
          { label: 'Aircraft serviceable', value: s ? `${s.serviceable}/${s.aircraft}` : '—', tone: s && s.serviceable < s.aircraft ? 'warn' : 'ok' },
          { label: 'Flying hours available', value: s?.available_hours ?? '—', hint: cap?.horizon ? `over ${cap.horizon.hours} h, after maintenance` : undefined },
          { label: 'Planned', value: s?.planned_hours ?? '—', hint: `${pct(s?.utilisation)} of available` },
          { label: 'Spare hours', value: s?.spare_hours ?? '—', tone: 'ok', hint: 'room for new missions' },
          { label: 'Crew duty left', value: cap?.crews ? `${cap.crews.duty_left_hours} h` : '—', hint: cap?.crews ? `${cap.crews.available}/${cap.crews.total} crews · ${cap.crews.near_limit} near limit` : 'no crews modelled', tone: cap?.crews?.near_limit ? 'warn' : 'default' },
          { label: 'Missions planned', value: s ? `${s.tasks_planned}/${s.tasks}` : '—', tone: s && s.tasks_planned < s.tasks ? 'warn' : 'ok' },
        ]}
      />

      {cap && !cap.horizon ? (
        <EmptyState title="No missions in this scenario" description="Add missions to see capacity against them." />
      ) : (
        <>
          <Panel
            title="Aircraft free, hour by hour"
            right={cap?.horizon ? `${fmtZulu(cap.horizon.start)} → ${fmtZulu(cap.horizon.end)} · lowest ${minFree ?? '—'} free · plan v${cap.plan_version ?? '—'}` : undefined}
          >
            {cap ? <div className="p-3"><FreeByHour data={cap.hourly} total={cap.summary?.serviceable ?? 0} /></div> : <SkeletonTable rows={4} cols={1} />}
          </Panel>

          <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
            <Panel title="By aircraft type" className="xl:col-span-2" right="most used first">
              {!cap ? <SkeletonTable rows={5} cols={6} /> : (
                <div className="overflow-x-auto">
                  <table className="data-table w-full text-xs">
                    <thead>
                      <tr><th>Type</th><th className="text-right">Aircraft</th><th className="text-right">Free now</th><th className="text-right">Available h</th><th className="text-right">Planned h</th><th className="text-right">Spare h</th><th>Use</th></tr>
                    </thead>
                    <tbody>
                      {cap.types.map((t) => (
                        <tr key={t.type}>
                          <td className="text-slate-200">{humanize(t.type)}</td>
                          <td className="text-right font-mono">{t.serviceable}/{t.aircraft}</td>
                          <td className="text-right font-mono">{t.free_now}</td>
                          <td className="text-right font-mono">{t.available_hours}</td>
                          <td className="text-right font-mono">{t.planned_hours}</td>
                          <td className="text-right font-mono text-ok">{t.spare_hours}</td>
                          <td><UseBar value={t.utilisation} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Panel>
            <Panel title="Stores after the plan">
              {!cap ? <SkeletonTable rows={4} cols={3} /> : cap.stores.length === 0 ? <EmptyState compact title="No stores held" /> : (
                <table className="data-table w-full text-xs">
                  <thead><tr><th>Store</th><th className="text-right">Held</th><th className="text-right">Planned</th><th className="text-right">Left</th></tr></thead>
                  <tbody>
                    {cap.stores.map((st) => (
                      <tr key={st.store_type}>
                        <td className="text-slate-200">{st.name}</td>
                        <td className="text-right font-mono">{st.held}</td>
                        <td className="text-right font-mono">{st.planned}</td>
                        <td className={`text-right font-mono ${st.left <= 0 ? 'text-crit' : st.left <= 1 ? 'text-warn' : 'text-ok'}`}>{st.left} {st.unit}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Panel>
          </div>

          <Panel title="By aircraft" right="spare hours = available after maintenance minus planned flying">
            {!cap ? <SkeletonTable rows={8} cols={7} /> : (
              <div className="overflow-x-auto">
                <table className="data-table w-full text-xs">
                  <thead>
                    <tr><th>Aircraft</th><th>Status</th><th className="text-right">Sorties</th><th className="text-right">Available h</th><th className="text-right">Planned h</th><th className="text-right">Spare h</th><th>Use</th><th>Next free (1 h+)</th></tr>
                  </thead>
                  <tbody>
                    {cap.aircraft.map((a) => (
                      <tr key={a.id}>
                        <td>
                          <div className="font-mono text-slate-100">{a.name}</div>
                          <div className="text-slate-500">{a.model ?? humanize(a.type)}{a.maintenance_hours ? ` · ${a.maintenance_hours} h maintenance` : ''}</div>
                        </td>
                        <td><Badge status={a.status} /></td>
                        <td className="text-right font-mono">{a.sorties}</td>
                        <td className="text-right font-mono">{a.available_hours}</td>
                        <td className="text-right font-mono">{a.planned_hours}</td>
                        <td className="text-right font-mono text-ok">{a.spare_hours}</td>
                        <td><UseBar value={a.utilisation} /></td>
                        <td className="font-mono text-slate-400 whitespace-nowrap">{a.next_free_at ? fmtZulu(a.next_free_at) : '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
        </>
      )}
    </div>
  );
};
