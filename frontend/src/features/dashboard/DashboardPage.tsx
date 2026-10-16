import React, { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../../api/client';
import { DashboardKPI, WeatherAlertsResponse } from '../../types/api';
import {
  Badge,
  EmptyState,
  ErrorState,
  PageHeader,
  Panel,
  SkeletonTable,
  StatStrip,
  fmtZulu,
  humanize,
} from '../../components/ui';

export const DashboardPage: React.FC = () => {
  const navigate = useNavigate();
  const [kpis, setKpis] = useState<DashboardKPI | null>(null);
  const [weather, setWeather] = useState<WeatherAlertsResponse | null>(null);
  const [weatherError, setWeatherError] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setKpis(await api.getDashboardKPI());
    } catch (err: any) {
      setError(err?.message || 'Could not load dashboard figures.');
    } finally {
      setLoading(false);
    }
    // Weather is slower (provider calls); load it separately so it never blocks the page
    try {
      const scenarios = await api.getScenarios();
      if (scenarios[0]) setWeather(await api.getWeatherAlerts(scenarios[0].id));
    } catch {
      setWeatherError(true);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const conflicts = kpis?.active_conflicts ?? 0;
  const unassigned = kpis?.unassigned_tasks ?? 0;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Overview"
        subtitle={
          kpis?.scenario_name
            ? `${kpis.scenario_name} · active plan ${kpis.active_version_number ? `v${kpis.active_version_number}` : 'none'}`
            : 'Current schedule, open conflicts and weather limits for the active scenario.'
        }
        actions={
          <>
            <button onClick={() => navigate('/disruptions')} className="btn-secondary">
              Log disruption
            </button>
            <button onClick={() => navigate('/optimisation')} className="btn-primary">
              Run optimiser
            </button>
          </>
        }
      />

      {error && <ErrorState message={error} onRetry={load} />}

      <StatStrip
        loading={loading}
        items={[
          { label: 'Tasks', value: kpis?.total_tasks ?? '—', hint: `${kpis?.assigned_tasks ?? 0} assigned` },
          { label: 'Unassigned', value: unassigned, tone: unassigned ? 'warn' : 'default', hint: 'backlog' },
          { label: 'Open conflicts', value: conflicts, tone: conflicts ? 'crit' : 'ok', hint: 'in the active plan' },
          { label: 'Completion', value: `${kpis?.schedule_completion_rate ?? 0}%`, hint: 'tasks with a slot' },
          { label: 'Utilisation', value: `${kpis?.resource_utilization_rate ?? 0}%`, hint: `${kpis?.total_resources ?? 0} resources` },
          {
            label: 'Last solver run',
            value: kpis?.latest_optimisation_status ?? 'None',
            tone: kpis?.latest_optimisation_status === 'INFEASIBLE' ? 'crit' : 'default',
          },
        ]}
      />

      <div className="grid grid-cols-1 xl:grid-cols-12 gap-4">
        <div className="xl:col-span-7 space-y-4">
          <Panel title="Schedule status" right={<Link to="/schedule" className="hover:text-slate-300">Open timeline →</Link>}>
            {loading ? (
              <SkeletonTable rows={2} cols={3} />
            ) : conflicts > 0 ? (
              <div className="p-4 flex items-start justify-between gap-4">
                <div className="text-xs">
                  <div className="text-crit font-medium">
                    {conflicts} conflict{conflicts > 1 ? 's' : ''} in the current schedule
                  </div>
                  <p className="text-slate-400 mt-1 max-w-lg">
                    Assignments break availability, time-window or qualification rules, usually after a disruption.
                    Re-run the optimiser to propose a repaired version for review.
                  </p>
                </div>
                <button onClick={() => navigate('/optimisation')} className="btn-primary shrink-0">
                  Resolve
                </button>
              </div>
            ) : (
              <div className="p-4 text-xs">
                <div className="text-ok font-medium">No conflicts</div>
                <p className="text-slate-400 mt-1">
                  Every assignment passes the independent validator.
                  {unassigned > 0 && ` ${unassigned} task${unassigned > 1 ? 's are' : ' is'} still waiting for a slot.`}
                </p>
              </div>
            )}
          </Panel>

          <Panel title="Weather limits" right={<Link to="/weather" className="hover:text-slate-300">Stations & map →</Link>}>
            {weatherError ? (
              <div className="p-4 text-xs text-slate-500">Weather service unavailable.</div>
            ) : !weather ? (
              <SkeletonTable rows={2} cols={3} />
            ) : weather.total_alerts === 0 ? (
              <EmptyState compact title="All sites within limits" description="No forecast hour crosses a wind, precipitation or temperature limit." />
            ) : (
              <table className="data-table w-full text-xs">
                <thead>
                  <tr>
                    <th>Site</th>
                    <th className="text-right">Critical</th>
                    <th className="text-right">Warning</th>
                    <th>First exceedance</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.values(
                    weather.alerts.reduce<Record<string, { name: string; crit: number; warn: number; first: string }>>(
                      (acc, a) => {
                        const row = (acc[a.location_id] ||= { name: a.location_name, crit: 0, warn: 0, first: a.forecast_timestamp });
                        if (a.severity === 'CRITICAL') row.crit++;
                        if (a.severity === 'WARNING') row.warn++;
                        if (a.forecast_timestamp < row.first) row.first = a.forecast_timestamp;
                        return acc;
                      },
                      {},
                    ),
                  ).map((r) => (
                    <tr key={r.name}>
                      <td className="text-slate-300">{r.name.replace(/\s*\(FICTIONAL\)$/i, '')}</td>
                      <td className={`text-right font-mono ${r.crit ? 'text-crit' : 'text-slate-600'}`}>{r.crit}</td>
                      <td className={`text-right font-mono ${r.warn ? 'text-warn' : 'text-slate-600'}`}>{r.warn}</td>
                      <td className="font-mono text-slate-400">{fmtZulu(r.first)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Panel>
        </div>

        <Panel
          title="Recent activity"
          right={<Link to="/audit" className="hover:text-slate-300">Audit log →</Link>}
          className="xl:col-span-5"
        >
          {loading ? (
            <SkeletonTable rows={6} cols={3} />
          ) : !kpis?.recent_audits?.length ? (
            <EmptyState compact title="No activity yet" />
          ) : (
            <table className="data-table w-full text-xs">
              <tbody>
                {kpis.recent_audits.map((e) => (
                  <tr key={e.id}>
                    <td className="font-mono text-slate-500 whitespace-nowrap">{fmtZulu(e.created_at)}</td>
                    <td className="text-slate-300">{humanize(e.action)}</td>
                    <td className="text-right">
                      <Badge status={e.entity_type} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>
      </div>
    </div>
  );
};
