import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api/client';
import { Scenario, ScheduleVersion, OptimisationRun, ScheduleComparison, WeatherAlertItem } from '../../types/api';
import { ComparisonView } from '../optimisation/ComparisonView';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import {
  ErrorState,
  Notice,
  PageHeader,
  Panel,
  SkeletonPage,
  StatStrip,
  fmtZulu,
} from '../../components/ui';

type Decision = 'APPROVED' | 'REJECTED';

export const SchedulingImpactPage: React.FC = () => {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenarioId, setScenarioId] = useState('');
  const [schedules, setSchedules] = useState<ScheduleVersion[]>([]);
  const [scheduleId, setScheduleId] = useState('');
  const [alerts, setAlerts] = useState<WeatherAlertItem[]>([]);
  const [run, setRun] = useState<OptimisationRun | null>(null);
  const [comparison, setComparison] = useState<ScheduleComparison | null>(null);

  const [includeWeather, setIncludeWeather] = useState(true);
  const [loading, setLoading] = useState(true);
  const [solving, setSolving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ tone: 'ok' | 'crit'; text: string } | null>(null);
  const [reason, setReason] = useState('');
  const [pending, setPending] = useState<Decision | null>(null);

  useEffect(() => {
    api
      .getScenarios()
      .then((s) => {
        setScenarios(s);
        if (s[0]) setScenarioId(s[0].id);
        else setLoading(false);
      })
      .catch((err) => {
        setError(err?.message || 'Could not load scenarios.');
        setLoading(false);
      });
  }, []);

  const loadScenario = useCallback(async () => {
    if (!scenarioId) return;
    setLoading(true);
    setError(null);
    try {
      const [scheds, alertResp] = await Promise.all([
        api.getScenarioSchedules(scenarioId),
        api.getWeatherAlerts(scenarioId),
      ]);
      setSchedules(scheds);
      setAlerts(alertResp.alerts || []);
      const baseline = scheds.find((s) => s.status === 'APPROVED') ?? scheds[0];
      setScheduleId(baseline?.id ?? '');
    } catch (err: any) {
      setError(err?.message || 'Could not load schedules or weather alerts.');
    } finally {
      setLoading(false);
    }
  }, [scenarioId]);

  useEffect(() => {
    loadScenario();
  }, [loadScenario]);

  const handleRun = async () => {
    if (!scheduleId) return;
    setSolving(true);
    setNotice(null);
    setRun(null);
    setComparison(null);
    try {
      const r = await api.triggerOptimisation(scheduleId, {
        include_weather: includeWeather,
        solver_time_limit_seconds: 30,
        weight_unassigned: 10000,
        weight_delay: 5,
        weight_churn: 50,
      });
      setRun(r);
      try {
        setComparison(await api.getComparison(r.id));
      } catch {
        /* no proposed version when the solve failed */
      }
    } catch (err: any) {
      setNotice({ tone: 'crit', text: err?.message || 'Solver run failed.' });
    } finally {
      setSolving(false);
    }
  };

  const decide = async (decision: Decision) => {
    setPending(null);
    if (!run) return;
    try {
      if (decision === 'APPROVED') await api.approveProposal(run.id, reason.trim());
      else await api.rejectProposal(run.id, reason.trim());
      setNotice({
        tone: 'ok',
        text: decision === 'APPROVED' ? 'Proposal approved and now active.' : 'Proposal rejected; the baseline is unchanged.',
      });
      setReason('');
      setSchedules(await api.getScenarioSchedules(scenarioId));
    } catch (err: any) {
      setNotice({ tone: 'crit', text: err?.message || 'The decision was not accepted.' });
    }
  };

  if (loading && !schedules.length) return <SkeletonPage panels={1} />;

  const crit = alerts.filter((a) => a.severity === 'CRITICAL');
  const warn = alerts.filter((a) => a.severity === 'WARNING');
  const sitesAffected = new Set(alerts.filter((a) => a.severity !== 'INFO').map((a) => a.location_id)).size;
  const firstCrit = crit.map((a) => a.forecast_timestamp).sort()[0];
  const wx = run?.metrics_json?.weather_constraints as { total_constraints?: number; freshness?: string } | undefined;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Schedule impact"
        subtitle="Re-solve the schedule with forecast limits as constraints: critical hours block a site, warnings add a penalty."
        actions={
          <>
            <select className="field max-w-[240px]" value={scenarioId} onChange={(e) => setScenarioId(e.target.value)} aria-label="Scenario">
              {scenarios.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
            <select className="field font-mono" value={scheduleId} onChange={(e) => setScheduleId(e.target.value)} aria-label="Schedule version">
              {schedules.map((s) => (
                <option key={s.id} value={s.id}>
                  v{s.version_number} · {s.status.toLowerCase()}
                </option>
              ))}
            </select>
          </>
        }
      />

      {error && <ErrorState message={error} onRetry={loadScenario} />}
      {notice && (
        <Notice tone={notice.tone} onDismiss={() => setNotice(null)}>
          {notice.text}
        </Notice>
      )}

      <StatStrip
        items={[
          { label: 'Critical hours', value: crit.length, tone: crit.length ? 'crit' : 'ok', hint: 'hard blackout' },
          { label: 'Warning hours', value: warn.length, tone: warn.length ? 'warn' : 'default', hint: 'soft penalty' },
          { label: 'Sites affected', value: sitesAffected },
          { label: 'First critical', value: firstCrit ? fmtZulu(firstCrit).slice(-5) : '—', hint: firstCrit ? fmtZulu(firstCrit).slice(0, 6) : 'none forecast' },
          { label: 'Constraints used', value: wx?.total_constraints ?? (run ? 0 : '—'), hint: 'last run' },
          { label: 'Data freshness', value: wx?.freshness ?? '—', tone: wx?.freshness === 'FRESH' ? 'ok' : wx?.freshness ? 'warn' : 'default' },
        ]}
      />

      <Panel title="Solve">
        <div className="p-3 flex flex-wrap items-center justify-between gap-3 text-xs">
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={includeWeather}
              onChange={(e) => setIncludeWeather(e.target.checked)}
              className="accent-indigo-500"
            />
            <span className="text-slate-200">Apply weather limits</span>
            <span className="text-slate-500">(untick to compare against a weather-blind solve)</span>
          </label>
          <div className="flex items-center gap-3">
            <Link to="/weather" className="text-slate-400 hover:text-slate-200">
              View forecast →
            </Link>
            <button onClick={handleRun} disabled={solving || !scheduleId} className="btn-primary">
              {solving ? 'Solving… (up to 30s)' : 'Run solver'}
            </button>
          </div>
        </div>
      </Panel>

      {run && (
        <>
          <StatStrip
            items={[
              {
                label: 'Solver status',
                value: run.solver_status ?? run.status,
                tone: run.solver_status === 'INFEASIBLE' ? 'crit' : run.solver_status === 'OPTIMAL' ? 'ok' : 'default',
              },
              { label: 'Objective', value: run.objective_value != null ? Math.round(run.objective_value) : '—' },
              { label: 'Runtime', value: `${(run.metrics_json?.execution_time_seconds ?? 0).toFixed(2)}s` },
              { label: 'Assigned', value: `${run.metrics_json?.assigned_tasks ?? 0}/${run.metrics_json?.total_tasks ?? '—'}` },
              {
                label: 'Validator',
                value: run.validation?.is_valid ? 'Pass' : 'Fail',
                tone: run.validation?.is_valid ? 'ok' : 'crit',
              },
              { label: 'Weather', value: includeWeather ? 'Applied' : 'Ignored' },
            ]}
          />

          {run.advisory_explanation && (
            <Notice tone="info">
              <p className="whitespace-pre-line text-slate-300 leading-relaxed">{run.advisory_explanation}</p>
            </Notice>
          )}

          {comparison && <ComparisonView comparison={comparison} />}

          {comparison && (
            <Panel title="Decision">
              <div className="p-3 space-y-3 text-xs">
                <div>
                  <label className="label" htmlFor="si-reason">
                    Reason (recorded in the audit log, min. 10 characters)
                  </label>
                  <textarea
                    id="si-reason"
                    rows={2}
                    className="field w-full"
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    placeholder="e.g. Mi-17 sorties held during forecast gusts at the pass; alternates feasible."
                  />
                </div>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-slate-500">The solver never activates a schedule on its own.</span>
                  <div className="flex gap-2">
                    <button onClick={() => setPending('REJECTED')} disabled={reason.trim().length < 10} className="btn-danger">
                      Reject
                    </button>
                    <button
                      onClick={() => setPending('APPROVED')}
                      disabled={reason.trim().length < 10 || !run.validation?.is_valid}
                      className="btn-primary"
                    >
                      Approve
                    </button>
                  </div>
                </div>
              </div>
            </Panel>
          )}
        </>
      )}

      <ConfirmDialog
        isOpen={pending != null}
        title={pending === 'APPROVED' ? 'Approve weather-aware proposal?' : 'Reject proposal?'}
        description={
          pending === 'APPROVED'
            ? 'It becomes the active schedule and the current approved version is superseded.'
            : 'The proposal is marked rejected and the current schedule stays in force.'
        }
        confirmLabel={pending === 'APPROVED' ? 'Approve' : 'Reject'}
        isDestructive={pending === 'REJECTED'}
        onConfirm={() => pending && decide(pending)}
        onCancel={() => setPending(null)}
      />
    </div>
  );
};
