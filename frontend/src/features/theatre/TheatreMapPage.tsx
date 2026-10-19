import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Crosshair, Search, X } from 'lucide-react';
import { api } from '../../api/client';
import {
  Location, OpsZone, RefAircraftType, RefAirfield, RefAirspace, RefMetarResponse, RefMetarStation, Scenario, ScheduleVersion,
} from '../../types/api';
import { useActiveTheme } from '../../components/useTheme';
import { Badge, ErrorState, PageHeader, StatStrip, fmtZulu, fmtZuluTime } from '../../components/ui';
import { drawZones } from '../threats/zoneLayer';

const ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services';
const BASEMAPS = {
  terrain: {
    dark: ['Canvas/World_Dark_Gray_Base', 'Elevation/World_Hillshade_Dark', 'Canvas/World_Dark_Gray_Reference'],
    light: ['Canvas/World_Light_Gray_Base', 'Elevation/World_Hillshade', 'Canvas/World_Light_Gray_Reference'],
  },
  satellite: {
    dark: ['World_Imagery', 'Reference/World_Boundaries_and_Places'],
    light: ['World_Imagery', 'Reference/World_Boundaries_and_Places'],
  },
} as const;

const CAT_COLOR: Record<string, string> = {
  VFR: 'rgb(var(--st-ok))',
  MVFR: 'rgb(var(--st-info))',
  IFR: 'rgb(var(--st-crit))',
  LIFR: '#c026d3',
};
const AREA_COLOR: Record<string, string> = {
  Prohibited: 'rgb(var(--st-crit))',
  Danger: 'rgb(var(--st-warn))',
  Restricted: '#8b5cf6',
};
const PRIO_COLOR: Record<string, string> = {
  CRITICAL: 'rgb(var(--st-crit))',
  HIGH: 'rgb(var(--st-warn))',
  MEDIUM: 'rgb(var(--accent-400))',
  LOW: 'rgb(var(--slate-400))',
};
const FIELD_RADIUS: Record<string, number> = { large_airport: 5.5, medium_airport: 4.5, small_airport: 3.5, heliport: 2.5, seaplane_base: 2.5 };
const TYPE_LABEL: Record<string, string> = {
  large_airport: 'Large airport', medium_airport: 'Airport', small_airport: 'Airstrip', heliport: 'Heliport', seaplane_base: 'Seaplane base',
};

/** Canvas cannot read CSS variables, so turn "rgb(var(--x))" into the colour the theme currently defines. */
const resolve = (c: string) =>
  c.replace(/rgb\(var\((--[\w-]+)\)\)/g, (_, name) => {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v ? `rgb(${v.split(/\s+/).join(',')})` : '#888';
  });
const esc = (s: string) => s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!);
const km = (a: [number, number], b: [number, number]) => {
  const r = Math.PI / 180;
  const d = Math.sin(((b[0] - a[0]) * r) / 2) ** 2 + Math.cos(a[0] * r) * Math.cos(b[0] * r) * Math.sin(((b[1] - a[1]) * r) / 2) ** 2;
  return 2 * 6371 * Math.asin(Math.sqrt(d));
};
const inPolygon = (p: [number, number], poly: [number, number][]) => {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [yi, xi] = poly[i];
    const [yj, xj] = poly[j];
    if (yi > p[0] !== yj > p[0] && p[1] < ((xj - xi) * (p[0] - yi)) / (yj - yi || 1e-12) + xi) inside = !inside;
  }
  return inside;
};
/** A gentle curve between two points, so sorties read as flight paths instead of straight rules. */
const arc = (a: [number, number], b: [number, number], n = 24): [number, number][] => {
  const mid: [number, number] = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
  const ctrl: [number, number] = [mid[0] + (b[1] - a[1]) * 0.18, mid[1] - (b[0] - a[0]) * 0.18];
  return Array.from({ length: n + 1 }, (_, i) => {
    const t = i / n;
    return [
      (1 - t) ** 2 * a[0] + 2 * (1 - t) * t * ctrl[0] + t ** 2 * b[0],
      (1 - t) ** 2 * a[1] + 2 * (1 - t) * t * ctrl[1] + t ** 2 * b[1],
    ];
  });
};

type Layers = { airfields: boolean; weather: boolean; airspace: boolean; scenario: boolean };
type Picked =
  | { kind: 'airfield'; field: RefAirfield }
  | { kind: 'area'; area: RefAirspace }
  | null;

export const TheatreMapPage: React.FC = () => {
  const [fields, setFields] = useState<RefAirfield[]>([]);
  const [areas, setAreas] = useState<RefAirspace[]>([]);
  const [types, setTypes] = useState<RefAircraftType[]>([]);
  const [metar, setMetar] = useState<RefMetarResponse | null>(null);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenarioId, setScenarioId] = useState('');
  const [sites, setSites] = useState<Location[]>([]);
  const [zones, setZones] = useState<OpsZone[]>([]);
  const [plan, setPlan] = useState<ScheduleVersion | null>(null);
  const [layers, setLayers] = useState<Layers>({ airfields: true, weather: true, airspace: true, scenario: true });
  const [basemap, setBasemap] = useState<'terrain' | 'satellite'>('terrain');
  const [query, setQuery] = useState('');
  const [picked, setPicked] = useState<Picked>(null);
  const [error, setError] = useState<string | null>(null);
  const [zoom, setZoom] = useState(5);

  const mapEl = useRef<HTMLDivElement>(null);
  const map = useRef<any>(null);
  const tiles = useRef<any>(null);
  const groups = useRef<Record<keyof Layers, any>>({} as any);
  // Animated sortie arcs need SVG paths; everything else draws on canvas for speed
  const svg = useRef<any>(null);
  const theme = useActiveTheme();

  // Reference data (national) and the scenario list
  useEffect(() => {
    Promise.all([api.getRefAirfields(), api.getRefAirspace(), api.getRefAircraftTypes()])
      .then(([f, a, t]) => {
        setFields(f);
        setAreas(a);
        setTypes(t);
      })
      .catch((e) => setError(e?.message || 'Could not load the reference data.'));
    api.getRefMetar().then(setMetar).catch(() => setMetar(null));
    api.getScenarios().then((s) => {
      setScenarios(s);
      const northern = s.find((x) => x.name.startsWith('Northern Sector'));
      setScenarioId((northern ?? s[0])?.id ?? '');
    }).catch(() => undefined);
  }, []);

  // Scenario overlay
  useEffect(() => {
    if (!scenarioId) return;
    setPlan(null);
    (async () => {
      try {
        const [locs, z, versions] = await Promise.all([api.getLocations(scenarioId), api.getZones(scenarioId), api.getScenarioSchedules(scenarioId)]);
        setSites(locs);
        setZones(z);
        const active = versions.filter((v) => v.status === 'APPROVED').sort((a, b) => b.version_number - a.version_number)[0];
        setPlan(active ? await api.getSchedule(active.id) : null);
      } catch {
        setSites([]);
        setZones([]);
      }
    })();
  }, [scenarioId]);

  // Map setup
  useEffect(() => {
    const L = (window as any).L;
    if (!L || !mapEl.current || map.current) return;
    map.current = L.map(mapEl.current, { center: [23.5, 80], zoom: 5, zoomControl: false, preferCanvas: true, worldCopyJump: true });
    svg.current = L.svg({ padding: 0.5 });
    map.current.on('zoomend', () => setZoom(map.current.getZoom()));
    L.control.zoom({ position: 'bottomright' }).addTo(map.current);
    L.control.scale({ position: 'bottomright', imperial: false }).addTo(map.current);
    (['airspace', 'airfields', 'weather', 'scenario'] as (keyof Layers)[]).forEach((k) => {
      groups.current[k] = L.layerGroup().addTo(map.current);
    });
    return () => {
      map.current?.remove();
      map.current = null;
    };
  }, []);

  useEffect(() => {
    const L = (window as any).L;
    if (!L || !map.current) return;
    tiles.current?.remove();
    const paths = BASEMAPS[basemap][theme];
    const tile = (path: string, opts: object = {}) => L.tileLayer(`${ESRI}/${path}/MapServer/tile/{z}/{y}/{x}`, { maxZoom: 17, ...opts });
    const list = paths.map((p, i) =>
      tile(p, i === 0 ? { attribution: 'Tiles &copy; Esri' } : p.includes('Hillshade') ? { opacity: theme === 'dark' ? 0.55 : 0.35 } : {}),
    );
    tiles.current = L.layerGroup(list).addTo(map.current);
    tiles.current.eachLayer((l: any) => l.bringToBack?.());
  }, [theme, basemap]);

  // Airspace layer
  useEffect(() => {
    const L = (window as any).L;
    const g = groups.current.airspace;
    if (!L || !g) return;
    g.clearLayers();
    if (!layers.airspace) return;
    for (const a of areas) {
      const color = resolve(AREA_COLOR[a.type]);
      const style = { color, weight: 1.2, opacity: 0.85, fillColor: color, fillOpacity: a.type === 'Prohibited' ? 0.28 : 0.12, dashArray: a.type === 'Restricted' ? '4 3' : undefined };
      const shape = a.polygon ? L.polygon(a.polygon, style) : a.center && a.radius_km ? L.circle(a.center, { ...style, radius: a.radius_km * 1000 }) : null;
      if (!shape) continue;
      shape.bindTooltip(`<b>${esc(a.designator)}</b> ${esc(a.name)}<br>${a.type} · ${esc(a.vertical_limits || 'limits n/a')}`, { sticky: true });
      shape.on('click', () => setPicked({ kind: 'area', area: a }));
      shape.addTo(g);
    }
  }, [areas, layers.airspace, theme]);

  // Airfield layer
  useEffect(() => {
    const L = (window as any).L;
    const g = groups.current.airfields;
    if (!L || !g) return;
    g.clearLayers();
    if (!layers.airfields) return;
    for (const f of fields) {
      const heli = f.type === 'heliport';
      L.circleMarker([f.latitude, f.longitude], {
        radius: FIELD_RADIUS[f.type] ?? 3,
        color: resolve(heli ? 'rgb(var(--slate-400))' : 'rgb(var(--accent-400))'),
        weight: heli ? 1 : 1.5,
        fillColor: resolve('rgb(var(--accent-400))'),
        fillOpacity: heli ? 0 : 0.55,
      })
        .bindTooltip(`${esc(f.name)}${f.icao ? ` · <b>${esc(f.icao)}</b>` : ''}${f.elevation_m != null ? ` · ${Math.round(f.elevation_m)} m` : ''}`, { direction: 'top' })
        .on('click', () => setPicked({ kind: 'airfield', field: f }))
        .addTo(g);
    }
  }, [fields, layers.airfields, theme]);

  // Live weather layer
  useEffect(() => {
    const L = (window as any).L;
    const g = groups.current.weather;
    if (!L || !g) return;
    g.clearLayers();
    if (!layers.weather || !metar) return;
    for (const s of metar.stations) {
      if (s.latitude == null || s.longitude == null) continue;
      const color = resolve(CAT_COLOR[s.flight_category ?? ''] ?? 'rgb(var(--slate-400))');
      L.circleMarker([s.latitude, s.longitude], { radius: 8, color, weight: 2.5, fillColor: color, fillOpacity: 0.18 })
        .bindTooltip(`<b>${esc(s.icao)}</b> ${s.flight_category ?? ''}<br><span style="font-family:'IBM Plex Mono'">${esc(s.raw_metar ?? '')}</span>`, { direction: 'top' })
        .on('click', () => {
          const f = fields.find((x) => x.icao === s.icao);
          if (f) setPicked({ kind: 'airfield', field: f });
        })
        .addTo(g);
    }
  }, [metar, fields, layers.weather, theme]);

  // Scenario layer: zones, sites and the approved plan's sorties as flight arcs from the hub
  const hub = useMemo(
    () => sites.find((s) => s.location_type === 'LOGISTICS_HUB') ?? sites.find((s) => s.location_type === 'BASE') ?? sites[0],
    [sites],
  );
  useEffect(() => {
    const L = (window as any).L;
    const g = groups.current.scenario;
    if (!L || !g) return;
    g.clearLayers();
    if (!layers.scenario) return;
    drawZones(L, g, zones, Date.now(), undefined, svg.current);
    const siteById = Object.fromEntries(sites.map((s) => [s.id, s]));
    if (hub) {
      const counts: Record<string, number> = {};
      for (const a of plan?.assignments ?? []) {
        const s = siteById[a.task_location_id ?? ''];
        if (!s || s.id === hub.id) continue;
        counts[s.id] = (counts[s.id] ?? 0) + 1;
        const curve = arc([hub.latitude, hub.longitude], [s.latitude, s.longitude]);
        L.polyline(curve, { color: PRIO_COLOR[a.priority ?? 'MEDIUM'], weight: 2, opacity: 0.9, className: 'theatre-sortie', renderer: svg.current })
          .bindTooltip(`${esc(a.task_name ?? 'Sortie')}<br>${esc(a.resource_name ?? '')}${a.crew_name ? ` · ${esc(a.crew_name)}` : ''} · ${fmtZuluTime(a.start_at)}`, { sticky: true })
          .addTo(g);
      }
    }
    for (const s of sites) {
      const isHub = s.id === hub?.id;
      L.marker([s.latitude, s.longitude], {
        icon: L.divIcon({
          className: '',
          iconSize: [0, 0],
          html: `<div style="position:absolute;transform:translate(-6px,-6px);display:flex;align-items:center;gap:5px;white-space:nowrap">
            <span style="width:12px;height:12px;${isHub ? '' : 'transform:rotate(45deg);'}background:rgb(var(--slate-950));border:2.5px solid rgb(var(--accent-400))"></span>
            ${zoom >= 7 || isHub ? `<span style="padding:0 4px;background:rgb(var(--slate-950) / 0.85);border:1px solid rgb(var(--slate-800));font:10px 'IBM Plex Sans';color:rgb(var(--slate-100))">${esc(s.name)}${isHub ? ' · hub' : ''}</span>` : ''}</div>`,
        }),
        interactive: false,
      }).addTo(g);
    }
  }, [zones, sites, plan, hub, layers.scenario, zoom]);

  const fitScenario = () => {
    const L = (window as any).L;
    if (!L || !map.current || !sites.length) return;
    map.current.fitBounds(L.latLngBounds(sites.map((s) => [s.latitude, s.longitude])), { padding: [60, 60], maxZoom: 9 });
  };
  const fitIndia = () => map.current?.setView([23.5, 80], 5);
  // Start on the scenario once its sites arrive
  const framed = useRef('');
  useEffect(() => {
    if (sites.length && framed.current !== scenarioId) {
      framed.current = scenarioId;
      fitScenario();
    }
  }, [sites, scenarioId]); // eslint-disable-line react-hooks/exhaustive-deps

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (q.length < 2) return [];
    return fields
      .filter((f) => f.name.toLowerCase().includes(q) || f.icao?.toLowerCase() === q || f.icao?.toLowerCase().startsWith(q) || f.municipality?.toLowerCase().includes(q))
      .slice(0, 8);
  }, [query, fields]);

  const flyTo = (f: RefAirfield) => {
    map.current?.flyTo([f.latitude, f.longitude], 10, { duration: 1.2 });
    setPicked({ kind: 'airfield', field: f });
    setQuery('');
  };

  const metarFor = (icao?: string | null): RefMetarStation | undefined => (icao ? metar?.stations.find((s) => s.icao === icao) : undefined);
  const cats = useMemo(() => {
    const c: Record<string, number> = {};
    metar?.stations.forEach((s) => { if (s.flight_category) c[s.flight_category] = (c[s.flight_category] ?? 0) + 1; });
    return c;
  }, [metar]);

  return (
    <div className="space-y-4">
      <style>{`
        .theatre-sortie { stroke-dasharray: 6 8; animation: theatre-flow 1.6s linear infinite; }
        @keyframes theatre-flow { to { stroke-dashoffset: -28; } }
        @media (prefers-reduced-motion: reduce) { .theatre-sortie { animation: none; } }
        .theatre-glass { background: rgb(var(--slate-950) / 0.86); backdrop-filter: blur(6px); border: 1px solid rgb(var(--slate-800)); }
      `}</style>
      <PageHeader
        title="Theatre map"
        subtitle="Every Indian airfield, the AIP's prohibited, restricted and danger areas, live weather at reporting stations, and the selected scenario's plan, on one map."
        actions={
          <select className="field max-w-[280px]" value={scenarioId} onChange={(e) => setScenarioId(e.target.value)} aria-label="Scenario overlay">
            {scenarios.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        }
      />
      {error && <ErrorState message={error} />}

      <StatStrip
        loading={!fields.length}
        items={[
          { label: 'Airfields & heliports', value: fields.length, hint: 'OurAirports' },
          { label: 'AIP areas', value: areas.length, hint: `${areas.filter((a) => a.type === 'Prohibited').length} prohibited · ${areas.filter((a) => a.type === 'Danger').length} danger` },
          { label: 'Stations reporting', value: metar?.stations.length ?? '—', hint: metar ? `${metar.source === 'live' ? 'live' : 'saved snapshot'} · ${fmtZulu(metar.fetched_at)}` : 'loading', tone: metar?.source === 'live' ? 'ok' : 'warn' },
          { label: 'Below VFR now', value: (cats.MVFR ?? 0) + (cats.IFR ?? 0) + (cats.LIFR ?? 0), hint: `${cats.IFR ?? 0} IFR · ${cats.LIFR ?? 0} LIFR`, tone: (cats.IFR ?? 0) + (cats.LIFR ?? 0) ? 'crit' : 'default' },
          { label: 'Scenario sorties', value: plan?.assignments.length ?? 0, hint: plan ? `plan v${plan.version_number}` : 'no approved plan' },
          { label: 'Scenario zones', value: zones.length },
        ]}
      />

      <div className="panel relative h-[720px] overflow-hidden">
        <div ref={mapEl} className="absolute inset-0" />

        {/* Layers and search */}
        <div className="absolute top-3 left-3 z-[1000] w-64 max-w-[calc(100%-1.5rem)] theatre-glass text-xs">
          <div className="p-2 border-b border-slate-800 relative">
            <div className="flex items-center gap-2 px-2 h-8 border border-slate-700 bg-slate-950">
              <Search className="w-3.5 h-3.5 text-slate-500" />
              <input
                className="flex-1 min-w-0 bg-transparent outline-none text-slate-100 placeholder:text-slate-500"
                placeholder="Airfield, ICAO or town"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                aria-label="Search airfields"
              />
            </div>
            {results.length > 0 && (
              <ul className="absolute left-2 right-2 top-11 theatre-glass max-h-64 overflow-y-auto">
                {results.map((f) => (
                  <li key={f.ident}>
                    <button onClick={() => flyTo(f)} className="w-full text-left px-2 py-1.5 hover:bg-slate-800">
                      <span className="text-slate-100">{f.name}</span>
                      <span className="font-mono text-slate-500"> {f.icao ?? f.ident}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="p-2 space-y-1">
            {([
              ['airfields', 'Airfields & heliports', fields.length, <span key="a" className="w-2.5 h-2.5 rounded-full bg-indigo-400" />],
              ['weather', `Weather (${metar?.source ?? '…'})`, metar?.stations.length ?? 0, <span key="w" className="w-2.5 h-2.5 rounded-full border-2 border-ok" />],
              ['airspace', 'AIP airspace (ENR 5.1)', areas.length, <span key="s" className="w-2.5 h-2.5 border border-crit bg-crit/30" />],
              ['scenario', 'Scenario plan & zones', plan?.assignments.length ?? 0, <span key="p" className="w-3 h-0.5 bg-warn" />],
            ] as [keyof Layers, string, number, React.ReactNode][]).map(([k, label, n, swatch]) => (
              <label key={k} className="flex items-center gap-2 px-1 py-1 cursor-pointer hover:bg-slate-800/60">
                <input type="checkbox" className="accent-indigo-500" checked={layers[k]} onChange={(e) => setLayers((l) => ({ ...l, [k]: e.target.checked }))} />
                {swatch}
                <span className="flex-1 text-slate-200">{label}</span>
                <span className="font-mono text-slate-500">{n}</span>
              </label>
            ))}
          </div>
          <div className="p-2 border-t border-slate-800 flex gap-1">
            {(['terrain', 'satellite'] as const).map((b) => (
              <button key={b} onClick={() => setBasemap(b)} className={`flex-1 h-7 border ${basemap === b ? 'border-indigo-500 text-slate-100' : 'border-slate-800 text-slate-500'}`}>
                {b === 'terrain' ? 'Terrain' : 'Satellite'}
              </button>
            ))}
          </div>
          <div className="p-2 border-t border-slate-800 flex gap-1">
            <button onClick={fitScenario} className="flex-1 h-7 border border-slate-800 text-slate-300 hover:border-slate-600 flex items-center justify-center gap-1"><Crosshair className="w-3 h-3" /> Scenario</button>
            <button onClick={fitIndia} className="flex-1 h-7 border border-slate-800 text-slate-300 hover:border-slate-600">All India</button>
          </div>
        </div>

        {/* Legend */}
        <div className="absolute bottom-3 left-3 z-[1000] theatre-glass px-3 py-2 text-[10px] text-slate-400 flex flex-wrap gap-x-4 gap-y-1 max-w-[calc(100%-1.5rem)]">
          <span className="text-slate-500 uppercase tracking-wider">Flight category</span>
          {Object.entries(CAT_COLOR).map(([k, c]) => (
            <span key={k} className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full" style={{ border: `2px solid ${c}` }} />{k} <span className="font-mono">{cats[k] ?? 0}</span></span>
          ))}
          <span className="text-slate-500 uppercase tracking-wider ml-2">Airspace</span>
          {Object.entries(AREA_COLOR).map(([k, c]) => (
            <span key={k} className="flex items-center gap-1"><span className="w-2.5 h-2.5" style={{ background: c, opacity: 0.6 }} />{k}</span>
          ))}
          <span className="text-slate-500 uppercase tracking-wider ml-2">Sorties</span>
          {['CRITICAL', 'HIGH', 'MEDIUM'].map((p) => (
            <span key={p} className="flex items-center gap-1"><span className="w-3 h-0.5" style={{ background: PRIO_COLOR[p] }} />{p.toLowerCase()}</span>
          ))}
        </div>

        {/* Detail card */}
        {picked && (
          <div className="absolute top-3 right-3 z-[1000] w-80 max-w-[calc(100%-1.5rem)] theatre-glass text-xs max-h-[calc(100%-1.5rem)] overflow-y-auto">
            <div className="flex items-start justify-between gap-2 p-3 border-b border-slate-800">
              <div className="min-w-0">
                {picked.kind === 'airfield' ? (
                  <>
                    <div className="text-sm text-slate-100 font-medium">{picked.field.name}</div>
                    <div className="font-mono text-slate-400">{[picked.field.icao, picked.field.iata].filter(Boolean).join(' · ') || picked.field.ident}</div>
                  </>
                ) : (
                  <>
                    <div className="text-sm text-slate-100 font-medium">{picked.area.designator} {picked.area.name}</div>
                    <div className="text-slate-400">{picked.area.fir} FIR</div>
                  </>
                )}
              </div>
              <button onClick={() => setPicked(null)} className="btn-ghost h-6 px-1.5" aria-label="Close details"><X className="w-3.5 h-3.5" /></button>
            </div>
            {picked.kind === 'airfield' ? (() => {
              const f = picked.field;
              const m = metarFor(f.icao);
              const can = types.filter((t) => t.service_ceiling_m != null && f.elevation_m != null && t.service_ceiling_m >= f.elevation_m);
              const cant = types.filter((t) => t.service_ceiling_m != null && f.elevation_m != null && t.service_ceiling_m < f.elevation_m);
              const near = areas
                .filter((a) => (a.polygon ? inPolygon([f.latitude, f.longitude], a.polygon) : a.center && a.radius_km && km(a.center, [f.latitude, f.longitude]) <= a.radius_km + 15))
                .slice(0, 4);
              return (
                <div className="p-3 space-y-3">
                  <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
                    <dt className="text-slate-500">Type</dt><dd className="text-slate-200">{TYPE_LABEL[f.type] ?? f.type}</dd>
                    <dt className="text-slate-500">Elevation</dt><dd className="text-slate-200 font-mono">{f.elevation_m != null ? `${Math.round(f.elevation_m)} m · ${Math.round(f.elevation_m / 0.3048)} ft` : '—'}</dd>
                    <dt className="text-slate-500">Position</dt><dd className="text-slate-200 font-mono">{f.latitude.toFixed(4)}, {f.longitude.toFixed(4)}</dd>
                    <dt className="text-slate-500">Region</dt><dd className="text-slate-200">{f.municipality ? `${f.municipality}, ` : ''}{f.state.replace('IN-', '')}</dd>
                  </dl>
                  {m && (
                    <div className="space-y-1">
                      <div className="flex items-center gap-2"><span className="text-slate-500">Weather</span>{m.flight_category && <Badge status={m.flight_category} tone={m.flight_category === 'VFR' ? 'ok' : m.flight_category === 'MVFR' ? 'info' : 'crit'} />}</div>
                      <div className="font-mono text-[11px] text-slate-200 bg-slate-950 border border-slate-800 p-2 break-words">{m.raw_metar}</div>
                      {m.raw_taf && <div className="font-mono text-[10px] text-slate-400 break-words">{m.raw_taf}</div>}
                    </div>
                  )}
                  {f.elevation_m != null && types.length > 0 && (
                    <div className="space-y-1">
                      <div className="text-slate-500">Types within their published ceiling here</div>
                      <div className="flex flex-wrap gap-1">
                        {can.map((t) => (
                          <span key={t.type_name} title={`${t.role} · ceiling ${t.service_ceiling_m} m`} className={`px-1.5 py-0.5 border ${f.elevation_m! / t.service_ceiling_m! >= 0.8 ? 'border-warn/50 text-warn' : 'border-slate-700 text-slate-300'}`}>
                            {t.type_name}
                          </span>
                        ))}
                        {cant.map((t) => <span key={t.type_name} className="px-1.5 py-0.5 border border-crit/40 text-crit line-through">{t.type_name}</span>)}
                      </div>
                      <div className="text-[10px] text-slate-500">Amber: above 80% of ceiling. Fixed-wing types also need a runway, which this check does not cover.</div>
                    </div>
                  )}
                  {near.length > 0 && (
                    <div className="space-y-1">
                      <div className="text-slate-500">AIP areas over or near this site</div>
                      {near.map((a) => (
                        <button key={a.designator} onClick={() => setPicked({ kind: 'area', area: a })} className="block w-full text-left hover:bg-slate-800/60 px-1 py-0.5">
                          <span className="font-mono" style={{ color: AREA_COLOR[a.type] }}>{a.designator}</span> <span className="text-slate-300">{a.name}</span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              );
            })() : (
              <div className="p-3 space-y-2">
                <div className="flex gap-2"><Badge status={picked.area.type} tone={picked.area.type === 'Prohibited' ? 'crit' : picked.area.type === 'Danger' ? 'warn' : 'info'} />{picked.area.approximated_arcs && <Badge status="arcs approximated" />}</div>
                <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
                  <dt className="text-slate-500">Limits</dt><dd className="text-slate-200 font-mono">{picked.area.vertical_limits || '—'}</dd>
                  <dt className="text-slate-500">Shape</dt><dd className="text-slate-200">{picked.area.geometry === 'circle' ? `circle, ${picked.area.radius_km} km` : `${picked.area.polygon?.length ?? 0}-point polygon`}</dd>
                </dl>
                {picked.area.remarks && <p className="text-slate-300 leading-relaxed">{picked.area.remarks}</p>}
                <p className="text-[10px] text-slate-500">Source: AAI eAIP India, ENR 5.1. Not for navigation.</p>
              </div>
            )}
          </div>
        )}
      </div>
      <p className="text-[11px] text-slate-500">
        Airfields: OurAirports (public domain). Airspace: AAI eAIP ENR 5.1, not for navigation. Weather: NOAA Aviation Weather Center. Aircraft ceilings: Wikipedia (CC BY-SA). Scenario sorties are drawn from the scenario's hub.
      </p>
    </div>
  );
};
