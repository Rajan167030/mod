import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Plus, Search } from 'lucide-react';
import { api } from '../../api/client';
import { Location, Resource, Scenario, StoreItem, Task, TaskOption, TaskOptions } from '../../types/api';
import {
  Badge,
  EmptyState,
  ErrorState,
  Notice,
  PageHeader,
  Panel,
  SkeletonTable,
  StatStrip,
  fmtZulu,
  fmtZuluTime,
  shortId,
} from '../../components/ui';

const PRIORITIES: Task['priority'][] = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'];
const priorityRank: Record<string, number> = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3 };

const fmtMinutes = (m: number) => (m >= 60 ? `${Math.floor(m / 60)}h${m % 60 ? ` ${m % 60}m` : ''}` : `${m}m`);
/** datetime-local value (read as UTC) -> ISO string */
const zIso = (v: string) => (v ? new Date(`${v}:00Z`).toISOString() : '');
const toLocalZ = (d: Date) => d.toISOString().slice(0, 16);

type Planned = { resource: string; crew?: string | null; start: string };

export const TaskManagementPage: React.FC = () => {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenarioId, setScenarioId] = useState('');
  const [tasks, setTasks] = useState<Task[]>([]);
  const [planned, setPlanned] = useState<Record<string, Planned>>({});
  const [sites, setSites] = useState<Location[]>([]);
  const [resources, setResources] = useState<Resource[]>([]);
  const [stores, setStores] = useState<StoreItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<React.ReactNode>(null);
  const [search, setSearch] = useState('');
  const [priorityFilter, setPriorityFilter] = useState('ALL');
  const [open, setOpen] = useState<string | null>(null);
  const [options, setOptions] = useState<TaskOptions | null>(null);
  const [optLoading, setOptLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [draft, setDraft] = useState({ name: '', priority: 'HIGH', minutes: '90', from: '', to: '', site: '', qual: '', stores: '' });

  useEffect(() => {
    api.getScenarios().then((s) => {
      setScenarios(s);
      if (s[0]) setScenarioId(s.find((x) => x.name.startsWith('Northern Sector'))?.id ?? s[0].id);
    }).catch((e) => setError(e?.message || 'Could not load scenarios.'));
  }, []);

  const load = useCallback(async () => {
    if (!scenarioId) return;
    setLoading(true);
    setError(null);
    try {
      const [ts, locs, res, st, versions] = await Promise.all([
        api.getTasks(scenarioId), api.getLocations(scenarioId), api.getResources(scenarioId),
        api.getStores(scenarioId).catch(() => []), api.getScenarioSchedules(scenarioId),
      ]);
      setTasks(ts);
      setSites(locs);
      setResources(res);
      setStores(st);
      const active = versions.filter((v) => v.status === 'APPROVED').sort((a, b) => b.version_number - a.version_number)[0];
      const full = active ? await api.getSchedule(active.id) : null;
      setPlanned(Object.fromEntries((full?.assignments ?? []).map((a) => [a.task_id, { resource: a.resource_name ?? '', crew: a.crew_name, start: a.start_at }])));
      if (!draft.from && ts.length) {
        const t0 = new Date(Math.min(...ts.map((t) => new Date(t.earliest_start).getTime())));
        setDraft((d) => ({ ...d, from: toLocalZ(new Date(t0.getTime() + 2 * 3600e3)), to: toLocalZ(new Date(t0.getTime() + 8 * 3600e3)), site: locs[0]?.id ?? '' }));
      }
    } catch (err: any) {
      setError(err?.message || 'Could not load tasks.');
    } finally {
      setLoading(false);
    }
  }, [scenarioId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    setOpen(null);
    setOptions(null);
    load();
  }, [load]);

  const quals = useMemo(() => [...new Set(resources.flatMap((r) => (r.metadata_json?.qualifications as string[]) ?? []))].sort(), [resources]);

  const showOptions = async (t: Task) => {
    if (open === t.id) {
      setOpen(null);
      return;
    }
    setOpen(t.id);
    setOptions(null);
    setOptLoading(true);
    try {
      setOptions(await api.getTaskOptions(t.id));
    } catch (e: any) {
      setError(e?.message || 'Could not find options.');
    } finally {
      setOptLoading(false);
    }
  };

  const assign = async (t: Task, o: TaskOption) => {
    setBusy(true);
    try {
      const r = await api.assignTask(t.id, { resource_id: o.resource_id, crew_id: o.crew_id, start_at: o.start_at });
      setNotice(
        <>
          {t.name} on {o.resource_name} at {fmtZuluTime(o.start_at)} is proposed as plan v{r.proposed_version_number}.{' '}
          <Link to="/review" className="underline">A reviewer approves it in Review →</Link>
        </>,
      );
      setOpen(null);
    } catch (e: any) {
      setError(e?.message || 'Could not assign the mission.');
    } finally {
      setBusy(false);
    }
  };

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const reqs = [
        ...(draft.qual ? [{ requirement_type: 'QUALIFICATION', requirement_value: draft.qual }] : []),
        ...draft.stores.split(/[;,]/).map((s) => s.trim().toUpperCase()).filter(Boolean).map((s) => ({ requirement_type: 'STORE', requirement_value: s })),
      ];
      const t = await api.createTask({
        scenario_id: scenarioId, name: draft.name, priority: draft.priority, duration_minutes: Number(draft.minutes),
        earliest_start: zIso(draft.from), latest_finish: zIso(draft.to), location_id: draft.site || null, requirements: reqs,
      });
      setShowNew(false);
      setDraft((d) => ({ ...d, name: '' }));
      await load();
      setNotice(<>{t.name} added. Choose an aircraft and crew below.</>);
      await showOptions(t);
    } catch (err: any) {
      setError(err?.message || 'Could not add the mission.');
    } finally {
      setBusy(false);
    }
  };

  const filtered = tasks
    .filter((t) => {
      const q = search.toLowerCase();
      const matches = !q || t.name.toLowerCase().includes(q) || t.requirements.some((r) => r.requirement_value.toLowerCase().includes(q));
      return matches && (priorityFilter === 'ALL' || t.priority === priorityFilter);
    })
    .sort((a, b) => priorityRank[a.priority] - priorityRank[b.priority] || a.earliest_start.localeCompare(b.earliest_start));

  const byPriority = (p: string) => tasks.filter((t) => t.priority === p).length;
  const unplanned = tasks.filter((t) => !planned[t.id]);
  const siteName = Object.fromEntries(sites.map((s) => [s.id, s.name]));

  return (
    <div className="space-y-4">
      <PageHeader
        title="Missions"
        subtitle="Every mission in the scenario and where the active plan puts it. Add a mission, then let AirOps list the aircraft and crews that can fly it without moving anything else."
        actions={
          <>
            <select className="field max-w-[280px]" value={scenarioId} onChange={(e) => setScenarioId(e.target.value)} aria-label="Scenario">
              {scenarios.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
            <button onClick={() => setShowNew((v) => !v)} className="btn-primary"><Plus className="w-3.5 h-3.5" /> New mission</button>
          </>
        }
      />

      {error && <ErrorState message={error} onRetry={load} />}
      {notice && <Notice tone="ok" onDismiss={() => setNotice(null)}>{notice}</Notice>}

      {showNew && (
        <Panel title="New mission">
          <form onSubmit={create} className="p-3 grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
            <div className="col-span-2">
              <label className="label" htmlFor="m-name">Name</label>
              <input id="m-name" required minLength={2} className="field w-full" value={draft.name} onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))} placeholder="e.g. NS-40 Casualty evacuation, Nyoma" />
            </div>
            <div>
              <label className="label" htmlFor="m-prio">Priority</label>
              <select id="m-prio" className="field w-full" value={draft.priority} onChange={(e) => setDraft((d) => ({ ...d, priority: e.target.value }))}>
                {PRIORITIES.map((p) => <option key={p} value={p}>{p.toLowerCase()}</option>)}
              </select>
            </div>
            <div>
              <label className="label" htmlFor="m-min">Duration (min)</label>
              <input id="m-min" type="number" min={10} max={1440} required className="field w-full font-mono" value={draft.minutes} onChange={(e) => setDraft((d) => ({ ...d, minutes: e.target.value }))} />
            </div>
            <div>
              <label className="label" htmlFor="m-from">Window opens (Z)</label>
              <input id="m-from" type="datetime-local" required className="field w-full font-mono" value={draft.from} onChange={(e) => setDraft((d) => ({ ...d, from: e.target.value }))} />
            </div>
            <div>
              <label className="label" htmlFor="m-to">Must finish by (Z)</label>
              <input id="m-to" type="datetime-local" required className="field w-full font-mono" value={draft.to} onChange={(e) => setDraft((d) => ({ ...d, to: e.target.value }))} />
            </div>
            <div>
              <label className="label" htmlFor="m-site">Site</label>
              <select id="m-site" className="field w-full" value={draft.site} onChange={(e) => setDraft((d) => ({ ...d, site: e.target.value }))}>
                <option value="">No site</option>
                {sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            </div>
            <div>
              <label className="label" htmlFor="m-qual">Needs capability</label>
              <select id="m-qual" className="field w-full" value={draft.qual} onChange={(e) => setDraft((d) => ({ ...d, qual: e.target.value }))}>
                <option value="">Any aircraft</option>
                {quals.map((q) => <option key={q} value={q}>{q.replace(/_/g, ' ').toLowerCase()}</option>)}
              </select>
            </div>
            <div className="col-span-2">
              <label className="label" htmlFor="m-stores">Stores (e.g. FLARE_SET; ROCKET_POD:2)</label>
              <input id="m-stores" className="field w-full font-mono" value={draft.stores} onChange={(e) => setDraft((d) => ({ ...d, stores: e.target.value }))} placeholder={stores.map((s) => s.store_type).join('; ') || 'none'} />
            </div>
            <div className="col-span-2 flex items-end gap-2">
              <button type="submit" disabled={busy || !scenarioId} className="btn-primary">{busy ? 'Adding…' : 'Add and find options'}</button>
              <button type="button" onClick={() => setShowNew(false)} className="btn-ghost">Cancel</button>
            </div>
          </form>
        </Panel>
      )}

      <StatStrip
        loading={loading}
        items={[
          { label: 'Missions', value: tasks.length },
          { label: 'Critical', value: byPriority('CRITICAL'), tone: byPriority('CRITICAL') ? 'crit' : 'default' },
          { label: 'High', value: byPriority('HIGH'), tone: byPriority('HIGH') ? 'warn' : 'default' },
          { label: 'Medium / low', value: byPriority('MEDIUM') + byPriority('LOW') },
          { label: 'In the plan', value: tasks.length - unplanned.length, tone: 'ok' },
          { label: 'Not in the plan', value: unplanned.length, tone: unplanned.length ? 'warn' : 'default', hint: unplanned.length ? 'use Options to assign' : undefined },
        ]}
      />

      <Panel
        title="Mission list"
        right={
          <div className="flex items-center gap-2 print:hidden">
            <div className="relative">
              <Search className="w-3 h-3 text-slate-500 absolute left-2 top-1/2 -translate-y-1/2" />
              <input className="field h-7 pl-6 w-48" placeholder="Name or capability" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search missions" />
            </div>
            <select className="field h-7" value={priorityFilter} onChange={(e) => setPriorityFilter(e.target.value)} aria-label="Filter by priority">
              <option value="ALL">All priorities</option>
              {PRIORITIES.map((p) => <option key={p} value={p}>{p.charAt(0) + p.slice(1).toLowerCase()}</option>)}
            </select>
          </div>
        }
      >
        {loading ? (
          <SkeletonTable rows={10} cols={7} />
        ) : tasks.length === 0 ? (
          <EmptyState title="No missions" description="Add a mission above, or import them from Data import." />
        ) : filtered.length === 0 ? (
          <EmptyState compact title="No matches" description="Try a different name, capability or priority." />
        ) : (
          <div className="overflow-x-auto">
            <table className="data-table w-full text-xs">
              <thead>
                <tr>
                  <th>Mission</th>
                  <th>Priority</th>
                  <th className="text-right">Duration</th>
                  <th>Window</th>
                  <th>Needs</th>
                  <th>In the active plan</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {filtered.map((t) => {
                  const p = planned[t.id];
                  return (
                    <React.Fragment key={t.id}>
                      <tr className={open === t.id ? 'bg-slate-900' : 'hover:bg-slate-900'}>
                        <td>
                          <div className="text-slate-100">{t.name}</div>
                          <div className="font-mono text-[10px] text-slate-500">{t.location_id ? siteName[t.location_id] : 'no site'} · {shortId(t.id)}</div>
                        </td>
                        <td><Badge status={t.priority} /></td>
                        <td className="text-right font-mono text-slate-300">{fmtMinutes(t.duration_minutes)}</td>
                        <td className="font-mono text-slate-400 whitespace-nowrap">{fmtZulu(t.earliest_start)} → {fmtZuluTime(t.latest_finish)}</td>
                        <td>
                          <div className="flex flex-wrap gap-1">
                            {t.requirements.length === 0 && <span className="text-slate-600">—</span>}
                            {t.requirements.map((r, i) => (
                              <span key={i} className="px-1.5 border border-slate-700 font-mono text-[10px] text-slate-400">{r.requirement_value}</span>
                            ))}
                          </div>
                        </td>
                        <td className="whitespace-nowrap">
                          {p ? (
                            <span className="text-slate-300"><span className="font-mono">{p.resource}</span> · {fmtZuluTime(p.start)}{p.crew ? <span className="text-slate-500"> · {p.crew}</span> : null}</span>
                          ) : (
                            <span className="text-warn">not planned</span>
                          )}
                        </td>
                        <td className="text-right">
                          <button onClick={() => showOptions(t)} className={p ? 'btn-ghost h-7 px-2' : 'btn-secondary h-7 px-2'}>
                            {open === t.id ? 'Close' : p ? 'Options' : 'Find options'}
                          </button>
                        </td>
                      </tr>
                      {open === t.id && (
                        <tr>
                          <td colSpan={7} className="bg-slate-950">
                            {optLoading || !options ? (
                              <SkeletonTable rows={3} cols={5} />
                            ) : (
                              <div className="p-2 space-y-2">
                                <div className="text-slate-400">
                                  Options that fit around plan v{options.plan_version ?? '—'} without moving any other sortie, earliest first.
                                  {options.currently && ' This mission is already planned; choosing another option moves it.'}
                                </div>
                                {options.stores_short.length > 0 && (
                                  <div className="text-crit">Not enough stores: {options.stores_short.join('; ')}. Raise stock in Crews &amp; stores or free them by re-planning.</div>
                                )}
                                {options.options.length === 0 ? (
                                  <div className="text-warn">
                                    No aircraft and crew can take it without changes to other sorties.{' '}
                                    <Link to="/courses-of-action" className="underline">Re-plan everything in Courses of action →</Link>
                                  </div>
                                ) : (
                                  <table className="w-full">
                                    <thead>
                                      <tr className="text-slate-500 text-left">
                                        <th className="py-1 font-normal">Aircraft</th>
                                        <th className="font-normal">Crew</th>
                                        <th className="font-normal">Flies</th>
                                        <th className="font-normal">Delay</th>
                                        <th className="font-normal">Risk</th>
                                        <th />
                                      </tr>
                                    </thead>
                                    <tbody>
                                      {options.options.map((o, i) => (
                                        <tr key={o.resource_id} className="border-t border-slate-800">
                                          <td className="py-1.5">
                                            <span className="font-mono text-slate-100">{o.resource_name}</span>
                                            <span className="text-slate-500"> {o.model ?? o.resource_type.replace(/_/g, ' ').toLowerCase()}</span>
                                            {i === 0 && <Badge status="earliest" tone="ok" className="ml-2" />}
                                          </td>
                                          <td className="text-slate-300">{o.crew_name ?? '—'}</td>
                                          <td className="font-mono text-slate-300 whitespace-nowrap">{fmtZulu(o.start_at)}–{fmtZuluTime(o.end_at)}</td>
                                          <td className={`font-mono ${o.delay_minutes > 60 ? 'text-warn' : 'text-slate-400'}`}>{o.delay_minutes} min</td>
                                          <td title={o.risk_factors.join('\n')}>
                                            <span className={`font-mono ${o.risk >= 45 ? 'text-crit' : o.risk >= 25 ? 'text-warn' : 'text-slate-300'}`}>{o.risk}%</span>
                                            {o.risk_factors[0] && <span className="text-slate-500"> · {o.risk_factors[0]}</span>}
                                          </td>
                                          <td className="text-right">
                                            <button onClick={() => assign(t, o)} disabled={busy} className="btn-primary h-7 px-2">Assign</button>
                                          </td>
                                        </tr>
                                      ))}
                                    </tbody>
                                  </table>
                                )}
                                {options.ruled_out.length > 0 && (
                                  <details className="text-slate-500">
                                    <summary className="cursor-pointer">{options.ruled_out.length} aircraft ruled out, and why</summary>
                                    <ul className="mt-1 grid md:grid-cols-2 gap-x-6">
                                      {options.ruled_out.map((r) => (
                                        <li key={r.aircraft}><span className="font-mono text-slate-400">{r.aircraft}</span>: {r.reason}</li>
                                      ))}
                                    </ul>
                                  </details>
                                )}
                              </div>
                            )}
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
};
