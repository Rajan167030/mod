import React, { useCallback, useEffect, useState } from 'react';
import { api } from '../../api/client';
import { ErrorState, PageHeader, Panel, SkeletonPage, StatStrip, fmtZulu } from '../../components/ui';

interface ScenarioReport {
  scenario_id: string;
  scenario_name: string;
  total_resources: number;
  total_tasks: number;
  tasks_assigned: number;
  tasks_unassigned: number;
  priority_distribution: Record<string, number>;
  active_schedule_version: number | null;
  schedule_status: string;
  conflict_count: number;
  is_valid?: boolean;
  [key: string]: unknown;
}

const PRIORITY_ORDER = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'];
const priorityBar: Record<string, string> = {
  CRITICAL: 'bg-crit',
  HIGH: 'bg-warn',
  MEDIUM: 'bg-indigo-500',
  LOW: 'bg-slate-500',
};

const DEFINITIONS = [
  ['Completion', 'Tasks with an assigned slot ÷ all tasks in the scenario.'],
  ['Reassigned', 'Tasks moved to a different resource compared with the parent version.'],
  ['Retimed', 'Tasks kept on the same resource but given a different start time.'],
  ['Delay', 'Minutes between a task’s window opening and its scheduled start, summed over tasks.'],
  ['Conflict', 'An assignment that breaks availability, overlap, time-window or qualification rules.'],
];

export const ReportsPage: React.FC = () => {
  const [report, setReport] = useState<ScenarioReport | null>(null);
  const [scenarioId, setScenarioId] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const scenarios = await api.getScenarios();
      if (!scenarios.length) return;
      setScenarioId(scenarios[0].id);
      setReport(await api.getScenarioReport(scenarios[0].id));
    } catch (err: any) {
      setError(err?.message || 'Could not build the report.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) return <SkeletonPage />;

  const completion = report && report.total_tasks ? Math.round((report.tasks_assigned / report.total_tasks) * 100) : 0;
  const priorities = report
    ? PRIORITY_ORDER.filter((p) => p in report.priority_distribution).concat(
        Object.keys(report.priority_distribution).filter((p) => !PRIORITY_ORDER.includes(p)),
      )
    : [];

  return (
    <div className="space-y-4">
      <PageHeader
        title="Reports"
        subtitle={report ? `${report.scenario_name} · generated ${fmtZulu(new Date().toISOString())}` : 'Scenario summary'}
        actions={
          <>
            <button onClick={() => window.print()} className="btn-secondary">
              Print
            </button>
            <a
              href={scenarioId ? api.getExportCsvUrl(scenarioId) : undefined}
              target="_blank"
              rel="noreferrer"
              className={`btn-primary ${scenarioId ? '' : 'pointer-events-none opacity-50'}`}
            >
              Export CSV
            </a>
          </>
        }
      />

      {error && <ErrorState message={error} onRetry={load} />}

      {report && (
        <>
          <StatStrip
            items={[
              { label: 'Tasks', value: report.total_tasks },
              { label: 'Assigned', value: report.tasks_assigned, tone: 'ok' },
              { label: 'Unassigned', value: report.tasks_unassigned, tone: report.tasks_unassigned ? 'warn' : 'default' },
              { label: 'Completion', value: `${completion}%` },
              { label: 'Resources', value: report.total_resources },
              {
                label: 'Active version',
                value: report.active_schedule_version != null ? `v${report.active_schedule_version}` : 'None',
                hint: `${report.conflict_count} conflicts`,
                tone: report.conflict_count ? 'crit' : 'default',
              },
            ]}
          />

          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            <Panel title="Tasks by priority">
              <table className="data-table w-full text-xs">
                <thead>
                  <tr>
                    <th>Priority</th>
                    <th className="text-right">Tasks</th>
                    <th className="text-right">Share</th>
                    <th className="w-1/2" />
                  </tr>
                </thead>
                <tbody>
                  {priorities.map((p) => {
                    const n = report.priority_distribution[p];
                    const pct = report.total_tasks ? (n / report.total_tasks) * 100 : 0;
                    return (
                      <tr key={p}>
                        <td className="text-slate-300">{p.charAt(0) + p.slice(1).toLowerCase()}</td>
                        <td className="text-right font-mono text-slate-100">{n}</td>
                        <td className="text-right font-mono text-slate-400">{pct.toFixed(0)}%</td>
                        <td>
                          <div className="h-2 bg-slate-800" aria-hidden>
                            <div className={`h-full ${priorityBar[p] ?? 'bg-slate-500'}`} style={{ width: `${pct}%` }} />
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </Panel>

            <Panel title="Definitions">
              <dl className="text-xs divide-y divide-slate-800/70">
                {DEFINITIONS.map(([term, def]) => (
                  <div key={term} className="grid grid-cols-[110px_1fr] gap-3 px-3 py-2">
                    <dt className="text-slate-300">{term}</dt>
                    <dd className="text-slate-400">{def}</dd>
                  </div>
                ))}
              </dl>
            </Panel>
          </div>
        </>
      )}
    </div>
  );
};
