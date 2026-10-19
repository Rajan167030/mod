import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Pause, Play } from 'lucide-react';
import { api } from '../../api/client';
import { Assignment, Location, OpsZone, Scenario, ScheduleVersion, Task, WeatherAlertItem } from '../../types/api';
import { drawZones, isActiveAt, zoneColor } from '../threats/zoneLayer';
import { useActiveTheme } from '../../components/useTheme';
import { EmptyState, ErrorState, PageHeader, Panel, Skeleton, fmtZulu, fmtZuluTime } from '../../components/ui';

const HOUR = 3600 * 1000;
const STEP_MIN = 10;
const ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services';
const BASEMAP = {
  dark: ['Canvas/World_Dark_Gray_Base', 'Elevation/World_Hillshade_Dark', 'Canvas/World_Dark_Gray_Reference'],
  light: ['Canvas/World_Light_Gray_Base', 'Elevation/World_Hillshade', 'Canvas/World_Light_Gray_Reference'],
} as const;
const SEV_COLOR: Record<string, string> = {
  CRITICAL: 'rgb(var(--st-crit))',
  WARNING: 'rgb(var(--st-warn))',
  CLEAR: 'rgb(var(--accent-400))',
};

const esc = (s: string) => s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!);
const floorHour = (ms: number) => Math.floor(ms / HOUR) * HOUR;
const code = (name?: string) => name?.match(/^[A-Z]{1,5}-\d+/)?.[0] ?? name ?? '';

type Sortie = Assignment & { start: number; end: number; site?: Location };

export const OpsMapPage: React.FC = () => {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenarioId, setScenarioId] = useState('');
  const [sites, setSites] = useState<Location[]>([]);
  const [plan, setPlan] = useState<ScheduleVersion | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [alerts, setAlerts] = useState<WeatherAlertItem[]>([]);
  const [zones, setZones] = useState<OpsZone[]>([]);
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const mapEl = useRef<HTMLDivElement>(null);
  const map = useRef<any>(null);
  const tiles = useRef<any>(null);
  const layer = useRef<any>(null);
  const fitted = useRef(false);
  const theme = useActiveTheme();

  useEffect(() => {
    api
      .getScenarios()
      .then((s) => {
        setScenarios(s);
        if (s[0]) setScenarioId(s[0].id);
      })
      .catch((e) => setError(e?.message || 'Could not load scenarios.'));
  }, []);

  useEffect(() => {
    if (!scenarioId) return;
    setLoading(true);
    setError(null);
    fitted.current = false;
    (async () => {
      try {
        const [locs, versions, ts] = await Promise.all([
          api.getLocations(scenarioId),
          api.getScenarioSchedules(scenarioId),
          api.getTasks(scenarioId),
        ]);
        setSites(locs);
        setTasks(ts);
        const active = versions.find((v) => v.status === 'APPROVED') ?? versions[0];
        const full = active ? await api.getSchedule(active.id) : null;
        setPlan(full);
        api.getWeatherAlerts(scenarioId).then((r) => setAlerts(r.alerts || [])).catch(() => setAlerts([]));
        api.getZones(scenarioId).then(setZones).catch(() => setZones([]));
      } catch (e: any) {
        setError(e?.message || 'Could not load the scenario.');
      } finally {
        setLoading(false);
      }
    })();
  }, [scenarioId]);

  const hub = useMemo(
    () => sites.find((s) => s.location_type === 'LOGISTICS_HUB') ?? sites.find((s) => s.location_type === 'BASE') ?? sites[0],
    [sites],
  );

  const sorties: Sortie[] = useMemo(() => {
    const siteById = Object.fromEntries(sites.map((s) => [s.id, s]));
    const taskSite = Object.fromEntries(tasks.map((x) => [x.id, x.location_id]));
    return (plan?.assignments ?? []).map((a) => ({
      ...a,
      start: new Date(a.start_at).getTime(),
      end: new Date(a.end_at).getTime(),
      site: siteById[a.task_location_id ?? taskSite[a.task_id] ?? ''],
    }));
  }, [plan, sites, tasks]);

  const [t0, t1] = useMemo(() => {
    if (!sorties.length) return [Date.now(), Date.now() + 24 * HOUR];
    return [floorHour(Math.min(...sorties.map((s) => s.start))), floorHour(Math.max(...sorties.map((s) => s.end))) + HOUR];
  }, [sorties]);

  // Start at "now" when it falls inside the plan, otherwise at the plan start
  useEffect(() => {
    const now = Date.now();
    setT(now >= t0 && now <= t1 ? now : t0);
  }, [t0, t1]);

  useEffect(() => {
    if (!playing) return;
    const id = window.setInterval(() => {
      setT((cur) => {
        const next = cur + STEP_MIN * 60 * 1000;
        if (next > t1) {
          setPlaying(false);
          return t1;
        }
        return next;
      });
    }, 250);
    return () => window.clearInterval(id);
  }, [playing, t1]);

  // Worst severity per site for the hour containing t
  const sevAt = useMemo(() => {
    const h = floorHour(t);
    const out: Record<string, string> = {};
    for (const a of alerts) {
      if (a.variable === 'all' || a.severity === 'INFO') continue;
      if (floorHour(new Date(a.forecast_timestamp).getTime()) !== h) continue;
      if (out[a.location_id] !== 'CRITICAL') out[a.location_id] = a.severity;
    }
    return out;
  }, [alerts, t]);

  const airborne = sorties.filter((s) => s.start <= t && t < s.end);
  const next = sorties.filter((s) => s.start > t && s.start <= t + 2 * HOUR).sort((a, b) => a.start - b.start);

  // Map setup
  useEffect(() => {
    const L = (window as any).L;
    if (!L || !mapEl.current || map.current) return;
    map.current = L.map(mapEl.current, { center: [34, 76.5], zoom: 7, zoomControl: false });
    L.control.zoom({ position: 'bottomright' }).addTo(map.current);
    L.control.scale({ position: 'bottomleft', imperial: false }).addTo(map.current);
    layer.current = L.layerGroup().addTo(map.current);
    return () => {
      map.current?.remove();
      map.current = null;
      tiles.current = null;
    };
  }, []);

  useEffect(() => {
    const L = (window as any).L;
    if (!L || !map.current) return;
    tiles.current?.remove();
    const [base, relief, labels] = BASEMAP[theme];
    const tile = (path: string, opts: object = {}) => L.tileLayer(`${ESRI}/${path}/MapServer/tile/{z}/{y}/{x}`, { maxZoom: 16, ...opts });
    tiles.current = L.layerGroup([tile(base, { attribution: 'Tiles &copy; Esri' }), tile(relief, { opacity: theme === 'dark' ? 0.55 : 0.35 }), tile(labels)]).addTo(map.current);
  }, [theme]);

  useEffect(() => {
    const L = (window as any).L;
    if (!L || !map.current || !sites.length || fitted.current) return;
    map.current.fitBounds(L.latLngBounds(sites.map((s) => [s.latitude, s.longitude])), { padding: [60, 60], maxZoom: 9 });
    fitted.current = true;
  }, [sites]);

  // Draw state at time t
  useEffect(() => {
    const L = (window as any).L;
    const g = layer.current;
    if (!L || !g) return;
    g.clearLayers();
    drawZones(L, g, zones, t);

    for (const s of sites) {
      const sev = sevAt[s.id] ?? 'CLEAR';
      const busy = airborne.filter((a) => a.site?.id === s.id).length;
      const isHub = s.id === hub?.id;
      L.marker([s.latitude, s.longitude], {
        icon: L.divIcon({
          className: '',
          iconSize: [0, 0],
          html: `<div style="position:absolute;transform:translate(-7px,-7px);display:flex;align-items:center;gap:6px;white-space:nowrap">
            <span style="width:14px;height:14px;${isHub ? '' : 'transform:rotate(45deg);'}background:rgb(var(--slate-950));border:3px solid ${SEV_COLOR[sev]}"></span>
            <span style="padding:1px 5px;background:rgb(var(--slate-950) / 0.88);border:1px solid rgb(var(--slate-800));font:11px 'IBM Plex Sans';color:rgb(var(--slate-100))">
              ${esc(s.name)}${isHub ? ' · hub' : ''}${busy ? ` · <b>${busy}</b> inbound` : ''}${sev !== 'CLEAR' ? ` · <span style="color:${SEV_COLOR[sev]}">${sev.toLowerCase()}</span>` : ''}
            </span></div>`,
        }),
      }).addTo(g);
    }

    if (!hub) return;
    for (const s of airborne) {
      if (!s.site || s.site.id === hub.id) continue;
      const a = [hub.latitude, hub.longitude];
      const b = [s.site.latitude, s.site.longitude];
      L.polyline([a, b], { color: 'rgb(var(--accent-400))', weight: 1.5, dashArray: '4 4', opacity: 0.8, interactive: false }).addTo(g);
      // Out and back: first half towards the site, second half home
      const p = (t - s.start) / (s.end - s.start);
      const f = p < 0.5 ? p * 2 : (1 - p) * 2;
      const pos = [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f];
      L.marker(pos, {
        icon: L.divIcon({
          className: '',
          iconSize: [0, 0],
          html: `<div style="position:absolute;transform:translate(-5px,-5px);display:flex;align-items:center;gap:4px;white-space:nowrap">
            <span style="width:10px;height:10px;background:rgb(var(--accent-400));border:2px solid rgb(var(--slate-950))"></span>
            <span style="font:10px 'IBM Plex Mono';color:rgb(var(--slate-100));background:rgb(var(--slate-950) / 0.8);padding:0 3px">${esc(s.resource_name ?? '')} ${esc(code(s.task_name))}</span>
          </div>`,
        }),
        interactive: false,
      }).addTo(g);
    }
  }, [sites, hub, airborne, sevAt, t, zones]);

  const pct = ((t - t0) / (t1 - t0)) * 100;
  const hours = Math.round((t1 - t0) / HOUR);

  return (
    <div className="space-y-4">
      <PageHeader
        title="Ops map"
        subtitle="The active plan on the map, through time: who is flying where, and which sites are under weather limits."
        actions={
          <select className="field max-w-[280px]" value={scenarioId} onChange={(e) => setScenarioId(e.target.value)} aria-label="Scenario">
            {scenarios.map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>
        }
      />
      {error && <ErrorState message={error} />}

      <div className="panel px-4 py-3 flex flex-wrap items-center gap-4">
        <button onClick={() => setPlaying((p) => !p)} className="btn-primary h-8 w-20" disabled={!sorties.length}>
          {playing ? <><Pause className="w-3.5 h-3.5" /> Pause</> : <><Play className="w-3.5 h-3.5" /> Play</>}
        </button>
        <div className="font-mono text-xl text-slate-100 w-24">{fmtZuluTime(new Date(t).toISOString())}</div>
        <div className="flex-1 min-w-[240px]">
          <input
            type="range"
            min={t0}
            max={t1}
            step={STEP_MIN * 60 * 1000}
            value={t}
            onChange={(e) => {
              setPlaying(false);
              setT(Number(e.target.value));
            }}
            className="w-full accent-indigo-500"
            aria-label="Time"
          />
          <div className="relative h-4 text-[10px] font-mono text-slate-500">
            {Array.from({ length: Math.min(hours, 24) + 1 }, (_, i) => {
              const step = Math.ceil(hours / 12);
              const h = t0 + i * step * HOUR;
              if (h > t1) return null;
              return (
                <span key={i} className="absolute -translate-x-1/2" style={{ left: `${((h - t0) / (t1 - t0)) * 100}%` }}>
                  {fmtZuluTime(new Date(h).toISOString()).slice(0, 2)}Z
                </span>
              );
            })}
          </div>
        </div>
        <div className="text-xs text-slate-400 font-mono">
          {fmtZulu(new Date(t0).toISOString()).slice(0, 6)} · {Math.round(pct)}% through plan
        </div>
      </div>

      <div className="grid grid-cols-1 2xl:grid-cols-12 gap-4">
        <Panel title={`Map · ${plan ? `plan v${plan.version_number}` : 'no plan'}`} className="2xl:col-span-9 h-[620px]">
          <div className="relative h-full">
            <div ref={mapEl} className="absolute inset-0" />
            {loading && <div className="absolute inset-0 p-3"><Skeleton className="h-full w-full" /></div>}
            <div className="absolute top-2 left-2 z-[1000] flex flex-wrap items-center gap-3 px-2 py-1 bg-slate-950/85 border border-slate-800 text-[10px] text-slate-400">
              <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 border-2 border-indigo-400 rotate-45" /> site</span>
              <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 border-2 border-indigo-400" /> logistics hub</span>
              <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 border-2 border-warn" /> warning hour</span>
              <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 border-2 border-crit" /> critical hour</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 bg-indigo-400" /> aircraft airborne</span>
              <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full border-2 border-crit" /> threat zone</span>
              <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 border-2 border-info" /> restricted airspace</span>
              <span className="text-slate-500">Sorties are drawn as round trips from the hub; aircraft bases are not modelled.</span>
            </div>
          </div>
        </Panel>

        <div className="2xl:col-span-3 space-y-4">
          <Panel title="Airborne" right={`${airborne.length}`}>
            {airborne.length === 0 ? (
              <EmptyState compact title="Nobody airborne" description="Drag the slider or press Play." />
            ) : (
              <ul className="text-xs divide-y divide-slate-800/60">
                {airborne.map((s) => {
                  const p = Math.round(((t - s.start) / (s.end - s.start)) * 100);
                  const sev = s.site ? sevAt[s.site.id] : undefined;
                  return (
                    <li key={s.id} className="px-3 py-2 space-y-1">
                      <div className="flex justify-between gap-2">
                        <span className="font-mono text-slate-100">{s.resource_name}</span>
                        <span className="font-mono text-slate-500">lands {fmtZuluTime(s.end_at)}</span>
                      </div>
                      <div className="text-slate-400 truncate">{s.task_name} → {s.site?.name ?? '—'}</div>
                      {s.crew_name && <div className="text-slate-500 truncate">crew: {s.crew_name}</div>}
                      <div className="h-1 bg-slate-800"><div className="h-full bg-indigo-400" style={{ width: `${p}%` }} /></div>
                      {sev && <div className={sev === 'CRITICAL' ? 'text-crit' : 'text-warn'}>{sev.toLowerCase()} weather at destination this hour</div>}
                    </li>
                  );
                })}
              </ul>
            )}
          </Panel>
          <Panel title="Threats & airspace" right={`${zones.filter((z) => isActiveAt(z, t)).length} active`}>
            {zones.length === 0 ? (
              <EmptyState compact title="No zones" />
            ) : (
              <ul className="text-xs divide-y divide-slate-800/60">
                {zones.map((z) => {
                  const on = isActiveAt(z, t);
                  return (
                    <li key={z.id} className={`px-3 py-1.5 flex items-center gap-2 ${on ? '' : 'opacity-45'}`}>
                      <span className="w-2 h-2 shrink-0" style={{ background: zoneColor(z) }} />
                      <span className="truncate flex-1 text-slate-300">{z.name}</span>
                      <span className="font-mono text-[10px] text-slate-500">{on ? 'active' : 'inactive'}</span>
                    </li>
                  );
                })}
              </ul>
            )}
          </Panel>
          <Panel title="Next 2 hours" right={`${next.length} departures`}>
            {next.length === 0 ? (
              <EmptyState compact title="No departures" />
            ) : (
              <table className="data-table w-full text-xs">
                <tbody>
                  {next.map((s) => (
                    <tr key={s.id}>
                      <td className="font-mono text-slate-400">{fmtZuluTime(s.start_at)}</td>
                      <td className="font-mono text-slate-200">{s.resource_name}</td>
                      <td className="text-slate-400 truncate max-w-[120px]">{code(s.task_name)} · {s.site?.name ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
};
