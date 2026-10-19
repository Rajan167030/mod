import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Trash2 } from 'lucide-react';
import { api } from '../../api/client';
import { Location, OpsZone, OpsZoneCreate, Scenario, ZoneKind } from '../../types/api';
import { useActiveTheme } from '../../components/useTheme';
import { Badge, EmptyState, ErrorState, Notice, PageHeader, Panel, SkeletonTable, StatStrip, fmtZulu } from '../../components/ui';
import { drawZones, zoneColor, zoneRule } from './zoneLayer';

const ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services';
const BASEMAP = {
  dark: ['Canvas/World_Dark_Gray_Base', 'Canvas/World_Dark_Gray_Reference'],
  light: ['Canvas/World_Light_Gray_Base', 'Canvas/World_Light_Gray_Reference'],
} as const;

const KINDS: { kind: ZoneKind; label: string; category: 'THREAT' | 'AIRSPACE' }[] = [
  { kind: 'SAM', label: 'SAM site', category: 'THREAT' },
  { kind: 'AAA', label: 'Anti-aircraft artillery', category: 'THREAT' },
  { kind: 'MANPADS', label: 'MANPADS', category: 'THREAT' },
  { kind: 'RADAR', label: 'Hostile radar', category: 'THREAT' },
  { kind: 'RESTRICTED', label: 'Restricted airspace', category: 'AIRSPACE' },
  { kind: 'NO_FLY', label: 'No-fly zone', category: 'AIRSPACE' },
];
const SOURCES = ['ELINT', 'SIGINT', 'IMINT', 'HUMINT', 'NOTAM', 'Own forces'];
const HOUR = 3600 * 1000;

const code = (name: string) => name.match(/^[A-Z]{1,5}-\d+/)?.[0] ?? name;

export const ThreatsPage: React.FC = () => {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenarioId, setScenarioId] = useState('');
  const [zones, setZones] = useState<OpsZone[] | null>(null);
  const [sites, setSites] = useState<Location[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [draft, setDraft] = useState({
    name: '', kind: 'SAM' as ZoneKind, effect: 'BLOCK' as 'BLOCK' | 'AVOID', radius: '20',
    lat: '', lon: '', startsIn: '0', lasts: '6', exempt: 'DASS', source: 'ELINT', confidence: '0.7',
  });

  const mapEl = useRef<HTMLDivElement>(null);
  const map = useRef<any>(null);
  const tiles = useRef<any>(null);
  const layer = useRef<any>(null);
  const fitted = useRef(false);
  const theme = useActiveTheme();

  useEffect(() => {
    api.getScenarios().then((s) => {
      setScenarios(s);
      if (s[0]) setScenarioId(s[0].id);
    }).catch((e) => setError(e?.message || 'Could not load scenarios.'));
  }, []);

  const load = useCallback(async () => {
    if (!scenarioId) return;
    setError(null);
    try {
      const [z, locs] = await Promise.all([api.getZones(scenarioId), api.getLocations(scenarioId)]);
      setZones(z);
      setSites(locs);
    } catch (e: any) {
      setError(e?.message || 'Could not load threats.');
    }
  }, [scenarioId]);

  useEffect(() => {
    setZones(null);
    fitted.current = false;
    load();
  }, [load]);

  // Map
  useEffect(() => {
    const L = (window as any).L;
    if (!L || !mapEl.current || map.current) return;
    map.current = L.map(mapEl.current, { center: [34, 76.5], zoom: 7, zoomControl: false });
    L.control.zoom({ position: 'bottomright' }).addTo(map.current);
    L.control.scale({ position: 'bottomleft', imperial: false }).addTo(map.current);
    layer.current = L.layerGroup().addTo(map.current);
    map.current.on('click', (e: any) =>
      setDraft((d) => ({ ...d, lat: e.latlng.lat.toFixed(3), lon: e.latlng.lng.toFixed(3) })),
    );
    return () => {
      map.current?.remove();
      map.current = null;
    };
  }, []);

  useEffect(() => {
    const L = (window as any).L;
    if (!L || !map.current) return;
    tiles.current?.remove();
    const [base, labels] = BASEMAP[theme];
    const tile = (path: string) => L.tileLayer(`${ESRI}/${path}/MapServer/tile/{z}/{y}/{x}`, { maxZoom: 16, attribution: 'Tiles &copy; Esri' });
    tiles.current = L.layerGroup([tile(base), tile(labels)]).addTo(map.current);
  }, [theme]);

  useEffect(() => {
    const L = (window as any).L;
    const g = layer.current;
    if (!L || !g) return;
    g.clearLayers();
    drawZones(L, g, zones ?? [], Date.now());
    for (const s of sites) {
      L.circleMarker([s.latitude, s.longitude], { radius: 4, color: 'rgb(var(--accent-400))', weight: 2, fillOpacity: 1, fillColor: 'rgb(var(--slate-950))' })
        .bindTooltip(s.name, { direction: 'right' })
        .addTo(g);
    }
    if (draft.lat && draft.lon && Number(draft.radius) > 0) {
      const cat = KINDS.find((k) => k.kind === draft.kind)!.category;
      const color = zoneColor({ category: cat, effect: draft.effect });
      L.circle([Number(draft.lat), Number(draft.lon)], { radius: Number(draft.radius) * 1000, color, dashArray: '2 4', weight: 2, fillOpacity: 0.05 }).addTo(g);
    }
    if (!fitted.current && sites.length) {
      map.current.fitBounds(L.latLngBounds(sites.map((s) => [s.latitude, s.longitude])), { padding: [50, 50], maxZoom: 9 });
      fitted.current = true;
    }
  }, [zones, sites, draft.lat, draft.lon, draft.radius, draft.kind, draft.effect]);

  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!draft.lat || !draft.lon) {
      setError('Click the map (or pick a site) to place the zone.');
      return;
    }
    const k = KINDS.find((x) => x.kind === draft.kind)!;
    const start = Date.now() + Number(draft.startsIn || 0) * HOUR;
    const body: OpsZoneCreate = {
      name: draft.name || `${k.label}${draft.source ? ` (${draft.source})` : ''}`,
      category: k.category,
      kind: draft.kind,
      effect: draft.effect,
      center_lat: Number(draft.lat),
      center_lon: Number(draft.lon),
      radius_km: Number(draft.radius),
      active_from: new Date(start).toISOString(),
      active_until: draft.lasts ? new Date(start + Number(draft.lasts) * HOUR).toISOString() : null,
      exempt_capability: draft.effect === 'BLOCK' && k.category === 'THREAT' && draft.exempt ? draft.exempt : null,
      source: draft.source || null,
      confidence: Number(draft.confidence),
    };
    setSaving(true);
    setError(null);
    try {
      const z = await api.createZone(scenarioId, body);
      setNotice(`${z.name} added. It affects ${z.affected_tasks.length} task(s); re-plan to apply it.`);
      setDraft((d) => ({ ...d, name: '', lat: '', lon: '' }));
      await load();
    } catch (err: any) {
      setError(err?.message || 'Could not add the zone.');
    } finally {
      setSaving(false);
    }
  };

  const remove = async (z: OpsZone) => {
    try {
      await api.deleteZone(z.id);
      await load();
    } catch (e: any) {
      setError(e?.message || 'Could not delete the zone.');
    }
  };

  const threats = (zones ?? []).filter((z) => z.category === 'THREAT');
  const affected = new Set((zones ?? []).flatMap((z) => z.affected_tasks.map((t) => t.id)));
  const isThreat = KINDS.find((k) => k.kind === draft.kind)?.category === 'THREAT';

  return (
    <div className="space-y-4">
      <PageHeader
        title="Threats & airspace"
        subtitle="Threat zones and airspace restrictions. The optimiser keeps sorties out of blocking zones while they are active, steers away from zones to avoid, and the validator checks every plan against them."
        actions={
          <select className="field max-w-[280px]" value={scenarioId} onChange={(e) => setScenarioId(e.target.value)} aria-label="Scenario">
            {scenarios.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        }
      />
      {error && <ErrorState message={error} onRetry={load} />}
      {notice && (
        <Notice tone="warn" onDismiss={() => setNotice(null)}>
          {notice} <Link to="/courses-of-action" className="underline">Generate courses of action →</Link>
        </Notice>
      )}

      <StatStrip
        loading={!zones}
        items={[
          { label: 'Zones', value: zones?.length ?? 0 },
          { label: 'Active now', value: zones?.filter((z) => z.active_now).length ?? 0, tone: zones?.some((z) => z.active_now) ? 'warn' : 'default' },
          { label: 'Threats', value: threats.length, hint: `${threats.filter((z) => z.effect === 'BLOCK').length} blocking` },
          { label: 'Airspace restrictions', value: (zones?.length ?? 0) - threats.length },
          { label: 'Tasks affected', value: affected.size, tone: affected.size ? 'warn' : 'default' },
          { label: 'Protected aircraft rule', value: threats.filter((z) => z.exempt_capability).length, hint: 'zones open to DASS-fitted aircraft' },
        ]}
      />

      <div className="grid grid-cols-1 xl:grid-cols-12 gap-4">
        <Panel title="Map" right="Click to place a new zone" className="xl:col-span-8 h-[520px]">
          <div className="relative h-full">
            <div ref={mapEl} className="absolute inset-0" />
            <div className="absolute top-2 left-2 z-[1000] flex flex-wrap items-center gap-3 px-2 py-1 bg-slate-950/85 border border-slate-800 text-[10px] text-slate-400">
              <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full border-2 border-crit" /> threat, no entry</span>
              <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full border-2 border-warn" /> threat, avoid</span>
              <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 border-2 border-info" /> airspace restriction</span>
              <span className="text-slate-500">Dashed = not active now</span>
            </div>
          </div>
        </Panel>

        <Panel title="Add threat or restriction" className="xl:col-span-4">
          <form onSubmit={add} className="p-3 space-y-3 text-xs">
            <div className="grid grid-cols-2 gap-2">
              <div className="col-span-2">
                <label className="label" htmlFor="z-kind">Type</label>
                <select id="z-kind" className="field w-full" value={draft.kind} onChange={(e) => {
                  const kind = e.target.value as ZoneKind;
                  const cat = KINDS.find((k) => k.kind === kind)!.category;
                  setDraft((d) => ({ ...d, kind, source: cat === 'AIRSPACE' ? 'NOTAM' : d.source === 'NOTAM' ? 'ELINT' : d.source, effect: kind === 'MANPADS' ? 'AVOID' : 'BLOCK' }));
                }}>
                  {KINDS.map((k) => <option key={k.kind} value={k.kind}>{k.label}</option>)}
                </select>
              </div>
              <div className="col-span-2">
                <label className="label" htmlFor="z-name">Name</label>
                <input id="z-name" className="field w-full" value={draft.name} onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))} placeholder="e.g. SAM radar, Foxtrot north" />
              </div>
              <div>
                <label className="label" htmlFor="z-effect">Rule</label>
                <select id="z-effect" className="field w-full" value={draft.effect} onChange={(e) => setDraft((d) => ({ ...d, effect: e.target.value as 'BLOCK' | 'AVOID' }))}>
                  <option value="BLOCK">No entry</option>
                  <option value="AVOID">Avoid if possible</option>
                </select>
              </div>
              <div>
                <label className="label" htmlFor="z-exempt">Exempt aircraft</label>
                <select id="z-exempt" className="field w-full" value={draft.exempt} disabled={!isThreat || draft.effect !== 'BLOCK'} onChange={(e) => setDraft((d) => ({ ...d, exempt: e.target.value }))}>
                  <option value="">None</option>
                  <option value="DASS">DASS-fitted</option>
                </select>
              </div>
              <div>
                <label className="label" htmlFor="z-lat">Centre lat</label>
                <input id="z-lat" className="field w-full font-mono" value={draft.lat} onChange={(e) => setDraft((d) => ({ ...d, lat: e.target.value }))} placeholder="click map" />
              </div>
              <div>
                <label className="label" htmlFor="z-lon">Centre lon</label>
                <input id="z-lon" className="field w-full font-mono" value={draft.lon} onChange={(e) => setDraft((d) => ({ ...d, lon: e.target.value }))} placeholder="click map" />
              </div>
              <div className="col-span-2">
                <label className="label" htmlFor="z-site">…or centre on a site</label>
                <select id="z-site" className="field w-full" value="" onChange={(e) => {
                  const s = sites.find((x) => x.id === e.target.value);
                  if (s) setDraft((d) => ({ ...d, lat: s.latitude.toFixed(3), lon: s.longitude.toFixed(3) }));
                }}>
                  <option value="">Choose a site</option>
                  {sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                </select>
              </div>
              <div>
                <label className="label" htmlFor="z-radius">Radius (km)</label>
                <input id="z-radius" type="number" min={1} max={500} className="field w-full font-mono" value={draft.radius} onChange={(e) => setDraft((d) => ({ ...d, radius: e.target.value }))} />
              </div>
              <div>
                <label className="label" htmlFor="z-source">Source</label>
                <select id="z-source" className="field w-full" value={draft.source} onChange={(e) => setDraft((d) => ({ ...d, source: e.target.value }))}>
                  {SOURCES.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              <div>
                <label className="label" htmlFor="z-start">Starts in (h)</label>
                <input id="z-start" type="number" min={0} step={0.5} className="field w-full font-mono" value={draft.startsIn} onChange={(e) => setDraft((d) => ({ ...d, startsIn: e.target.value }))} />
              </div>
              <div>
                <label className="label" htmlFor="z-lasts">Lasts (h, blank = open)</label>
                <input id="z-lasts" type="number" min={0.5} step={0.5} className="field w-full font-mono" value={draft.lasts} onChange={(e) => setDraft((d) => ({ ...d, lasts: e.target.value }))} />
              </div>
              <div className="col-span-2">
                <label className="label" htmlFor="z-conf">Confidence: {Math.round(Number(draft.confidence) * 100)}%</label>
                <input id="z-conf" type="range" min={0.1} max={1} step={0.05} className="w-full accent-indigo-500" value={draft.confidence} onChange={(e) => setDraft((d) => ({ ...d, confidence: e.target.value }))} />
              </div>
            </div>
            <button type="submit" disabled={saving || !scenarioId} className="btn-primary w-full">{saving ? 'Adding…' : 'Add zone'}</button>
            <p className="text-slate-500">Confidence feeds the predicted risk of sorties flown near the zone.</p>
          </form>
        </Panel>
      </div>

      <Panel title="Zones" right={zones ? `${zones.length}` : undefined}>
        {!zones ? (
          <SkeletonTable rows={4} cols={6} />
        ) : zones.length === 0 ? (
          <EmptyState compact title="No threats or restrictions" description="Click the map to add one." />
        ) : (
          <div className="overflow-x-auto">
            <table className="data-table w-full text-xs">
              <thead>
                <tr>
                  <th>Zone</th>
                  <th>Type</th>
                  <th>Rule</th>
                  <th>Active</th>
                  <th>Source</th>
                  <th>Tasks affected</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {zones.map((z) => (
                  <tr key={z.id}>
                    <td>
                      <div className="flex items-center gap-2">
                        <span className="w-2.5 h-2.5 shrink-0" style={{ background: zoneColor(z) }} />
                        <span className="text-slate-200">{z.name}</span>
                        {z.active_now && <Badge status="ACTIVE" tone="warn" />}
                      </div>
                      {z.notes && <div className="text-slate-500 mt-0.5 max-w-md">{z.notes}</div>}
                    </td>
                    <td><Badge status={z.kind} tone={z.category === 'AIRSPACE' ? 'info' : z.effect === 'BLOCK' ? 'crit' : 'warn'} /></td>
                    <td className="text-slate-300 whitespace-nowrap">{zoneRule(z)}</td>
                    <td className="font-mono text-slate-400 whitespace-nowrap">
                      {z.active_from ? fmtZulu(z.active_from) : 'now'} → {z.active_until ? fmtZulu(z.active_until) : 'open'}
                    </td>
                    <td className="text-slate-400 whitespace-nowrap">{z.source ?? '—'} · {Math.round(z.confidence * 100)}%</td>
                    <td className="font-mono text-slate-300">
                      {z.affected_tasks.length ? z.affected_tasks.map((t) => code(t.name)).join(', ') : <span className="text-slate-600">none</span>}
                    </td>
                    <td className="text-right">
                      <button onClick={() => remove(z)} className="btn-ghost h-7 px-2" aria-label={`Delete ${z.name}`}><Trash2 className="w-3.5 h-3.5" /></button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
};
