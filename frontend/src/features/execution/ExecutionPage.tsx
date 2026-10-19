import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api/client';
import { CoaSet, ExecutionBoard, ExecutionSortie, Scenario } from '../../types/api';
import { Badge, EmptyState, ErrorState, Notice, PageHeader, Panel, SkeletonTable, StatStrip, fmtZulu, fmtZuluTime } from '../../components/ui';

const statusTone = { PLANNED: 'default', AIRBORNE: 'info', COMPLETED: 'ok', ABORTED: 'crit' } as const;

export const ExecutionPage: React.FC = () => {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenarioId, setScenarioId] = useState('');
  const [board, setBoard] = useState<ExecutionBoard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [aborting, setAborting] = useState<string | null>(null);
  const [abortForm, setAbortForm] = useState({ reason: '', ground: false, hours: '6' });
  const [coa, setCoa] = useState<CoaSet | null>(null);
  const [solving, setSolving] = useState(false);
  const [adopted, setAdopted] = useState<string | null>(null);

  useEffect(() => {
    api.getScenarios().then((s) => {
      setScenarios(s);
      if (s[0]) setScenarioId(s.find((x) => x.name.startsWith('Northern Sector'))?.id ?? s[0].id);
    }).catch((e) => setError(e?.message || 'Could not load scenarios.'));
  }, []);

  const load = useCallback(async () => {
    if (!scenarioId) return;
    try {
      setBoard(await api.getExecution(scenarioId));
    } catch (e: any) {
      setError(e?.message || 'Could not load the plan.');
    }
  }, [scenarioId]);

  useEffect(() => {
    setBoard(null);
    setCoa(null);
    setAdopted(null);
    load();
    const id = window.setInterval(load, 30000);
    return () => window.clearInterval(id);
  }, [load]);

  const act = async (s: ExecutionSortie, action: 'launch' | 'land' | 'abort') => {
    setBusy(s.assignment_id);
    setError(null);
    try {
      const body = action === 'abort'
        ? { action, reason: abortForm.reason, ground_hours: abortForm.ground ? Number(abortForm.hours) : undefined }
        : { action };
      setBoard(await api.sortieAction(s.assignment_id, body));
      setAborting(null);
      setAbortForm({ reason: '', ground: false, hours: '6' });
    } catch (e: any) {
      setError(e?.message || 'Could not record that.');
    } finally {
      setBusy(null);
    }
  };

  const replan = async () => {
    if (!board?.plan_id) return;
    setSolving(true);
    setCoa(null);
    setError(null);
    try {
      setCoa(await api.generateCoursesOfAction(board.plan_id, true, 6, true));
    } catch (e: any) {
      setError(e?.message || 'Could not re-plan.');
    } finally {
      setSolving(false);
    }
  };

  const adopt = async (key: CoaSet['courses'][number]['key']) => {
    if (!coa) return;
    try {
      const r = await api.adoptCourseOfAction(coa.coa_set_id, key);
      setAdopted(`Plan v${r.proposed_version_number} proposed.`);
      setCoa(null);
    } catch (e: any) {
      setError(e?.message || 'Could not adopt that plan.');
    }
  };

  const sum = board?.summary ?? {};
  const options = coa?.courses.filter((c) => c.metrics && !c.same_as) ?? [];

  return (
    <div className="space-y-4">
      <PageHeader
        title="Mission execution"
        subtitle="The approved plan on the day: launch, land or abort each sortie as it happens. When something breaks, re-plan from now; sorties already flying or flown stay as they are."
        actions={
          <>
            <select className="field max-w-[280px]" value={scenarioId} onChange={(e) => setScenarioId(e.target.value)} aria-label="Scenario">
              {scenarios.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
            </select>
            <button onClick={load} className="btn-secondary">Refresh</button>
          </>
        }
      />
      {error && <ErrorState message={error} onRetry={load} />}
      {adopted && (
        <Notice tone="ok" onDismiss={() => setAdopted(null)}>
          {adopted} <Link to="/review" className="underline">A reviewer approves it in Review →</Link> Execution then continues on the new plan.
        </Notice>
      )}

      <StatStrip
        loading={!board}
        items={[
          { label: 'Plan in force', value: board?.plan_version ? `v${board.plan_version}` : '—', hint: board ? `as of ${fmtZuluTime(board.now)}` : undefined },
          { label: 'To fly', value: sum.planned ?? 0, hint: sum.overdue ? `${sum.overdue} overdue to launch` : undefined, tone: sum.overdue ? 'warn' : 'default' },
          { label: 'Airborne', value: sum.airborne ?? 0, tone: sum.airborne ? 'info' : 'default' },
          { label: 'Completed', value: sum.completed ?? 0, tone: sum.completed ? 'ok' : 'default' },
          { label: 'Aborted', value: sum.aborted ?? 0, tone: sum.aborted ? 'crit' : 'default' },
          { label: 'Plan check', value: board?.check ? (board.check.valid ? 'Valid' : `${board.check.conflicts} conflicts`) : '—', hint: board?.check?.unassigned ? `${board.check.unassigned} missions without a sortie` : undefined, tone: board?.check?.valid ? 'ok' : 'crit' },
        ]}
      />

      {board?.needs_replan && (
        <div className="border border-crit/40 bg-crit/5 px-3 py-2.5 text-xs space-y-2">
          <div className="text-slate-200 font-medium">The plan no longer holds.</div>
          <ul className="list-disc pl-4 text-slate-300">
            {(sum.aborted ?? 0) > 0 && <li>{sum.aborted} sortie(s) aborted; their missions need a new slot.</li>}
            {board.check?.items.map((t, i) => <li key={i}>{t}</li>)}
          </ul>
          <button onClick={replan} disabled={solving} className="btn-primary h-8">{solving ? 'Solving 4 options from now…' : 'Re-plan from now'}</button>
        </div>
      )}

      {coa && (
        <Panel title="Options from now" right={coa.recommendation_reason ?? undefined}>
          {options.length === 0 ? (
            <EmptyState compact title="No feasible option" description="Open Courses of action to adjust weights or drop low-priority missions." />
          ) : (
            <table className="data-table w-full text-xs">
              <thead><tr><th>Option</th><th className="text-right">Dropped</th><th className="text-right">Critical dropped</th><th className="text-right">Delay</th><th className="text-right">Changes</th><th className="text-right">High-risk</th><th>Checks</th><th /></tr></thead>
              <tbody>
                {options.map((c) => (
                  <tr key={c.key} className={c.recommended ? 'bg-indigo-500/5' : ''}>
                    <td><span className="text-slate-100">{c.label}</span>{c.recommended && <Badge status="suggested" tone="ok" className="ml-2" />}<div className="text-slate-500">{c.intent}</div></td>
                    <td className="text-right font-mono">{c.metrics!.unassigned}</td>
                    <td className={`text-right font-mono ${c.metrics!.unassigned_critical ? 'text-crit' : ''}`}>{c.metrics!.unassigned_critical}</td>
                    <td className="text-right font-mono">{c.metrics!.total_delay_minutes} min</td>
                    <td className="text-right font-mono">{c.metrics!.reassigned + c.metrics!.retimed}</td>
                    <td className="text-right font-mono">{c.metrics!.risk_high ?? '—'}</td>
                    <td className={c.metrics!.validator_pass ? 'text-ok' : 'text-crit'}>{c.metrics!.validator_pass ? 'Pass' : `${c.metrics!.validator_conflicts} conflicts`}</td>
                    <td className="text-right"><button onClick={() => adopt(c.key)} disabled={!c.metrics!.validator_pass} className="btn-primary h-7 px-2">Adopt</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>
      )}

      <Panel title="Sorties" right={board ? `${board.sorties.length} in plan v${board.plan_version ?? '—'}` : undefined}>
        {!board ? (
          <SkeletonTable rows={8} cols={7} />
        ) : board.sorties.length === 0 ? (
          <EmptyState title="No approved plan" description="Approve a plan in Review before executing it." />
        ) : (
          <div className="overflow-x-auto">
            <table className="data-table w-full text-xs">
              <thead>
                <tr><th>Planned</th><th>Mission</th><th>Aircraft · crew</th><th>Status</th><th>Actual</th><th /></tr>
              </thead>
              <tbody>
                {board.sorties.map((s) => (
                  <React.Fragment key={s.assignment_id}>
                    <tr className={s.status === 'ABORTED' ? 'opacity-60' : ''}>
                      <td className="font-mono whitespace-nowrap">
                        <div className="text-slate-200">{fmtZulu(s.start_at)}</div>
                        <div className="text-slate-500">to {fmtZuluTime(s.end_at)}</div>
                      </td>
                      <td>
                        <div className="text-slate-100">{s.task_name}</div>
                        <div className="text-slate-500">{s.priority?.toLowerCase()} · {s.site ?? 'no site'}</div>
                      </td>
                      <td>
                        <div className="font-mono text-slate-200">{s.resource_name}{s.resource_status && s.resource_status !== 'AVAILABLE' ? <span className="text-crit"> ({s.resource_status.toLowerCase()})</span> : null}</div>
                        <div className="text-slate-500">{s.crew_name ?? 'no crew'}</div>
                      </td>
                      <td>
                        <Badge status={s.status} tone={statusTone[s.status]} />
                        {s.overdue_minutes ? <div className="text-warn mt-0.5">{s.overdue_minutes} min overdue</div> : null}
                        {s.note && <div className="text-slate-500 mt-0.5">{s.note}</div>}
                      </td>
                      <td className="font-mono text-slate-400 whitespace-nowrap">
                        {s.actual_start ? <>off {fmtZuluTime(s.actual_start)}{s.launch_delay_minutes ? <span className={s.launch_delay_minutes > 15 ? 'text-warn' : ''}> ({s.launch_delay_minutes > 0 ? '+' : ''}{s.launch_delay_minutes}m)</span> : null}</> : '—'}
                        {s.actual_end && <div>on {fmtZuluTime(s.actual_end)}</div>}
                      </td>
                      <td className="text-right whitespace-nowrap">
                        {s.status === 'PLANNED' && <button onClick={() => act(s, 'launch')} disabled={busy === s.assignment_id} className="btn-secondary h-7 px-2 mr-1">Launch</button>}
                        {s.status === 'AIRBORNE' && <button onClick={() => act(s, 'land')} disabled={busy === s.assignment_id} className="btn-secondary h-7 px-2 mr-1">Landed</button>}
                        {(s.status === 'PLANNED' || s.status === 'AIRBORNE') && (
                          <button onClick={() => setAborting(aborting === s.assignment_id ? null : s.assignment_id)} className="btn-ghost h-7 px-2 text-crit">Abort</button>
                        )}
                      </td>
                    </tr>
                    {aborting === s.assignment_id && (
                      <tr>
                        <td colSpan={6} className="bg-slate-950">
                          <form
                            className="flex flex-wrap items-end gap-3 p-2"
                            onSubmit={(e) => {
                              e.preventDefault();
                              act(s, 'abort');
                            }}
                          >
                            <div className="flex-1 min-w-[220px]">
                              <label className="label" htmlFor={`r-${s.assignment_id}`}>Reason</label>
                              <input id={`r-${s.assignment_id}`} required className="field w-full" value={abortForm.reason} onChange={(e) => setAbortForm((f) => ({ ...f, reason: e.target.value }))} placeholder="e.g. Hydraulic leak on start-up" />
                            </div>
                            <label className="flex items-center gap-2 text-slate-300 h-9">
                              <input type="checkbox" className="accent-indigo-500" checked={abortForm.ground} onChange={(e) => setAbortForm((f) => ({ ...f, ground: e.target.checked }))} />
                              {s.resource_name} unserviceable for
                            </label>
                            <input type="number" min={1} max={72} className="field w-16 font-mono" disabled={!abortForm.ground} value={abortForm.hours} onChange={(e) => setAbortForm((f) => ({ ...f, hours: e.target.value }))} aria-label="Hours unserviceable" />
                            <span className="text-slate-500 h-9 flex items-center">hours</span>
                            <button type="submit" disabled={busy === s.assignment_id} className="btn-primary h-9">Record abort</button>
                          </form>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
};
