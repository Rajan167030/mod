import React, { useEffect, useState } from 'react';
import { api } from '../../api/client';
import { RiskFactorKind, RiskReport, Scenario, ScheduleVersion } from '../../types/api';
import { Badge, EmptyState, ErrorState, PageHeader, Panel, SkeletonTable, StatStrip, fmtZulu, fmtZuluTime } from '../../components/ui';

const FACTOR: Record<RiskFactorKind, { label: string; cls: string }> = {
  weather: { label: 'Weather', cls: 'text-info border-info/40' },
  threat: { label: 'Threat', cls: 'text-crit border-crit/40' },
  airspace: { label: 'Airspace', cls: 'text-crit border-crit/40' },
  crew: { label: 'Crew', cls: 'text-warn border-warn/40' },
  aircraft: { label: 'Aircraft', cls: 'text-slate-300 border-slate-600' },
  schedule: { label: 'Slack', cls: 'text-slate-300 border-slate-600' },
  stores: { label: 'Stores', cls: 'text-warn border-warn/40' },
};

const levelTone = { HIGH: 'crit', MEDIUM: 'warn', LOW: 'ok' } as const;

export const RiskPage: React.FC = () => {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenarioId, setScenarioId] = useState('');
  const [versions, setVersions] = useState<ScheduleVersion[]>([]);
  const [versionId, setVersionId] = useState('');
  const [report, setReport] = useState<RiskReport | null>(null);
  const [filter, setFilter] = useState<'ALL' | 'HIGH' | 'MEDIUM'>('ALL');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    api.getScenarios().then((s) => {
      setScenarios(s);
      if (s[0]) setScenarioId(s[0].id);
    }).catch((e) => setError(e?.message || 'Could not load scenarios.'));
  }, []);

  useEffect(() => {
    if (!scenarioId) return;
    setReport(null);
    setVersions([]);
    api.getScenarioSchedules(scenarioId).then((vs) => {
      const usable = vs.filter((v) => v.status === 'APPROVED' || v.status === 'PROPOSED').sort((a, b) => b.version_number - a.version_number);
      setVersions(usable);
      setVersionId(usable.find((v) => v.status === 'APPROVED')?.id ?? usable[0]?.id ?? '');
    }).catch((e) => setError(e?.message || 'Could not load plans.'));
  }, [scenarioId]);

  const load = () => {
    if (!versionId) return;
    setLoading(true);
    setError(null);
    api.getScheduleRisk(versionId)
      .then(setReport)
      .catch((e) => setError(e?.message || 'Could not assess risk.'))
      .finally(() => setLoading(false));
  };
  useEffect(load, [versionId]);

  const rows = (report?.sorties ?? []).filter((s) => filter === 'ALL' || s.level === filter);
  const sum = report?.summary;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Mission risk"
        subtitle="Predicted chance that each sortie is disrupted, from forecast weather and its trend, threat zones and their confidence, crew fatigue and turnaround, maintenance timing, deadline slack and stores reserve. Every score lists its reasons."
        actions={
          <>
            <select className="field max-w-[260px]" value={scenarioId} onChange={(e) => setScenarioId(e.target.value)} aria-label="Scenario">
              {scenarios.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
            <select className="field" value={versionId} onChange={(e) => setVersionId(e.target.value)} aria-label="Plan version">
              {versions.map((v) => <option key={v.id} value={v.id}>v{v.version_number} · {v.status.toLowerCase()}</option>)}
            </select>
            <button onClick={load} className="btn-secondary" disabled={!versionId}>Re-assess</button>
          </>
        }
      />
      {error && <ErrorState message={error} onRetry={load} />}

      <StatStrip
        loading={loading || (!report && !!versionId)}
        items={[
          { label: 'Sorties', value: sum?.sorties ?? 0 },
          { label: 'Average risk', value: `${sum?.average ?? 0}%`, tone: (sum?.average ?? 0) >= 25 ? 'warn' : 'ok' },
          { label: 'Highest', value: `${sum?.max ?? 0}%`, tone: (sum?.max ?? 0) >= 45 ? 'crit' : (sum?.max ?? 0) >= 25 ? 'warn' : 'ok' },
          { label: 'High risk', value: sum?.high ?? 0, tone: sum?.high ? 'crit' : 'ok' },
          { label: 'Medium risk', value: sum?.medium ?? 0, tone: sum?.medium ? 'warn' : 'default' },
          { label: 'Critical tasks at high risk', value: sum?.critical_high ?? 0, tone: sum?.critical_high ? 'crit' : 'ok' },
        ]}
      />

      {sum && Object.keys(sum.drivers).length > 0 && (
        <div className="panel px-4 py-2.5 flex flex-wrap items-center gap-3 text-xs">
          <span className="text-slate-500">Main drivers</span>
          {Object.entries(sum.drivers).map(([k, n]) => (
            <span key={k} className={`px-1.5 border font-mono text-[10px] uppercase ${FACTOR[k as RiskFactorKind]?.cls ?? ''}`}>
              {FACTOR[k as RiskFactorKind]?.label ?? k} · {n} sorties
            </span>
          ))}
        </div>
      )}

      <Panel
        title={report ? `Sorties · plan v${report.version_number} (${report.status.toLowerCase()})` : 'Sorties'}
        right={
          <span className="flex gap-1">
            {(['ALL', 'HIGH', 'MEDIUM'] as const).map((f) => (
              <button key={f} onClick={() => setFilter(f)} className={`h-6 px-2 border text-[11px] ${filter === f ? 'border-indigo-500 text-slate-100' : 'border-slate-800 text-slate-500'}`}>
                {f === 'ALL' ? 'All' : f.toLowerCase()}
              </button>
            ))}
          </span>
        }
      >
        {!versionId && !loading ? (
          <EmptyState compact title="No plan to assess" description="This scenario has no approved or proposed plan." />
        ) : !report || loading ? (
          <SkeletonTable rows={8} cols={6} />
        ) : rows.length === 0 ? (
          <EmptyState compact title="Nothing at this level" />
        ) : (
          <div className="overflow-x-auto">
            <table className="data-table w-full text-xs">
              <thead>
                <tr>
                  <th className="w-28">Risk</th>
                  <th>Sortie</th>
                  <th>Aircraft · crew</th>
                  <th>When</th>
                  <th>Why</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((s) => (
                  <tr key={s.task_id}>
                    <td>
                      <div className="flex items-center gap-2">
                        <span className={`font-mono text-base w-10 ${s.level === 'HIGH' ? 'text-crit' : s.level === 'MEDIUM' ? 'text-warn' : 'text-slate-300'}`}>{s.score}%</span>
                        <Badge status={s.level} tone={levelTone[s.level]} />
                      </div>
                    </td>
                    <td>
                      <div className="text-slate-200">{s.task_name}</div>
                      <div className="text-slate-500">{s.priority.toLowerCase()} · {s.site ?? 'no site'}</div>
                    </td>
                    <td className="whitespace-nowrap">
                      <div className="font-mono text-slate-200">{s.resource_name}</div>
                      <div className="text-slate-500">{s.crew_name ?? 'no crew'}</div>
                    </td>
                    <td className="font-mono text-slate-400 whitespace-nowrap">{fmtZulu(s.start_at)}–{fmtZuluTime(s.end_at)}</td>
                    <td>
                      {s.factors.length === 0 ? (
                        <span className="text-slate-600">No risk factors found</span>
                      ) : (
                        <ul className="space-y-0.5">
                          {s.factors.map((f, i) => (
                            <li key={i} className="flex items-start gap-1.5">
                              <span className={`shrink-0 px-1 border font-mono text-[9px] uppercase ${FACTOR[f.kind]?.cls ?? ''}`}>{FACTOR[f.kind]?.label ?? f.kind} +{f.points}</span>
                              <span className="text-slate-300">{f.detail}</span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="px-3 py-2 border-t border-slate-800 text-[11px] text-slate-500">
          Each factor is treated as an independent chance of disruption and combined as 1 − Π(1 − p). Scores rank sorties for attention; they are estimates, not forecasts of a specific outcome.
        </p>
      </Panel>
    </div>
  );
};
