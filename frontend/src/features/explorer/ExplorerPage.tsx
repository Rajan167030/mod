import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Search } from 'lucide-react';
import { api } from '../../api/client';
import { GraphNode, ObjectGraph, ObjectProfile, ObjectSummary, ObjectType, Scenario } from '../../types/api';
import {
  Badge,
  EmptyState,
  ErrorState,
  PageHeader,
  Panel,
  Skeleton,
  SkeletonTable,
  fmtZulu,
  humanize,
} from '../../components/ui';
import { LinkGraph } from './LinkGraph';

const TYPES: { key: ObjectType | 'all'; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'aircraft', label: 'Aircraft' },
  { key: 'task', label: 'Tasks' },
  { key: 'site', label: 'Sites' },
  { key: 'capability', label: 'Capabilities' },
];

const statusTone = (s: string): 'default' | 'ok' | 'warn' | 'crit' | 'info' => {
  if (['CONFLICT', 'GROUNDED', 'UNAVAILABLE', 'CRITICAL', 'NONE'].includes(s)) return 'crit';
  if (['WEATHER_RISK', 'UNASSIGNED', 'WARNING', 'SINGLE_POINT', 'MAINTENANCE'].includes(s)) return 'warn';
  if (['PLANNED', 'AVAILABLE', 'CLEAR', 'OK'].includes(s)) return 'ok';
  return 'default';
};

type Ref = { type: ObjectType; id: string };

export const ExplorerPage: React.FC = () => {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenarioId, setScenarioId] = useState('');
  const [q, setQ] = useState('');
  const [type, setType] = useState<ObjectType | 'all'>('all');
  const [results, setResults] = useState<ObjectSummary[] | null>(null);
  const [graph, setGraph] = useState<ObjectGraph | null>(null);
  const [showCaps, setShowCaps] = useState(true);
  const [selected, setSelected] = useState<Ref | null>(null);
  const [trail, setTrail] = useState<Ref[]>([]);
  const [profile, setProfile] = useState<ObjectProfile | null>(null);
  const [profileLoading, setProfileLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [params] = useSearchParams();

  // Deep link from alerts and elsewhere: /explorer?type=task&id=...
  useEffect(() => {
    const type = params.get('type') as ObjectType | null;
    const id = params.get('id');
    if (type && id) setSelected({ type, id });
  }, [params]);

  useEffect(() => {
    api
      .getScenarios()
      .then((s) => {
        setScenarios(s);
        const wanted = params.get('scenario');
        setScenarioId(s.find((x) => x.id === wanted)?.id ?? s[0]?.id ?? '');
      })
      .catch((e) => setError(e?.message || 'Could not load scenarios.'));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Search (debounced)
  useEffect(() => {
    if (!scenarioId) return;
    const id = window.setTimeout(() => {
      api
        .searchObjects(scenarioId, q, type === 'all' ? undefined : type)
        .then(setResults)
        .catch((e) => setError(e?.message || 'Search failed.'));
    }, 200);
    return () => window.clearTimeout(id);
  }, [scenarioId, q, type]);

  const loadGraph = useCallback(() => {
    if (!scenarioId) return;
    setGraph(null);
    api
      .getObjectGraph(scenarioId, showCaps)
      .then(setGraph)
      .catch((e) => setError(e?.message || 'Could not build the graph.'));
  }, [scenarioId, showCaps]);

  useEffect(() => {
    loadGraph();
  }, [loadGraph]);

  useEffect(() => {
    if (!scenarioId || !selected) {
      setProfile(null);
      return;
    }
    setProfileLoading(true);
    api
      .getObject(scenarioId, selected.type, selected.id)
      .then(setProfile)
      .catch((e) => setError(e?.message || 'Could not load the object.'))
      .finally(() => setProfileLoading(false));
  }, [scenarioId, selected]);

  const open = (ref: Ref) => {
    setTrail((t) => (selected ? [...t.slice(-6), selected] : t));
    setSelected(ref);
  };
  const back = () => {
    const prev = trail[trail.length - 1];
    setTrail((t) => t.slice(0, -1));
    setSelected(prev ?? null);
  };

  const selectedKey = selected ? `${selected.type}:${selected.id}` : null;
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    (results ?? []).forEach((r) => (c[r.status] = (c[r.status] ?? 0) + 1));
    return c;
  }, [results]);

  return (
    <div className="space-y-4">
      <PageHeader
        title="Object explorer"
        subtitle="Every aircraft, task, site and capability as a linked object. Click anything to see what it connects to and why."
        actions={
          <select className="field max-w-[280px]" value={scenarioId} onChange={(e) => { setScenarioId(e.target.value); setSelected(null); setTrail([]); }} aria-label="Scenario">
            {scenarios.map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>
        }
      />

      {error && <ErrorState message={error} onRetry={() => { setError(null); loadGraph(); }} />}

      <div className="grid grid-cols-1 2xl:grid-cols-12 gap-4">
        <Panel title="Objects" right={results ? `${results.length} found` : undefined} className="2xl:col-span-3 2xl:max-h-[760px]">
          <div className="p-2 space-y-2 border-b border-slate-800">
            <div className="relative">
              <Search className="w-3 h-3 text-slate-500 absolute left-2 top-1/2 -translate-y-1/2" />
              <input className="field w-full pl-6" placeholder="Name, code, qualification, site" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search objects" />
            </div>
            <div className="flex flex-wrap gap-1" role="group" aria-label="Object type">
              {TYPES.map((t) => (
                <button
                  key={t.key}
                  onClick={() => setType(t.key)}
                  className={`px-2 h-6 text-[11px] border ${type === t.key ? 'border-indigo-500 text-slate-100' : 'border-slate-800 text-slate-400 hover:text-slate-200'}`}
                >
                  {t.label}
                </button>
              ))}
            </div>
            {results && (counts.CONFLICT || counts.UNASSIGNED || counts.WEATHER_RISK || counts.SINGLE_POINT) ? (
              <div className="flex flex-wrap gap-2 text-[10px] font-mono">
                {counts.CONFLICT ? <span className="text-crit">{counts.CONFLICT} conflict</span> : null}
                {counts.UNASSIGNED ? <span className="text-warn">{counts.UNASSIGNED} unassigned</span> : null}
                {counts.WEATHER_RISK ? <span className="text-warn">{counts.WEATHER_RISK} wx risk</span> : null}
                {counts.SINGLE_POINT ? <span className="text-warn">{counts.SINGLE_POINT} single-source capability</span> : null}
              </div>
            ) : null}
          </div>
          <div className="overflow-y-auto max-h-[640px]">
            {!results ? (
              <SkeletonTable rows={10} cols={2} />
            ) : results.length === 0 ? (
              <EmptyState compact title="Nothing matches" />
            ) : (
              <ul>
                {results.map((r) => {
                  const active = selected?.id === r.id && selected.type === r.type;
                  return (
                    <li key={`${r.type}:${r.id}`}>
                      <button
                        onClick={() => open({ type: r.type, id: r.id })}
                        className={`w-full text-left px-3 py-1.5 border-b border-slate-800/60 border-l-2 text-xs ${active ? 'bg-slate-900 border-l-indigo-400' : 'border-l-transparent hover:bg-slate-900/60'}`}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className={`truncate ${r.type === 'task' || r.type === 'aircraft' ? 'font-mono' : ''} ${active ? 'text-slate-100' : 'text-slate-300'}`}>{r.title}</span>
                          <Badge status={r.status} tone={statusTone(r.status)} />
                        </div>
                        <div className="text-[10px] text-slate-500 truncate">{r.type} · {r.subtitle}</div>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </Panel>

        <div className="2xl:col-span-9 space-y-4">
          <Panel
            title={graph ? `Link graph · ${graph.nodes.length} objects · ${graph.edges.length} links${graph.active_version ? ` · plan v${graph.active_version}` : ''}` : 'Link graph'}
            right={
              <label className="flex items-center gap-1.5 cursor-pointer print:hidden">
                <input type="checkbox" checked={showCaps} onChange={(e) => setShowCaps(e.target.checked)} className="accent-indigo-500" />
                Capabilities
              </label>
            }
          >
            {graph ? (
              <LinkGraph
                nodes={graph.nodes}
                edges={graph.edges}
                selectedKey={selectedKey}
                onSelect={(n: GraphNode) => open({ type: n.type, id: n.id })}
              />
            ) : (
              <div className="p-3"><Skeleton className="h-[420px] w-full" /></div>
            )}
          </Panel>

          {selected && (
            <Panel
              title={profile ? `${profile.type} · ${profile.title}` : 'Loading…'}
              right={
                <div className="flex items-center gap-2 print:hidden">
                  {trail.length > 0 && <button onClick={back} className="btn-ghost h-6 px-2">← Back</button>}
                  <button onClick={() => { setSelected(null); setTrail([]); }} className="btn-ghost h-6 px-2">Close</button>
                </div>
              }
            >
              {profileLoading || !profile ? (
                <SkeletonTable rows={6} cols={3} />
              ) : (
                <ProfileView p={profile} onOpen={open} />
              )}
            </Panel>
          )}
        </div>
      </div>
    </div>
  );
};

const ProfileView: React.FC<{ p: ObjectProfile; onOpen: (r: Ref) => void }> = ({ p, onOpen }) => {
  const groups = useMemo(() => {
    const g: Record<string, typeof p.links> = {};
    p.links.forEach((l) => (g[l.relation] ||= []).push(l));
    return g;
  }, [p]);

  return (
    <div className="grid grid-cols-1 xl:grid-cols-12 text-xs">
      <div className="xl:col-span-4 border-b xl:border-b-0 xl:border-r border-slate-800 p-3 space-y-3">
        <div className="flex items-center gap-2">
          <span className="text-sm text-slate-100 font-medium">{p.title}</span>
          <Badge status={p.status} tone={statusTone(p.status)} />
        </div>
        <dl className="divide-y divide-slate-800/60">
          {Object.entries(p.properties).map(([k, v]) => (
            <div key={k} className="flex justify-between gap-4 py-1.5">
              <dt className="text-slate-500">{k}</dt>
              <dd className="text-slate-200 text-right font-mono">{String(v)}</dd>
            </div>
          ))}
        </dl>
        {p.conflicts.length > 0 && (
          <div className="border border-crit/40 bg-crit/5 p-2 space-y-1">
            <div className="text-crit font-medium">Conflicts</div>
            {p.conflicts.map((c, i) => <div key={i} className="text-slate-300">{c}</div>)}
          </div>
        )}
        {p.unavailability && p.unavailability.length > 0 && (
          <div>
            <div className="label">Unavailable</div>
            {p.unavailability.map((u, i) => (
              <div key={i} className="font-mono text-warn">{fmtZulu(u.from)} – {fmtZulu(u.to)}</div>
            ))}
          </div>
        )}
        {p.weather_hours && p.weather_hours.length > 0 && (
          <div>
            <div className="label">Forecast limit hours</div>
            <div className="flex flex-wrap gap-0.5">
              {p.weather_hours.slice(0, 48).map((h) => (
                <span
                  key={h.hour}
                  title={`${fmtZulu(h.hour)} ${h.severity.toLowerCase()}`}
                  className={`w-2.5 h-3 ${h.severity === 'CRITICAL' ? 'bg-crit' : 'bg-warn/70'}`}
                />
              ))}
            </div>
          </div>
        )}
      </div>

      <div className="xl:col-span-5 border-b xl:border-b-0 xl:border-r border-slate-800 p-3 space-y-3">
        <div className="label">Links</div>
        {Object.keys(groups).length === 0 && <div className="text-slate-500">No links.</div>}
        {Object.entries(groups).map(([relation, links]) => (
          <div key={relation}>
            <div className="text-[10px] uppercase tracking-[0.08em] text-slate-500 mb-1">{relation} · {links.length}</div>
            <ul className="space-y-0.5">
              {links.map((l) => (
                <li key={`${l.type}:${l.id}:${relation}`}>
                  <button onClick={() => onOpen({ type: l.type, id: l.id })} className="w-full flex items-center justify-between gap-2 px-2 py-1 border border-slate-800 hover:border-slate-600 hover:bg-slate-900 text-left">
                    <span className="truncate">
                      <span className="text-slate-500 mr-1.5">{l.type}</span>
                      <span className={`text-slate-200 ${l.type !== 'site' && l.type !== 'capability' ? 'font-mono' : ''}`}>{l.title}</span>
                      {l.detail && <span className="text-slate-500 ml-1.5">{l.detail}</span>}
                    </span>
                    {l.status && <Badge status={l.status} tone={statusTone(l.status)} />}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      <div className="xl:col-span-3 p-3 space-y-3">
        <div className="label">Disruptions</div>
        {p.disruptions.length === 0 ? (
          <div className="text-slate-500">None recorded.</div>
        ) : (
          p.disruptions.map((d, i) => (
            <div key={i} className="border-l-2 border-warn pl-2">
              <div className="font-mono text-slate-500">{fmtZulu(d.at)}</div>
              <div className="text-slate-300">{humanize(d.type.replace('EXERCISE_', ''))}</div>
            </div>
          ))
        )}
        <div className="label pt-2">History</div>
        {p.history.length === 0 ? (
          <div className="text-slate-500">No audit entries for this object.</div>
        ) : (
          p.history.map((h, i) => (
            <div key={i} className="border-l-2 border-slate-700 pl-2">
              <div className="font-mono text-slate-500">{fmtZulu(h.at)}</div>
              <div className="text-slate-300">{humanize(h.what)}</div>
              <div className="text-slate-500">{h.who}</div>
            </div>
          ))
        )}
      </div>
    </div>
  );
};
