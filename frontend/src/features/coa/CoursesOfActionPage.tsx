import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api/client';
import {
  Assignment,
  CoaKey,
  CoaMetrics,
  CoaSet,
  CourseOfAction,
  Resource,
  Scenario,
  ScheduleVersion,
  WeatherAlertItem,
} from '../../types/api';
import {
  Badge,
  EmptyState,
  ErrorState,
  Notice,
  PageHeader,
  Panel,
  Skeleton,
  SkeletonTable,
  fmtZulu,
} from '../../components/ui';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { ScheduleTimeline } from '../schedule/ScheduleTimeline';
import { TradeoffChart } from './TradeoffChart';

type Row = {
  label: string;
  metric?: keyof CoaMetrics;
  render: (m: CoaMetrics) => React.ReactNode;
  tone?: (m: CoaMetrics) => string;
};

const GROUPS: { title: string; rows: Row[] }[] = [
  {
    title: 'Coverage',
    rows: [
      { label: 'Tasks flown', render: (m) => `${m.assigned}/${m.assigned + m.unassigned}` },
      { label: 'Critical dropped', metric: 'unassigned_critical', render: (m) => m.unassigned_critical, tone: (m) => (m.unassigned_critical ? 'text-crit' : '') },
      { label: 'High dropped', metric: 'unassigned_high', render: (m) => m.unassigned_high, tone: (m) => (m.unassigned_high ? 'text-warn' : '') },
      { label: 'All dropped', metric: 'unassigned', render: (m) => m.unassigned },
    ],
  },
  {
    title: 'Timing',
    rows: [
      { label: 'Total delay', metric: 'total_delay_minutes', render: (m) => `${m.total_delay_minutes} min` },
      {
        label: 'Avg critical delay',
        metric: 'critical_avg_delay_minutes',
        render: (m) => (m.critical_avg_delay_minutes == null ? '—' : `${m.critical_avg_delay_minutes} min`),
      },
      { label: 'Last landing', render: (m) => fmtZulu(m.finish_at) },
    ],
  },
  {
    title: 'Change to current plan',
    rows: [
      { label: 'Aircraft swapped', metric: 'reassigned', render: (m) => m.reassigned },
      { label: 'Retimed', metric: 'retimed', render: (m) => m.retimed },
      { label: 'Unchanged', render: (m) => m.unchanged },
    ],
  },
  {
    title: 'Weather',
    rows: [
      {
        label: 'Sorties in critical hour',
        metric: 'weather_exposed_critical',
        render: (m) => m.weather_exposed_critical,
        tone: (m) => (m.weather_exposed_critical ? 'text-crit' : ''),
      },
      {
        label: 'Sorties in warning hour',
        metric: 'weather_exposed_warning',
        render: (m) => m.weather_exposed_warning,
        tone: (m) => (m.weather_exposed_warning ? 'text-warn' : ''),
      },
    ],
  },
  {
    title: 'Predicted risk',
    rows: [
      {
        label: 'High-risk sorties',
        metric: 'risk_high',
        render: (m) => m.risk_high ?? '—',
        tone: (m) => (m.risk_high ? 'text-crit' : ''),
      },
      {
        label: 'Average sortie risk',
        metric: 'risk_average',
        render: (m) => (m.risk_average == null ? '—' : `${m.risk_average}%`),
        tone: (m) => ((m.risk_average ?? 0) >= 25 ? 'text-warn' : ''),
      },
    ],
  },
  {
    title: 'Checks',
    rows: [
      {
        label: 'Independent validator',
        metric: 'validator_conflicts',
        render: (m) => (m.validator_pass ? 'Pass' : `${m.validator_conflicts} conflicts`),
        tone: (m) => (m.validator_pass ? 'text-ok' : 'text-crit'),
      },
    ],
  },
];

const changeTone: Record<string, 'default' | 'ok' | 'warn' | 'crit' | 'info'> = {
  UNCHANGED: 'default',
  REASSIGNED: 'info',
  RETIMED: 'warn',
  NEW: 'ok',
  DROPPED: 'crit',
  UNASSIGNED: 'crit',
};

const toAssignments = (c: CourseOfAction, taskSites: Record<string, string | null | undefined>): Assignment[] =>
  c.tasks
    .filter((t) => t.resource_id && t.start_at && t.end_at)
    .map((t) => ({
      id: `${c.key}-${t.task_id}`,
      schedule_version_id: c.key,
      task_id: t.task_id,
      resource_id: t.resource_id!,
      start_at: t.start_at!,
      end_at: t.end_at!,
      task_name: t.task_name,
      resource_name: t.resource_name ?? undefined,
      priority: t.priority,
      task_location_id: taskSites[t.task_id] ?? null,
    }));

export const CoursesOfActionPage: React.FC = () => {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenarioId, setScenarioId] = useState('');
  const [versions, setVersions] = useState<ScheduleVersion[]>([]);
  const [baselineId, setBaselineId] = useState('');
  const [resources, setResources] = useState<Resource[]>([]);
  const [taskSites, setTaskSites] = useState<Record<string, string | null | undefined>>({});
  const [alerts, setAlerts] = useState<WeatherAlertItem[]>([]);
  const [includeWeather, setIncludeWeather] = useState(true);

  const [coa, setCoa] = useState<CoaSet | null>(null);
  const [selected, setSelected] = useState<CoaKey | null>(null);
  const [tab, setTab] = useState<'timeline' | 'tasks'>('timeline');
  const [loading, setLoading] = useState(true);
  const [solving, setSolving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingAdopt, setPendingAdopt] = useState<CourseOfAction | null>(null);
  const [adopted, setAdopted] = useState<{ label: string; version: number | null } | null>(null);

  useEffect(() => {
    api
      .getScenarios()
      .then((s) => {
        setScenarios(s);
        if (s[0]) setScenarioId(s[0].id);
        else setLoading(false);
      })
      .catch((e) => {
        setError(e?.message || 'Could not load scenarios.');
        setLoading(false);
      });
  }, []);

  const loadScenario = useCallback(async () => {
    if (!scenarioId) return;
    setLoading(true);
    setError(null);
    setCoa(null);
    setAdopted(null);
    try {
      const [vs, res, tasks] = await Promise.all([
        api.getScenarioSchedules(scenarioId),
        api.getResources(scenarioId),
        api.getTasks(scenarioId),
      ]);
      setVersions(vs);
      setResources(res);
      setTaskSites(Object.fromEntries(tasks.map((t) => [t.id, t.location_id])));
      setBaselineId((vs.find((v) => v.status === 'APPROVED') ?? vs[0])?.id ?? '');
      api.getWeatherAlerts(scenarioId).then((r) => setAlerts(r.alerts || [])).catch(() => setAlerts([]));
    } catch (e: any) {
      setError(e?.message || 'Could not load the scenario.');
    } finally {
      setLoading(false);
    }
  }, [scenarioId]);

  useEffect(() => {
    loadScenario();
  }, [loadScenario]);

  const generate = async () => {
    if (!baselineId) return;
    setSolving(true);
    setError(null);
    setAdopted(null);
    try {
      const res = await api.generateCoursesOfAction(baselineId, includeWeather);
      setCoa(res);
      setSelected((res.courses.find((c) => c.recommended) ?? res.courses[0])?.key ?? null);
    } catch (e: any) {
      setError(e?.message || 'Could not generate plans.');
    } finally {
      setSolving(false);
    }
  };

  const adopt = async (c: CourseOfAction) => {
    setPendingAdopt(null);
    if (!coa) return;
    try {
      const r = await api.adoptCourseOfAction(coa.coa_set_id, c.key);
      setAdopted({ label: c.label, version: r.proposed_version_number });
      setVersions(await api.getScenarioSchedules(scenarioId));
    } catch (e: any) {
      setError(e?.message || 'Could not adopt the plan.');
    }
  };

  const current = coa?.courses.find((c) => c.key === selected) ?? null;
  const shown = current?.same_as ? coa?.courses.find((c) => c.key === current.same_as) ?? current : current;
  const assignments = useMemo(() => (shown ? toAssignments(shown, taskSites) : []), [shown, taskSites]);
  const isBest = (metric: keyof CoaMetrics | undefined, key: CoaKey) =>
    !!metric && !!coa?.best_by_metric[metric as string]?.includes(key);

  if (loading && !versions.length) return <SkeletonPageCoa />;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Courses of action"
        subtitle="Solve the same situation under different planning intents and compare the plans before committing to one."
        actions={
          <>
            <select className="field max-w-[240px]" value={scenarioId} onChange={(e) => setScenarioId(e.target.value)} aria-label="Scenario">
              {scenarios.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
            <select className="field font-mono" value={baselineId} onChange={(e) => setBaselineId(e.target.value)} aria-label="Start from version">
              {versions.map((v) => (
                <option key={v.id} value={v.id}>
                  from v{v.version_number} · {v.status.toLowerCase()}
                </option>
              ))}
            </select>
            <label className="flex items-center gap-1.5 text-xs text-slate-300 cursor-pointer">
              <input type="checkbox" checked={includeWeather} onChange={(e) => setIncludeWeather(e.target.checked)} className="accent-indigo-500" />
              Live weather
            </label>
            <button onClick={generate} disabled={solving || !baselineId} className="btn-primary">
              {solving ? 'Solving…' : coa ? 'Regenerate' : 'Generate plans'}
            </button>
          </>
        }
      />

      {error && <ErrorState message={error} onRetry={coa ? generate : loadScenario} />}

      {adopted && (
        <Notice tone="ok" onDismiss={() => setAdopted(null)}>
          “{adopted.label}” saved as proposed version v{adopted.version}. It is not active until a reviewer approves it.{' '}
          <Link to="/review" className="underline">
            Open review
          </Link>
        </Notice>
      )}

      {solving && (
        <Panel title="Solving">
          <div className="p-3 space-y-2 text-xs text-slate-400">
            <div>Running the CP-SAT solver once per intent, in parallel. Each plan is then checked by the independent validator.</div>
            <div className="grid grid-cols-4 gap-3">
              {['Fastest execution', 'Least disruption', 'Weather-safe', 'Critical missions first'].map((l) => (
                <div key={l} className="space-y-1.5">
                  <div className="text-slate-500">{l}</div>
                  <Skeleton className="h-16 w-full" />
                </div>
              ))}
            </div>
          </div>
        </Panel>
      )}

      {!coa && !solving && (
        <Panel>
          <EmptyState
            title="No plans generated yet"
            description="Pick the version to start from and generate. Nothing is saved until you adopt a plan, and an adopted plan still needs reviewer approval."
            action={
              <button onClick={generate} disabled={!baselineId} className="btn-primary">
                Generate plans
              </button>
            }
          />
        </Panel>
      )}

      {coa && !solving && (
        <>
          {coa.recommendation_reason && (
            <Notice tone="info">
              <span className="font-medium">Suggested: </span>
              {coa.recommendation_reason}{' '}
              <span className="text-slate-500">
                Rule: protect critical tasks, then avoid critical weather, then high-priority tasks, then fewer changes, then less delay.
              </span>
            </Notice>
          )}

          <div className="grid grid-cols-1 2xl:grid-cols-12 gap-4">
            <Panel
              title={`Comparison · from v${coa.baseline_version_number}`}
              right={`generated ${fmtZulu(coa.generated_at)} · ${coa.include_weather ? 'live weather applied' : 'weather ignored'}`}
              className="2xl:col-span-8"
            >
              <div className="overflow-x-auto">
                <table className="data-table w-full text-xs">
                  <thead>
                    <tr>
                      <th className="w-48" />
                      {coa.courses.map((c) => (
                        <th
                          key={c.key}
                          className={`!normal-case !tracking-normal !font-normal align-top cursor-pointer ${selected === c.key ? 'bg-slate-900' : ''}`}
                          onClick={() => setSelected(c.key)}
                        >
                          <div className="flex items-center gap-1.5">
                            <span className={`text-[13px] font-medium ${selected === c.key ? 'text-slate-100' : 'text-slate-300'}`}>{c.label}</span>
                            {c.recommended && <Badge status="Suggested" tone="info" />}
                          </div>
                          <div className="font-normal text-slate-500 whitespace-normal mt-0.5 max-w-[220px]">{c.intent}</div>
                          {c.same_as && <div className="font-normal text-warn whitespace-normal mt-1 max-w-[220px]">{c.note}</div>}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {GROUPS.map((g) => (
                      <React.Fragment key={g.title}>
                        <tr>
                          <td colSpan={coa.courses.length + 1} className="!pt-3 !pb-1 text-[10px] uppercase tracking-[0.08em] text-slate-500">
                            {g.title}
                          </td>
                        </tr>
                        {g.rows.map((r) => (
                          <tr key={r.label}>
                            <td className="text-slate-400">{r.label}</td>
                            {coa.courses.map((c) => (
                              <td
                                key={c.key}
                                className={`font-mono ${selected === c.key ? 'bg-slate-900' : ''} ${
                                  c.metrics && isBest(r.metric, c.key) && !c.same_as ? 'text-ok' : 'text-slate-200'
                                } ${c.metrics && r.tone ? r.tone(c.metrics) : ''}`}
                              >
                                {c.metrics ? r.render(c.metrics) : c.solver_status}
                                {c.metrics && isBest(r.metric, c.key) && !c.same_as && <span className="ml-1 text-[10px]">best</span>}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </React.Fragment>
                    ))}
                    <tr>
                      <td />
                      {coa.courses.map((c) => (
                        <td key={c.key} className={selected === c.key ? 'bg-slate-900' : ''}>
                          <button
                            onClick={() => setPendingAdopt(c)}
                            disabled={!c.metrics || !!c.same_as || !c.metrics.validator_pass}
                            className={c.recommended ? 'btn-primary h-7' : 'btn-secondary h-7'}
                          >
                            Adopt
                          </button>
                        </td>
                      ))}
                    </tr>
                  </tbody>
                </table>
              </div>
            </Panel>

            <Panel title="Trade-off" right="click a point to inspect" className="2xl:col-span-4">
              <div className="p-2">
                <TradeoffChart courses={coa.courses} selectedKey={selected} onSelect={setSelected} />
                <p className="px-2 pb-1 text-[11px] text-slate-500">
                  Bottom-left is better on both. Plans that came out identical are shown once.
                </p>
              </div>
            </Panel>
          </div>

          {shown && (
            <Panel
              title={`${current?.label ?? shown.label}${current?.same_as ? ` (same as ${shown.label})` : ''}`}
              right={
                <div className="flex border border-slate-800 print:hidden" role="tablist">
                  {(
                    [
                      ['timeline', 'Timeline'],
                      ['tasks', 'Task outcomes'],
                    ] as const
                  ).map(([k, l]) => (
                    <button
                      key={k}
                      role="tab"
                      aria-selected={tab === k}
                      onClick={() => setTab(k)}
                      className={`px-2 h-6 ${tab === k ? 'bg-slate-800 text-slate-100' : 'text-slate-500 hover:text-slate-300'}`}
                    >
                      {l}
                    </button>
                  ))}
                </div>
              }
            >
              {tab === 'timeline' ? (
                <ScheduleTimeline resources={resources} assignments={assignments} weatherAlerts={alerts} horizonHours={24} />
              ) : (
                <div className="overflow-auto max-h-[480px]">
                  <table className="data-table w-full text-xs">
                    <thead className="sticky top-0 bg-slate-925">
                      <tr>
                        <th>Task</th>
                        <th>Priority</th>
                        <th>Aircraft</th>
                        <th>Departs</th>
                        <th className="text-right">Delay</th>
                        <th>Change</th>
                        <th>Weather</th>
                      </tr>
                    </thead>
                    <tbody>
                      {[...shown.tasks]
                        .sort((a, b) => (a.start_at ?? 'z').localeCompare(b.start_at ?? 'z'))
                        .map((t) => (
                          <tr key={t.task_id}>
                            <td className="text-slate-200">{t.task_name}</td>
                            <td>
                              <Badge status={t.priority} />
                            </td>
                            <td className="font-mono text-slate-300">{t.resource_name ?? '—'}</td>
                            <td className="font-mono text-slate-400 whitespace-nowrap">{fmtZulu(t.start_at)}</td>
                            <td className="text-right font-mono text-slate-400">{t.delay_minutes ?? '—'}</td>
                            <td>
                              <Badge status={t.change} tone={changeTone[t.change]} />
                            </td>
                            <td className={`font-mono ${t.weather_exposure === 'CRITICAL' ? 'text-crit' : t.weather_exposure ? 'text-warn' : 'text-slate-600'}`}>
                              {t.weather_exposure?.toLowerCase() ?? '—'}
                            </td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Panel>
          )}
        </>
      )}

      <ConfirmDialog
        isOpen={pendingAdopt != null}
        title={`Adopt “${pendingAdopt?.label}”?`}
        description="The plan is saved as a new proposed schedule version and sent to review. Nothing changes in the active schedule until a reviewer approves it."
        confirmLabel="Adopt as proposal"
        onConfirm={() => pendingAdopt && adopt(pendingAdopt)}
        onCancel={() => setPendingAdopt(null)}
      />
    </div>
  );
};

const SkeletonPageCoa: React.FC = () => (
  <div className="space-y-4" role="status" aria-label="Loading">
    <Skeleton className="h-5 w-48" />
    <div className="panel">
      <SkeletonTable rows={8} cols={5} />
    </div>
  </div>
);
