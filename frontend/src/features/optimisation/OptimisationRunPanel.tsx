import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../../api/client';
import { ScheduleVersion, OptimisationRun, ScheduleComparison } from '../../types/api';
import {
  Badge,
  EmptyState,
  ErrorState,
  Notice,
  PageHeader,
  Panel,
  SkeletonPage,
  StatStrip,
  shortId,
} from '../../components/ui';
import { ComparisonView } from './ComparisonView';

const WEIGHTS = [
  { key: 'unassigned', label: 'Unassigned task penalty', help: 'Cost of leaving a task without a slot', def: 10000 },
  { key: 'churn', label: 'Change penalty', help: 'Cost of moving a task off its baseline resource', def: 50 },
  { key: 'delay', label: 'Delay penalty', help: 'Cost per minute a task starts after its window opens', def: 5 },
] as const;

type WeightKey = (typeof WEIGHTS)[number]['key'];

export const OptimisationRunPanel: React.FC = () => {
  const navigate = useNavigate();
  const [schedules, setSchedules] = useState<ScheduleVersion[]>([]);
  const [scheduleId, setScheduleId] = useState('');
  const [run, setRun] = useState<OptimisationRun | null>(null);
  const [comparison, setComparison] = useState<ScheduleComparison | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [solveError, setSolveError] = useState<string | null>(null);
  const [solving, setSolving] = useState(false);
  const [tab, setTab] = useState<'changes' | 'solver'>('changes');

  const [weights, setWeights] = useState<Record<WeightKey, number>>({ unassigned: 10000, churn: 50, delay: 5 });
  const [timeLimit, setTimeLimit] = useState(15);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const scenarios = await api.getScenarios();
      if (!scenarios.length) return;
      const list = await api.getScenarioSchedules(scenarios[0].id);
      setSchedules(list);
      setScheduleId((cur) => cur || list[0]?.id || '');
    } catch (err: any) {
      setError(err?.message || 'Could not load schedule versions.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleSolve = async () => {
    if (!scheduleId) return;
    setSolving(true);
    setSolveError(null);
    try {
      const res = await api.triggerOptimisation(scheduleId, {
        solver_time_limit_seconds: Number(timeLimit),
        weight_unassigned: weights.unassigned,
        weight_delay: weights.delay,
        weight_churn: weights.churn,
      });
      setRun(res);
      setComparison(await api.getComparison(res.id));
      setTab('changes');
    } catch (err: any) {
      setSolveError(err?.message || 'Optimisation run failed.');
    } finally {
      setSolving(false);
    }
  };

  if (loading) return <SkeletonPage panels={1} />;

  const m = run?.metrics_json ?? {};

  return (
    <div className="space-y-4">
      <PageHeader
        title="Optimiser"
        subtitle="Builds a repaired schedule with OR-Tools CP-SAT. The result is a new proposed version; nothing changes until it is approved."
        actions={
          run?.status === 'COMPLETED' && (
            <button onClick={() => navigate('/review')} className="btn-primary">
              Send to review
            </button>
          )
        }
      />

      {error && <ErrorState message={error} onRetry={load} />}

      {schedules.length === 0 && !error ? (
        <Panel>
          <EmptyState title="No schedule to optimise" description="The active scenario has no schedule versions yet." />
        </Panel>
      ) : (
        <Panel title="Run settings">
          <div className="p-3 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-[220px_repeat(3,1fr)_120px_auto] gap-3 items-end text-xs">
            <div>
              <label className="label" htmlFor="opt-src">
                Start from version
              </label>
              <select id="opt-src" className="field w-full font-mono" value={scheduleId} onChange={(e) => setScheduleId(e.target.value)}>
                {schedules.map((s) => (
                  <option key={s.id} value={s.id}>
                    v{s.version_number} · {s.status.toLowerCase()}
                  </option>
                ))}
              </select>
            </div>
            {WEIGHTS.map((w) => (
              <div key={w.key}>
                <label className="label" htmlFor={`w-${w.key}`} title={w.help}>
                  {w.label}
                </label>
                <input
                  id={`w-${w.key}`}
                  type="number"
                  min={0}
                  className="field w-full font-mono"
                  value={weights[w.key]}
                  onChange={(e) => setWeights((cur) => ({ ...cur, [w.key]: Number(e.target.value) }))}
                />
              </div>
            ))}
            <div>
              <label className="label" htmlFor="opt-time">
                Time limit (s)
              </label>
              <input
                id="opt-time"
                type="number"
                min={1}
                max={120}
                className="field w-full font-mono"
                value={timeLimit}
                onChange={(e) => setTimeLimit(Number(e.target.value))}
              />
            </div>
            <button onClick={handleSolve} disabled={solving || !scheduleId} className="btn-primary">
              {solving ? 'Solving…' : 'Run solver'}
            </button>
          </div>
          {solving && (
            <div className="px-3 pb-3 text-xs text-slate-500">
              Searching for a feasible assignment. This can take up to {timeLimit}s.
            </div>
          )}
        </Panel>
      )}

      {solveError && <ErrorState message={solveError} onRetry={handleSolve} />}

      {run && (
        <>
          <StatStrip
            items={[
              {
                label: 'Solver status',
                value: run.solver_status ?? run.status,
                tone: run.solver_status === 'INFEASIBLE' ? 'crit' : run.solver_status === 'OPTIMAL' ? 'ok' : 'default',
              },
              { label: 'Assigned', value: `${m.assigned_tasks ?? 0}/${m.total_tasks ?? '—'}` },
              { label: 'Unassigned', value: m.unassigned_tasks ?? 0, tone: m.unassigned_tasks ? 'warn' : 'default' },
              { label: 'Objective', value: run.objective_value != null ? Math.round(run.objective_value) : '—' },
              { label: 'Runtime', value: `${(m.execution_time_seconds ?? 0).toFixed(2)}s` },
              {
                label: 'Validator',
                value: run.validation?.is_valid ? 'Pass' : 'Fail',
                tone: run.validation?.is_valid ? 'ok' : 'crit',
                hint: `${run.validation?.conflict_count ?? 0} conflicts`,
              },
            ]}
          />

          {run.advisory_explanation && (
            <Notice tone="info">
              <div className="font-medium mb-1">Why the solver made these changes</div>
              <p className="whitespace-pre-line text-slate-300 leading-relaxed">{run.advisory_explanation}</p>
              <p className="mt-1 text-slate-500">Generated from the solver output, not a language model.</p>
            </Notice>
          )}

          <div className="flex items-center gap-1 border-b border-slate-800" role="tablist">
            {(
              [
                ['changes', 'Changes vs baseline'],
                ['solver', 'Solver detail'],
              ] as const
            ).map(([key, label]) => (
              <button
                key={key}
                role="tab"
                aria-selected={tab === key}
                onClick={() => setTab(key)}
                className={`h-8 px-3 text-xs -mb-px border-b-2 ${
                  tab === key ? 'border-indigo-400 text-slate-100' : 'border-transparent text-slate-500 hover:text-slate-300'
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          {tab === 'changes' &&
            (comparison ? (
              <ComparisonView comparison={comparison} />
            ) : (
              <Panel>
                <EmptyState compact title="No comparison available" />
              </Panel>
            ))}

          {tab === 'solver' && (
            <Panel title="Solver detail">
              <table className="data-table w-full text-xs">
                <tbody>
                  <tr>
                    <td className="text-slate-500 w-64">Run ID</td>
                    <td className="font-mono text-slate-300">{run.id}</td>
                  </tr>
                  <tr>
                    <td className="text-slate-500">New schedule version</td>
                    <td className="font-mono text-slate-300">{run.new_schedule_version_id ?? '—'}</td>
                  </tr>
                  <tr>
                    <td className="text-slate-500">Status</td>
                    <td>
                      <Badge status={run.status} />
                    </td>
                  </tr>
                  <tr>
                    <td className="text-slate-500">Search branches</td>
                    <td className="font-mono text-slate-300">{m.branches ?? '—'}</td>
                  </tr>
                  <tr>
                    <td className="text-slate-500">Conflicts learned</td>
                    <td className="font-mono text-slate-300">{m.conflicts ?? '—'}</td>
                  </tr>
                  <tr>
                    <td className="text-slate-500">Source version</td>
                    <td className="font-mono text-slate-300">{shortId(run.schedule_version_id)}</td>
                  </tr>
                  {run.error_summary && (
                    <tr>
                      <td className="text-slate-500">Error</td>
                      <td className="text-crit">{run.error_summary}</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </Panel>
          )}
        </>
      )}
    </div>
  );
};
