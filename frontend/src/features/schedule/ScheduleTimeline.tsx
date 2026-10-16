import React, { useMemo } from 'react';
import { AlertSeverity, Assignment, Resource, WeatherAlertItem } from '../../types/api';
import { EmptyState, fmtZulu, fmtZuluTime } from '../../components/ui';

interface ScheduleTimelineProps {
  resources: Resource[];
  assignments: Assignment[];
  conflictResourceIds?: string[];
  /** Hourly weather limit exceedances for the scenario's sites */
  weatherAlerts?: WeatherAlertItem[];
  horizonHours?: number;
  /** Clock for the NOW marker; defaults to real time (exercises pass simulated time) */
  nowMs?: number;
  /** Start of the visible window; defaults to the earlier of now and the first assignment */
  startMs?: number;
}

const HOUR_MS = 3600 * 1000;
const LABEL_W = 200;

type Exposure = 'CRITICAL' | 'WARNING' | null;

const sevRank: Record<AlertSeverity, number> = { CRITICAL: 2, WARNING: 1, INFO: 0 };

const cleanSite = (name: string) => name.replace(/\s*\((FICTIONAL|SYNTHETIC)\)\s*$/i, '');

const floorHour = (ms: number) => Math.floor(ms / HOUR_MS) * HOUR_MS;

export const ScheduleTimeline: React.FC<ScheduleTimelineProps> = ({
  resources,
  assignments,
  conflictResourceIds = [],
  weatherAlerts = [],
  horizonHours = 48,
  nowMs,
  startMs,
}) => {
  const clockNow = nowMs ?? Date.now();
  // Window starts at the earlier of "now" and the first assignment, on an hour boundary
  const t0 = useMemo(() => {
    if (startMs != null) return floorHour(startMs);
    const starts = assignments.map((a) => new Date(a.start_at).getTime());
    return floorHour(Math.min(clockNow, ...(starts.length ? starts : [clockNow])));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [assignments, startMs]);
  const t1 = t0 + horizonHours * HOUR_MS;

  const pct = (ms: number) => ((ms - t0) / (t1 - t0)) * 100;
  const clampPct = (ms: number) => Math.max(0, Math.min(100, pct(ms)));

  // Worst severity per hour, overall and per site
  const { hourly, sites } = useMemo(() => {
    const hourly = new Map<number, { sev: AlertSeverity; lines: string[] }>();
    const sites = new Map<string, { name: string; hours: Map<number, AlertSeverity> }>();
    for (const a of weatherAlerts) {
      if (a.severity === 'INFO' || a.variable === 'all') continue;
      const h = floorHour(new Date(a.forecast_timestamp).getTime());
      if (h < t0 || h >= t1) continue;

      const site = sites.get(a.location_id) ?? { name: cleanSite(a.location_name), hours: new Map<number, AlertSeverity>() };
      const prev = site.hours.get(h);
      if (!prev || sevRank[a.severity] > sevRank[prev]) site.hours.set(h, a.severity);
      sites.set(a.location_id, site);

      const cell = hourly.get(h) ?? { sev: a.severity, lines: [] };
      if (sevRank[a.severity] > sevRank[cell.sev]) cell.sev = a.severity;
      cell.lines.push(`${a.severity.slice(0, 4)} ${cleanSite(a.location_name)}: ${a.variable.replace('_', ' ')} ${a.observed_value}`);
      hourly.set(h, cell);
    }
    return { hourly, sites };
  }, [weatherAlerts, t0, t1]);

  // Scenarios whose tasks have sites use per-site weather: a sortie is exposed only to its own site's limits
  const perSite = assignments.some((a) => a.task_location_id);

  const exposure = (a: Assignment): Exposure => {
    const siteHours = perSite ? (a.task_location_id ? sites.get(a.task_location_id)?.hours : undefined) : undefined;
    if (perSite && !siteHours) return null;
    let worst: Exposure = null;
    for (let h = floorHour(new Date(a.start_at).getTime()); h < new Date(a.end_at).getTime(); h += HOUR_MS) {
      const s = perSite ? siteHours!.get(h) : hourly.get(h)?.sev;
      if (s === 'CRITICAL') return 'CRITICAL';
      if (s === 'WARNING') worst = 'WARNING';
    }
    return worst;
  };

  if (resources.length === 0) {
    return <EmptyState title="No resources" description="Add resources to the scenario to see the timeline." />;
  }

  const tickEvery = horizonHours <= 24 ? 2 : horizonHours <= 48 ? 4 : 6;
  const ticks = Array.from({ length: Math.floor(horizonHours / tickEvery) + 1 }, (_, i) => t0 + i * tickEvery * HOUR_MS);
  const hours = Array.from({ length: horizonHours }, (_, i) => t0 + i * HOUR_MS);
  const now = clockNow;
  const exposedCount = assignments.filter((a) => exposure(a) === 'CRITICAL').length;

  const shading = (
    <>
      {!perSite && hours.map((h) => {
        const sev = hourly.get(h)?.sev;
        if (!sev || sev === 'INFO') return null;
        return (
          <div
            key={h}
            className={`absolute inset-y-0 pointer-events-none ${sev === 'CRITICAL' ? 'bg-crit/[0.12]' : 'bg-warn/[0.07]'}`}
            style={{ left: `${pct(h)}%`, width: `${100 / horizonHours}%` }}
          />
        );
      })}
      {ticks.map((t) => (
        <div
          key={t}
          className={`absolute inset-y-0 border-l pointer-events-none ${
            new Date(t).getUTCHours() === 0 ? 'border-slate-600' : 'border-slate-800/70'
          }`}
          style={{ left: `${pct(t)}%` }}
        />
      ))}
      {now >= t0 && now <= t1 && (
        <div className="absolute inset-y-0 border-l border-indigo-400 pointer-events-none z-20" style={{ left: `${pct(now)}%` }} />
      )}
    </>
  );

  return (
    <div className="overflow-x-auto">
      <div className="min-w-[960px] text-xs">
        {/* Axis */}
        <div className="flex border-b border-slate-800 bg-slate-925 sticky top-0 z-30">
          <div style={{ width: LABEL_W }} className="shrink-0 px-3 py-1.5 text-[10px] uppercase tracking-[0.08em] text-slate-500">
            UTC
          </div>
          <div className="relative flex-1 h-7">
            {ticks.map((t) => (
              <span
                key={t}
                className="absolute top-1.5 -translate-x-1/2 font-mono text-[10px] text-slate-500 whitespace-nowrap"
                style={{ left: `${pct(t)}%` }}
              >
                {new Date(t).getUTCHours() === 0 ? fmtZulu(new Date(t).toISOString()).slice(0, 6) : fmtZuluTime(new Date(t).toISOString())}
              </span>
            ))}
            {now >= t0 && now <= t1 && (
              <span
                className="absolute bottom-0 -translate-x-1/2 px-1 bg-indigo-600 text-white font-mono text-[9px] leading-3"
                style={{ left: `${pct(now)}%` }}
              >
                NOW
              </span>
            )}
          </div>
        </div>

        {/* Weather band: one thin row per site */}
        <div className="border-b border-slate-700">
          <div className="flex items-center">
            <div style={{ width: LABEL_W }} className="shrink-0 px-3 py-1 text-[10px] uppercase tracking-[0.08em] text-slate-500">
              Weather limits
            </div>
            <div className="flex-1 text-[10px] text-slate-500 py-1">
              {sites.size === 0
                ? 'No site exceeds a limit in this window'
                : `${sites.size} site${sites.size > 1 ? 's' : ''} affected · ${exposedCount} sortie${exposedCount === 1 ? '' : 's'} inside a critical hour`}
            </div>
          </div>
          {Array.from(sites.entries()).map(([id, site]) => (
            <div key={id} className="flex items-center h-4">
              <div style={{ width: LABEL_W }} className="shrink-0 px-3 truncate text-[10px] text-slate-400">
                {site.name}
              </div>
              <div className="relative flex-1 h-full">
                {Array.from(site.hours.entries()).map(([h, sev]) => (
                  <div
                    key={h}
                    className={`absolute top-0.5 bottom-0.5 ${sev === 'CRITICAL' ? 'bg-crit' : 'bg-warn/70'}`}
                    style={{ left: `${pct(h)}%`, width: `${100 / horizonHours}%` }}
                    title={`${site.name} · ${fmtZulu(new Date(h).toISOString())} · ${sev}`}
                  />
                ))}
              </div>
            </div>
          ))}
          {sites.size > 0 && <div className="h-1" />}
        </div>

        {/* Resource rows */}
        {resources.map((res) => {
          const conflicted = conflictResourceIds.includes(res.id);
          const rows = assignments.filter((a) => a.resource_id === res.id);
          return (
            <div key={res.id} className={`flex border-b border-slate-800/70 ${conflicted ? 'bg-crit/[0.04]' : ''}`}>
              <div style={{ width: LABEL_W }} className="shrink-0 px-3 py-1.5 min-w-0">
                <div className="flex items-center gap-1.5">
                  <span className="font-mono text-slate-200 truncate">{res.name}</span>
                  {conflicted && <span className="w-1.5 h-1.5 bg-crit shrink-0" title="Has conflicts" />}
                  {res.status !== 'AVAILABLE' && (
                    <span className="font-mono text-[9px] text-warn">{res.status.slice(0, 5)}</span>
                  )}
                </div>
                <div className="text-[10px] text-slate-500 truncate">{res.resource_type.toLowerCase().replace(/_/g, ' ')}</div>
              </div>

              <div className="relative flex-1 h-11">
                {shading}
                {rows.map((a) => {
                  const s = new Date(a.start_at).getTime();
                  const e = new Date(a.end_at).getTime();
                  if (e < t0 || s > t1) return null;
                  const left = clampPct(s);
                  const width = Math.max(0.6, clampPct(e) - left);
                  const wx = exposure(a);
                  return (
                    <div
                      key={a.id}
                      className={`absolute top-1.5 bottom-1.5 z-10 px-1.5 flex flex-col justify-center overflow-hidden border ${
                        conflicted
                          ? 'bg-crit/15 border-crit text-crit'
                          : 'bg-indigo-700 border-indigo-500 text-white'
                      } ${wx === 'CRITICAL' ? 'outline outline-2 outline-crit outline-offset-1' : ''}`}
                      style={{ left: `${left}%`, width: `${width}%` }}
                      title={[
                        a.task_name ?? 'Task',
                        `${fmtZulu(a.start_at)} – ${fmtZuluTime(a.end_at)}`,
                        wx ? `Weather: inside a ${wx.toLowerCase()} hour` : '',
                      ]
                        .filter(Boolean)
                        .join('\n')}
                    >
                      <span className="truncate text-[10px] leading-tight font-medium">
                        {wx && <span className={`mr-1 font-mono ${wx === 'CRITICAL' ? 'text-crit bg-slate-950 px-0.5' : 'text-warn'}`}>WX</span>}
                        {a.task_name ?? 'Sortie'}
                      </span>
                      <span className="truncate text-[9px] leading-tight font-mono opacity-75">{fmtZuluTime(a.start_at)}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}

        {/* Legend */}
        <div className="flex flex-wrap items-center gap-4 px-3 py-2 text-[10px] text-slate-500">
          <span className="flex items-center gap-1.5">
            <span className="w-3 h-2.5 bg-indigo-700 border border-indigo-500" /> Assignment
          </span>
          <span className="flex items-center gap-1.5">
            <span className="w-3 h-2.5 bg-crit/15 border border-crit" /> Resource with conflict
          </span>
          {perSite ? (
            <span>Weather limits apply per site: a sortie is tagged only for its own site&apos;s forecast.</span>
          ) : (
            <>
              <span className="flex items-center gap-1.5">
                <span className="w-3 h-2.5 bg-crit/20" /> Critical weather hour (hard blackout)
              </span>
              <span className="flex items-center gap-1.5">
                <span className="w-3 h-2.5 bg-warn/20" /> Warning hour (penalty)
              </span>
            </>
          )}
          <span className="flex items-center gap-1.5">
            <span className="font-mono text-crit">WX</span> Sortie overlaps a limit
          </span>
        </div>
      </div>
    </div>
  );
};
