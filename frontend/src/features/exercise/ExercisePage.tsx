import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Pause, Play, SkipForward, Square } from 'lucide-react';
import { api } from '../../api/client';
import {
  CoaKey,
  CoaSet,
  ExerciseEvent,
  ExerciseState,
  Resource,
  ScheduleVersion,
  User,
  WeatherAlertItem,
} from '../../types/api';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import {
  Badge,
  EmptyState,
  ErrorState,
  Notice,
  PageHeader,
  Panel,
  Skeleton,
  SkeletonPage,
  StatStrip,
} from '../../components/ui';
import { ScheduleTimeline } from '../schedule/ScheduleTimeline';

const POLL_MS = 1000;
const pad = (n: number) => String(Math.floor(n)).padStart(2, '0');
const zulu = (ms: number) => {
  const d = new Date(ms);
  return `${pad(d.getUTCHours())}${pad(d.getUTCMinutes())}Z`;
};
const tPlus = (mins: number) => `T+${pad(mins / 60)}:${pad(mins % 60)}`;

const canPlan = (u: User | null) => u?.role === 'PLANNER' || u?.role === 'ADMIN';
const canApprove = (u: User | null) => u?.role === 'REVIEWER' || u?.role === 'ADMIN';

export const ExercisePage: React.FC = () => {
  const [me, setMe] = useState<User | null>(null);
  const [state, setState] = useState<ExerciseState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [speed, setSpeed] = useState(60);
  const [busy, setBusy] = useState(false);
  const [confirmEnd, setConfirmEnd] = useState(false);

  const [resources, setResources] = useState<Resource[]>([]);
  const [schedule, setSchedule] = useState<ScheduleVersion | null>(null);
  const [alerts, setAlerts] = useState<WeatherAlertItem[]>([]);
  // Local clock between polls so the display moves smoothly
  const [tick, setTick] = useState(Date.now());
  const lastPoll = useRef<{ wall: number; sim: number } | null>(null);

  useEffect(() => {
    api.getMe().then(setMe).catch(() => setMe(null));
    api
      .latestExercise()
      .then((s) => s && setState(s))
      .catch(() => undefined)
      .finally(() => setLoading(false));
  }, []);

  // Poll the server: it advances the simulated clock and applies events
  useEffect(() => {
    if (!state || state.status === 'FINISHED') return;
    const id = window.setInterval(async () => {
      try {
        setState(await api.getExercise(state.id));
        setError(null);
      } catch (e: any) {
        setError(e?.message || 'Lost contact with the exercise.');
      }
    }, POLL_MS);
    return () => window.clearInterval(id);
  }, [state?.id, state?.status]);

  useEffect(() => {
    if (state) lastPoll.current = { wall: Date.now(), sim: new Date(state.sim_now).getTime() };
  }, [state?.sim_now]);

  useEffect(() => {
    const id = window.setInterval(() => setTick(Date.now()), 250);
    return () => window.clearInterval(id);
  }, []);

  const simMs = useMemo(() => {
    if (!state) return 0;
    const base = lastPoll.current ?? { wall: Date.now(), sim: new Date(state.sim_now).getTime() };
    return state.status === 'RUNNING' ? base.sim + (tick - base.wall) * state.speed : base.sim;
  }, [state, tick]);

  // Reload plan, fleet and weather when the scenario or active version changes, or an event lands
  const appliedCount = state?.events.filter((e) => e.status !== 'PENDING').length ?? 0;
  useEffect(() => {
    if (!state) return;
    api.getResources(state.scenario_id).then(setResources).catch(() => undefined);
  }, [state?.scenario_id, appliedCount]);
  useEffect(() => {
    if (!state?.active_version_id) return;
    api.getSchedule(state.active_version_id).then(setSchedule).catch(() => undefined);
  }, [state?.active_version_id, appliedCount]);
  useEffect(() => {
    if (!state) return;
    api.getWeatherAlerts(state.scenario_id).then((r) => setAlerts(r.alerts || [])).catch(() => undefined);
  }, [state?.scenario_id, appliedCount]);

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      setState(await api.startExercise(speed));
    } catch (e: any) {
      setError(e?.message || 'Could not start the exercise.');
    } finally {
      setBusy(false);
    }
  };

  const controlAction = async (action: 'pause' | 'resume' | 'speed' | 'skip', s?: number) => {
    if (!state) return;
    try {
      setState(await api.controlExercise(state.id, action, s));
    } catch (e: any) {
      setError(e?.message || 'Control failed.');
    }
  };

  const end = async () => {
    setConfirmEnd(false);
    if (!state) return;
    try {
      await api.closeExercise(state.id);
      setState(null);
      setSchedule(null);
    } catch (e: any) {
      setError(e?.message || 'Could not close the exercise.');
    }
  };

  if (loading) return <SkeletonPage />;

  if (!state) {
    return (
      <div className="space-y-4">
        <PageHeader
          title="Live exercise"
          subtitle="Play a day of operations on a fast clock. Events land unannounced; the system replans and you decide."
        />
        {error && <ErrorState message={error} />}
        <Panel title="Exercise WINTER LIFT · day one">
          <div className="p-4 grid grid-cols-1 lg:grid-cols-2 gap-6 text-xs">
            <div className="space-y-3 text-slate-300">
              <p>
                Seven aircraft, six mountain sites and 21 tasks over the next day. During the exercise the fleet,
                the weather and the task list will change without warning. After each change the system checks the
                active plan, solves four courses of action from the current moment, and suggests one.
              </p>
              <ul className="space-y-1 text-slate-400 list-disc pl-4">
                <li>Runs on a copy of the scenario; the original is not touched.</li>
                <li>Weather is live; any simulated weather is labelled “exercise inject”.</li>
                <li>Sorties already airborne are never replanned.</li>
                <li>Nothing becomes active without approval by a reviewer or admin.</li>
              </ul>
            </div>
            <div className="space-y-3">
              <div>
                <div className="label">Clock speed</div>
                <div className="flex border border-slate-800 w-fit" role="group">
                  {[30, 60, 120, 240].map((s) => (
                    <button
                      key={s}
                      onClick={() => setSpeed(s)}
                      className={`px-3 h-8 font-mono ${speed === s ? 'bg-slate-800 text-slate-100' : 'text-slate-500 hover:text-slate-300'}`}
                    >
                      {s}×
                    </button>
                  ))}
                </div>
                <div className="text-slate-500 mt-1">
                  At {speed}× the 10-hour script plays in about {Math.round(600 / speed)} minutes.
                </div>
              </div>
              <button onClick={start} disabled={busy || !canPlan(me)} className="btn-primary h-9 px-4">
                {busy ? 'Preparing copy…' : 'Start exercise'}
              </button>
              {!canPlan(me) && <div className="text-warn">Sign in as a planner or admin to run an exercise.</div>}
              {me?.role === 'PLANNER' && (
                <div className="text-slate-500">
                  Planners can adopt plans; approving them needs a reviewer. Sign in as admin to do both yourself.
                </div>
              )}
            </div>
          </div>
        </Panel>
      </div>
    );
  }

  const t0 = new Date(state.sim_t0).getTime();
  const elapsedMin = Math.max(0, (simMs - t0) / 60000);
  const s = state.summary;
  const pending = state.events.filter((e) => e.status === 'PENDING');
  const shown = state.events.filter((e) => e.status !== 'PENDING');
  const awaiting = shown.filter((e) => e.status === 'READY' || e.decision?.stage === 'ADOPTED').length;

  return (
    <div className="space-y-4">
      <div className="panel flex flex-wrap items-center justify-between gap-4 px-4 py-3 sticky top-0 z-40">
        <div className="flex items-baseline gap-4">
          <span className="font-mono text-2xl text-slate-100 tabular-nums">{zulu(simMs)}</span>
          <span className="font-mono text-sm text-slate-400">{tPlus(Math.min(elapsedMin, state.end_min))}</span>
          <Badge status={state.status} tone={state.status === 'RUNNING' ? 'ok' : state.status === 'PAUSED' ? 'warn' : 'default'} />
          <span className="text-xs text-slate-500 hidden md:inline">{state.title}</span>
        </div>
        {state.status !== 'FINISHED' && (
          <div className="flex items-center gap-2 text-xs">
            {state.status === 'RUNNING' ? (
              <button onClick={() => controlAction('pause')} className="btn-secondary" title="Pause">
                <Pause className="w-3.5 h-3.5" /> Pause
              </button>
            ) : (
              <button onClick={() => controlAction('resume')} className="btn-primary" title="Resume">
                <Play className="w-3.5 h-3.5" /> Resume
              </button>
            )}
            <div className="flex border border-slate-800" role="group" aria-label="Clock speed">
              {state.speeds.map((sp) => (
                <button
                  key={sp}
                  onClick={() => controlAction('speed', sp)}
                  className={`px-2 h-8 font-mono ${state.speed === sp ? 'bg-slate-800 text-slate-100' : 'text-slate-500 hover:text-slate-300'}`}
                >
                  {sp}×
                </button>
              ))}
            </div>
            <button onClick={() => controlAction('skip')} disabled={!pending.length} className="btn-secondary" title="Jump to the next event">
              <SkipForward className="w-3.5 h-3.5" /> Next event
            </button>
          </div>
        )}
        <button onClick={() => setConfirmEnd(true)} className="btn-ghost text-xs">
          <Square className="w-3 h-3" /> End exercise
        </button>
      </div>

      {error && <ErrorState message={error} />}
      {awaiting > 0 && state.status === 'RUNNING' && (
        <Notice tone="warn">
          {awaiting} event{awaiting > 1 ? 's are' : ' is'} waiting for a decision. The clock keeps running; pause if you need time.
        </Notice>
      )}

      <StatStrip
        items={[
          { label: 'Events', value: `${shown.length}/${state.events.length}`, hint: pending.length ? `next ${tPlus(pending[0].at_min)}` : 'script complete' },
          { label: 'Replans', value: s.replans, hint: s.avg_replan_seconds != null ? `avg ${s.avg_replan_seconds}s to plans` : '—' },
          { label: 'Decisions', value: s.decisions, hint: s.avg_decision_seconds != null ? `avg ${s.avg_decision_seconds}s after event` : '—' },
          { label: 'Active plan', value: s.active_version != null ? `v${s.active_version}` : '—' },
          {
            label: 'Rule conflicts',
            value: s.active_conflicts ?? '—',
            tone: s.active_conflicts ? 'crit' : 'ok',
            hint: `${s.active_unassigned ?? 0} task(s) unscheduled`,
          },
          {
            label: 'Critical covered',
            value: `${s.critical_covered}/${s.critical_tasks}`,
            tone: s.critical_covered < s.critical_tasks ? 'warn' : 'ok',
          },
        ]}
      />

      {state.status === 'FINISHED' && <AfterAction state={state} />}

      <div className="grid grid-cols-1 2xl:grid-cols-12 gap-4">
        <Panel title="Event log" right={`${pending.length} still to come`} className="2xl:col-span-5">
          {shown.length === 0 ? (
            <EmptyState compact title="Quiet so far" description={`First event in ${Math.max(0, Math.round(pending[0]?.at_min - elapsedMin))} simulated minutes.`} />
          ) : (
            <ol className="divide-y divide-slate-800 max-h-[720px] overflow-y-auto">
              {[...shown].reverse().map((e) => (
                <EventRow key={e.idx} e={e} exercise={state} me={me} onChange={setState} onError={setError} />
              ))}
            </ol>
          )}
        </Panel>

        <Panel
          title={`Active plan${state.active_version_number ? ` · v${state.active_version_number}` : ''}`}
          right={<Link to="/weather" className="hover:text-slate-300">weather →</Link>}
          className="2xl:col-span-7"
        >
          {schedule ? (
            <ScheduleTimeline
              resources={resources}
              assignments={schedule.assignments}
              weatherAlerts={alerts}
              horizonHours={12}
              nowMs={simMs}
              startMs={t0}
            />
          ) : (
            <div className="p-3">
              <Skeleton className="h-64 w-full" />
            </div>
          )}
        </Panel>
      </div>

      <ConfirmDialog
        isOpen={confirmEnd}
        title="End the exercise?"
        description="The exercise copy of the scenario and everything decided in it will be deleted. The audit log keeps a record."
        confirmLabel="End and delete copy"
        isDestructive
        onConfirm={end}
        onCancel={() => setConfirmEnd(false)}
      />
    </div>
  );
};

const kindTone: Record<string, 'default' | 'warn' | 'crit' | 'info'> = {
  NOTE: 'default',
  AIRCRAFT_UNSERVICEABLE: 'crit',
  WEATHER_INJECT: 'warn',
  NEW_TASK: 'crit',
  DURATION_SURGE: 'warn',
  DEADLINE_TIGHTEN: 'warn',
};

const kindLabel: Record<string, string> = {
  NOTE: 'Info',
  AIRCRAFT_UNSERVICEABLE: 'Aircraft',
  WEATHER_INJECT: 'Weather',
  NEW_TASK: 'New task',
  DURATION_SURGE: 'Delay',
  DEADLINE_TIGHTEN: 'Deadline',
};

const EventRow: React.FC<{
  e: ExerciseEvent;
  exercise: ExerciseState;
  me: User | null;
  onChange: (s: ExerciseState) => void;
  onError: (m: string) => void;
}> = ({ e, exercise, me, onChange, onError }) => {
  const [coa, setCoa] = useState<CoaSet | null>(null);
  const [choice, setChoice] = useState<CoaKey | null>(null);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);

  const loadCoa = useCallback(async () => {
    if (!e.coa_set_id) return;
    try {
      const c = await api.getCoaSet(e.coa_set_id);
      setCoa(c);
      setChoice((cur) => cur ?? e.suggested_key ?? c.courses[0]?.key ?? null);
    } catch {
      /* set expired; buttons stay hidden */
    }
  }, [e.coa_set_id, e.suggested_key]);

  useEffect(() => {
    if (e.status === 'READY') loadCoa();
  }, [e.status, loadCoa]);

  const decide = async (action: 'adopt' | 'approve') => {
    setBusy(true);
    try {
      onChange(
        await api.decideExerciseEvent(exercise.id, e.idx, {
          action,
          course: action === 'adopt' ? choice ?? undefined : undefined,
          reason: action === 'approve' ? reason : undefined,
        }),
      );
    } catch (err: any) {
      onError(err?.message || 'Decision failed.');
    } finally {
      setBusy(false);
    }
  };

  const distinct = coa?.courses.filter((c) => c.metrics && !c.same_as) ?? [];

  return (
    <li className="px-3 py-3 text-xs space-y-2">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-mono text-slate-500">{tPlus(e.at_min)}</span>
            <Badge status={kindLabel[e.kind] ?? e.kind} tone={kindTone[e.kind] ?? 'default'} />
            <span className="text-slate-100 font-medium">{e.title}</span>
          </div>
          <p className="text-slate-400 mt-1">{e.detail}</p>
          {e.effect && <p className="text-slate-500 font-mono mt-0.5">{e.effect}</p>}
        </div>
      </div>

      {e.kind !== 'NOTE' && e.conflicts_after != null && (
        <div className="flex flex-wrap gap-3 font-mono text-[11px]">
          <span className={e.conflicts_after ? 'text-crit' : 'text-slate-500'}>{e.conflicts_after} rule conflicts</span>
          <span className={e.unassigned_after ? 'text-warn' : 'text-slate-500'}>{e.unassigned_after} unscheduled</span>
          <span className={e.weather_exposed_after ? 'text-crit' : 'text-slate-500'}>{e.weather_exposed_after} in critical weather</span>
        </div>
      )}

      {e.status === 'REPLANNING' && (
        <div className="space-y-1">
          <div className="text-slate-400">Solving courses of action from {e.applied_sim_at ? zulu(new Date(e.applied_sim_at).getTime()) : 'now'}…</div>
          <Skeleton className="h-8 w-full" />
        </div>
      )}

      {e.status === 'ERROR' && <div className="text-crit">{e.error}</div>}

      {e.status === 'READY' && e.replan_from_version && e.replan_from_version !== exercise.active_version_id && (
        <div className="text-slate-500">
          Plans for this event were built on an earlier version. v{exercise.active_version_number} was approved since, and later
          replans already include this change.
        </div>
      )}

      {e.status === 'READY' && (!e.replan_from_version || e.replan_from_version === exercise.active_version_id) && (
        <div className="border border-slate-800 bg-slate-950 p-2 space-y-2">
          <div className="text-slate-300">
            {distinct.length || '…'} distinct plan{distinct.length === 1 ? '' : 's'} ready in {e.replan_seconds}s.{' '}
            {e.suggested_label ? (
              <>
                Suggested: <span className="text-slate-100">{e.suggested_label}</span>.
              </>
            ) : (
              <span className="text-warn">No plan passes every check; review before adopting.</span>
            )}
          </div>
          {coa && (
            <div className="space-y-1">
              {distinct.map((c) => (
                <label key={c.key} className={`flex items-center gap-2 px-2 py-1 border cursor-pointer ${choice === c.key ? 'border-indigo-500' : 'border-slate-800'}`}>
                  <input type="radio" checked={choice === c.key} onChange={() => setChoice(c.key)} className="accent-indigo-500" />
                  <span className="w-36 shrink-0 text-slate-200">{c.label}</span>
                  <span className="font-mono text-[11px] text-slate-400">
                    {c.metrics!.unassigned} dropped · {c.metrics!.total_delay_minutes}m delay · {c.metrics!.reassigned + c.metrics!.retimed} changes
                    {c.metrics!.weather_exposed_critical > 0 && <span className="text-crit"> · {c.metrics!.weather_exposed_critical} in crit wx</span>}
                  </span>
                </label>
              ))}
            </div>
          )}
          {canPlan(me) ? (
            <button onClick={() => decide('adopt')} disabled={busy || !choice} className="btn-primary h-7">
              {busy ? 'Adopting…' : 'Adopt as proposal'}
            </button>
          ) : (
            <div className="text-slate-500">A planner must adopt a plan first.</div>
          )}
        </div>
      )}

      {e.decision?.stage === 'ADOPTED' && (
        <div className="border border-slate-800 bg-slate-950 p-2 space-y-2">
          <div className="text-slate-300">
            Proposal v{e.decision.version_number} adopted by {e.decision.by}. Awaiting approval.
          </div>
          {canApprove(me) ? (
            <div className="flex gap-2">
              <input
                className="field flex-1"
                placeholder={`Reason (optional) e.g. "Accept reroute after ${e.title.toLowerCase()}"`}
                value={reason}
                onChange={(ev) => setReason(ev.target.value)}
              />
              <button onClick={() => decide('approve')} disabled={busy} className="btn-primary h-8">
                {busy ? 'Approving…' : 'Approve'}
              </button>
            </div>
          ) : (
            <div className="text-slate-500">
              A reviewer approves this on the <Link to="/review" className="underline">Review</Link> page.
            </div>
          )}
        </div>
      )}

      {e.decision?.stage === 'APPROVED' && (
        <div className="text-ok">
          v{e.decision.version_number} active · approved by {e.decision.approved_by}
          {e.applied_wall_at && (
            <span className="text-slate-500">
              {' '}
              · {Math.round((new Date(e.decision.decided_wall_at).getTime() - new Date(e.applied_wall_at).getTime()) / 1000)}s from event
            </span>
          )}
        </div>
      )}
    </li>
  );
};

const AfterAction: React.FC<{ state: ExerciseState }> = ({ state }) => {
  const s = state.summary;
  return (
    <Panel title="After-action summary">
      <div className="p-3 grid grid-cols-1 lg:grid-cols-2 gap-4 text-xs">
        <table className="data-table w-full">
          <thead>
            <tr>
              <th />
              <th className="text-right">Original plan, untouched</th>
              <th className="text-right">Plan in force (v{s.active_version})</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td className="text-slate-400">Rule conflicts now</td>
              <td className={`text-right font-mono ${s.original_plan_conflicts ? 'text-crit' : ''}`}>{s.original_plan_conflicts ?? '—'}</td>
              <td className={`text-right font-mono ${s.active_conflicts ? 'text-crit' : 'text-ok'}`}>{s.active_conflicts ?? '—'}</td>
            </tr>
            <tr>
              <td className="text-slate-400">Tasks with no slot</td>
              <td className={`text-right font-mono ${s.original_plan_unassigned ? 'text-warn' : ''}`}>{s.original_plan_unassigned ?? '—'}</td>
              <td className="text-right font-mono">{s.active_unassigned ?? '—'}</td>
            </tr>
          </tbody>
        </table>
        <ul className="space-y-1 text-slate-300">
          <li>
            {s.events_applied} events, {s.replans} automatic replans, average {s.avg_replan_seconds ?? '—'}s from event to ready plans.
          </li>
          <li>
            {s.decisions} decisions recorded
            {s.avg_decision_seconds != null && `, average ${s.avg_decision_seconds}s from event to decision`}.
          </li>
          <li>
            {s.critical_covered} of {s.critical_tasks} critical tasks have a slot in the plan in force.
          </li>
          <li className="text-slate-500">All figures are measured in this exercise; none are estimated.</li>
        </ul>
      </div>
    </Panel>
  );
};
