import React, { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../../api/client';
import { Resource, Task, Disruption } from '../../types/api';
import {
  EmptyState,
  ErrorState,
  Notice,
  PageHeader,
  Panel,
  SkeletonPage,
  SkeletonTable,
  fmtZulu,
} from '../../components/ui';

type DisruptionType = 'RESOURCE_UNAVAILABLE' | 'WINDOW_SHIFT' | 'DURATION_SURGE' | 'DEADLINE_TIGHTEN';

const TYPES: { value: DisruptionType; label: string; help: string }[] = [
  { value: 'RESOURCE_UNAVAILABLE', label: 'Resource grounded', help: 'Marks the resource GROUNDED; every assignment on it becomes a conflict.' },
  { value: 'WINDOW_SHIFT', label: 'Availability blackout', help: 'Removes the resource for the next 8 hours (e.g. runway or bay closure).' },
  { value: 'DURATION_SURGE', label: 'Task takes longer', help: 'Extends a task, e.g. headwinds or a slow turnaround.' },
  { value: 'DEADLINE_TIGHTEN', label: 'Deadline brought forward', help: 'Moves a task’s latest finish earlier.' },
];

const typeLabel = (t: string) => TYPES.find((x) => x.value === t)?.label ?? t;

const describe = (d: Disruption, resources: Resource[], tasks: Task[]) => {
  const p = d.payload_json ?? {};
  const res = resources.find((r) => r.id === p.resource_id)?.name;
  const task = tasks.find((t) => t.id === p.task_id)?.name;
  switch (d.type) {
    case 'RESOURCE_UNAVAILABLE':
      return `${res ?? 'Resource'} → ${p.new_status ?? 'GROUNDED'}`;
    case 'WINDOW_SHIFT':
      return `${res ?? 'Resource'} unavailable ${fmtZulu(p.blackout_start)} – ${fmtZulu(p.blackout_end)}`;
    case 'DURATION_SURGE':
      return `${task ?? 'Task'} +${p.surge_minutes} min`;
    case 'DEADLINE_TIGHTEN':
      return `${task ?? 'Task'} deadline −${p.tighten_hours} h`;
    default:
      return JSON.stringify(p);
  }
};

export const DisruptionSimulator: React.FC = () => {
  const navigate = useNavigate();
  const [resources, setResources] = useState<Resource[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [disruptions, setDisruptions] = useState<Disruption[]>([]);
  const [scenarioId, setScenarioId] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);
  const [notice, setNotice] = useState<{ tone: 'warn' | 'crit'; text: string } | null>(null);

  const [type, setType] = useState<DisruptionType>('RESOURCE_UNAVAILABLE');
  const [resourceId, setResourceId] = useState('');
  const [taskId, setTaskId] = useState('');
  const [surgeMinutes, setSurgeMinutes] = useState(60);
  const [tightenHours, setTightenHours] = useState(4);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const scenarios = await api.getScenarios();
      if (!scenarios.length) return;
      const sc = scenarios[0];
      setScenarioId(sc.id);
      const [res, tsk, dis] = await Promise.all([
        api.getResources(sc.id),
        api.getTasks(sc.id),
        api.getDisruptions(sc.id),
      ]);
      setResources(res);
      setTasks(tsk);
      setDisruptions(dis);
      setResourceId((cur) => cur || res[0]?.id || '');
      setTaskId((cur) => cur || tsk[0]?.id || '');
    } catch (err: any) {
      setError(err?.message || 'Could not load scenario data.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleApply = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!scenarioId) return;
    setApplying(true);
    setNotice(null);

    const payload: Record<string, unknown> =
      type === 'RESOURCE_UNAVAILABLE'
        ? { resource_id: resourceId, new_status: 'GROUNDED' }
        : type === 'WINDOW_SHIFT'
          ? {
              resource_id: resourceId,
              blackout_start: new Date().toISOString(),
              blackout_end: new Date(Date.now() + 8 * 3600 * 1000).toISOString(),
            }
          : type === 'DURATION_SURGE'
            ? { task_id: taskId, surge_minutes: Number(surgeMinutes) }
            : { task_id: taskId, tighten_hours: Number(tightenHours) };

    try {
      await api.injectDisruption(scenarioId, type, payload);
      setNotice({ tone: 'warn', text: 'Disruption applied. The current schedule has been re-validated.' });
      setDisruptions(await api.getDisruptions(scenarioId));
      setResources(await api.getResources(scenarioId));
    } catch (err: any) {
      setNotice({ tone: 'crit', text: err?.message || 'Could not apply disruption.' });
    } finally {
      setApplying(false);
    }
  };

  if (loading) return <SkeletonPage />;

  const needsResource = type === 'RESOURCE_UNAVAILABLE' || type === 'WINDOW_SHIFT';

  return (
    <div className="space-y-4">
      <PageHeader
        title="Disruptions"
        subtitle="Record an event that invalidates part of the plan, then let the optimiser propose a repair."
        actions={
          <button onClick={() => navigate('/optimisation')} className="btn-primary">
            Run optimiser
          </button>
        }
      />

      {error && <ErrorState message={error} onRetry={load} />}

      {notice && (
        <Notice tone={notice.tone} onDismiss={() => setNotice(null)}>
          {notice.text}{' '}
          {notice.tone === 'warn' && (
            <Link to="/schedule" className="underline">
              View conflicts on the timeline
            </Link>
          )}
        </Notice>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-12 gap-4">
        <Panel title="New disruption" className="xl:col-span-5">
          <form onSubmit={handleApply} className="p-3 space-y-3 text-xs">
            <fieldset>
              <legend className="label">Event type</legend>
              <div className="space-y-1">
                {TYPES.map((t) => (
                  <label
                    key={t.value}
                    className={`flex items-start gap-2.5 px-2.5 py-2 border cursor-pointer ${
                      type === t.value ? 'border-indigo-500 bg-indigo-950/40' : 'border-slate-800 hover:border-slate-700'
                    }`}
                  >
                    <input
                      type="radio"
                      name="type"
                      value={t.value}
                      checked={type === t.value}
                      onChange={() => setType(t.value)}
                      className="mt-0.5 accent-indigo-500"
                    />
                    <span>
                      <span className="block text-slate-200">{t.label}</span>
                      <span className="block text-slate-500">{t.help}</span>
                    </span>
                  </label>
                ))}
              </div>
            </fieldset>

            {needsResource ? (
              <div>
                <label className="label" htmlFor="d-res">
                  Resource
                </label>
                <select id="d-res" className="field w-full" value={resourceId} onChange={(e) => setResourceId(e.target.value)}>
                  {resources.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.name} · {r.status.toLowerCase()}
                    </option>
                  ))}
                </select>
              </div>
            ) : (
              <div className="grid grid-cols-[1fr_120px] gap-2">
                <div>
                  <label className="label" htmlFor="d-task">
                    Task
                  </label>
                  <select id="d-task" className="field w-full" value={taskId} onChange={(e) => setTaskId(e.target.value)}>
                    {tasks.map((t) => (
                      <option key={t.id} value={t.id}>
                        {t.name} · {t.duration_minutes}m
                      </option>
                    ))}
                  </select>
                </div>
                {type === 'DURATION_SURGE' ? (
                  <div>
                    <label className="label" htmlFor="d-surge">
                      Extra minutes
                    </label>
                    <input
                      id="d-surge"
                      type="number"
                      min={15}
                      step={15}
                      className="field w-full font-mono"
                      value={surgeMinutes}
                      onChange={(e) => setSurgeMinutes(Number(e.target.value))}
                    />
                  </div>
                ) : (
                  <div>
                    <label className="label" htmlFor="d-tight">
                      Hours earlier
                    </label>
                    <input
                      id="d-tight"
                      type="number"
                      min={1}
                      max={12}
                      className="field w-full font-mono"
                      value={tightenHours}
                      onChange={(e) => setTightenHours(Number(e.target.value))}
                    />
                  </div>
                )}
              </div>
            )}

            <div className="flex items-center justify-between pt-1">
              <span className="text-slate-500">Applies to the active scenario immediately.</span>
              <button type="submit" disabled={applying || (needsResource ? !resourceId : !taskId)} className="btn-primary">
                {applying ? 'Applying…' : 'Apply disruption'}
              </button>
            </div>
          </form>
        </Panel>

        <Panel title="Disruption log" right={`${disruptions.length} recorded`} className="xl:col-span-7">
          {loading ? (
            <SkeletonTable rows={4} cols={3} />
          ) : disruptions.length === 0 ? (
            <EmptyState compact title="Nothing recorded" description="Disruptions you apply appear here in order." />
          ) : (
            <div className="overflow-auto max-h-[480px]">
              <table className="data-table w-full text-xs">
                <thead className="sticky top-0 bg-slate-925">
                  <tr>
                    <th>Logged</th>
                    <th>Type</th>
                    <th>Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {[...disruptions]
                    .sort((a, b) => b.created_at.localeCompare(a.created_at))
                    .map((d) => (
                      <tr key={d.id}>
                        <td className="font-mono text-slate-500 whitespace-nowrap">{fmtZulu(d.created_at)}</td>
                        <td className="text-warn whitespace-nowrap">{typeLabel(d.type)}</td>
                        <td className="text-slate-300">{describe(d, resources, tasks)}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
};
