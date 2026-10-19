import React, { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { api } from '../../api/client';
import { Scenario, ScenarioComparison } from '../../types/api';
import { Badge, EmptyState, ErrorState, PageHeader, Panel, SkeletonTable, fmtZulu, humanize } from '../../components/ui';

const CHANGE_LABEL: Record<string, string> = {
  ONLY_IN_A: 'only in A',
  ONLY_IN_B: 'only in B',
  FLOWN_ONLY_IN_A: 'flown only in A',
  FLOWN_ONLY_IN_B: 'flown only in B',
  UNASSIGNED_IN_BOTH: 'no aircraft in either',
  DIFFERENT_AIRCRAFT: 'different aircraft',
  DIFFERENT_TIME: 'different time',
};

export const ComparePage: React.FC = () => {
  const [params, setParams] = useSearchParams();
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [data, setData] = useState<ScenarioComparison | null>(null);
  const [error, setError] = useState<string | null>(null);
  const a = params.get('a') ?? '';
  const b = params.get('b') ?? '';

  useEffect(() => {
    api.getScenarios().then((s) => {
      setScenarios(s);
      if (!a && !b && s.length >= 2) {
        const branch = s.find((x) => x.parent_scenario_id);
        setParams(branch ? { a: branch.parent_scenario_id!, b: branch.id } : { a: s[1].id, b: s[0].id });
      }
    }).catch((e) => setError(e?.message || 'Could not load scenarios.'));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!a || !b) return;
    setData(null);
    setError(null);
    api.compareScenarios(a, b).then(setData).catch((e) => setError(e?.message || 'Could not compare.'));
  }, [a, b]);

  const pick = (key: 'a' | 'b', id: string) => setParams({ a: key === 'a' ? id : a, b: key === 'b' ? id : b });

  const tone = (m: ScenarioComparison['measures'][number]) => {
    if (m.higher_is_better == null || m.a == null || m.b == null || m.a === m.b) return '';
    const bBetter = m.higher_is_better ? m.b > m.a : m.b < m.a;
    return bBetter ? 'text-ok' : 'text-crit';
  };

  return (
    <div className="space-y-4">
      <PageHeader title="Compare scenarios" subtitle="Two scenarios (for example a branch and its parent) on the same measures, then task by task." />
      {error && <ErrorState message={error} />}

      <div className="panel p-3 grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
        {(['a', 'b'] as const).map((k) => (
          <div key={k}>
            <label className="label" htmlFor={`cmp-${k}`}>{k.toUpperCase()}</label>
            <select id={`cmp-${k}`} className="field w-full" value={k === 'a' ? a : b} onChange={(e) => pick(k, e.target.value)}>
              <option value="">Choose a scenario</option>
              {scenarios.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </div>
        ))}
      </div>

      {!a || !b ? (
        <Panel><EmptyState title="Pick two scenarios" description="Create a branch from the Scenarios page to try changes, then compare it here." /></Panel>
      ) : !data ? (
        <Panel><SkeletonTable rows={8} cols={3} /></Panel>
      ) : (
        <>
          <Panel title="Measures" right="green: B is better · red: B is worse">
            <table className="data-table w-full text-xs">
              <thead>
                <tr>
                  <th />
                  <th className="text-right normal-case tracking-normal">A · {data.a.name}</th>
                  <th className="text-right normal-case tracking-normal">B · {data.b.name}</th>
                  <th className="text-right">Change</th>
                </tr>
              </thead>
              <tbody>
                {data.measures.map((m) => (
                  <tr key={m.name}>
                    <td className="text-slate-400">{m.name}</td>
                    <td className="text-right font-mono text-slate-300">{m.a ?? '—'}</td>
                    <td className={`text-right font-mono ${tone(m) || 'text-slate-300'}`}>{m.b ?? '—'}</td>
                    <td className={`text-right font-mono ${tone(m)}`}>
                      {m.a != null && m.b != null && m.a !== m.b ? `${m.b > m.a ? '+' : ''}${Math.round((m.b - m.a) * 10) / 10}` : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>

          <Panel title="Task differences" right={`${data.changes.length} differ · ${data.identical_tasks} identical`}>
            {data.changes.length === 0 ? (
              <EmptyState compact title="Task plans are identical" />
            ) : (
              <div className="overflow-auto max-h-[480px]">
                <table className="data-table w-full text-xs">
                  <thead className="sticky top-0 bg-slate-925">
                    <tr><th>Task</th><th>Priority</th><th>Difference</th><th>In A</th><th>In B</th></tr>
                  </thead>
                  <tbody>
                    {data.changes.map((c) => (
                      <tr key={c.task}>
                        <td className="text-slate-200">{c.task}</td>
                        <td><Badge status={c.priority} /></td>
                        <td className="text-slate-300">{CHANGE_LABEL[c.change] ?? humanize(c.change)}</td>
                        <td className="font-mono text-slate-400 whitespace-nowrap">{c.a ? `${c.a.aircraft} · ${fmtZulu(c.a.start)}` : '—'}</td>
                        <td className="font-mono text-slate-200 whitespace-nowrap">{c.b ? `${c.b.aircraft} · ${fmtZulu(c.b.start)}` : '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
        </>
      )}
    </div>
  );
};
