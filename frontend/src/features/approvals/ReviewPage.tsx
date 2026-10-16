import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api/client';
import { OptimisationRun, ScheduleComparison, ScheduleVersion, ValidationResult } from '../../types/api';
import {
  Badge,
  EmptyState,
  ErrorState,
  Notice,
  PageHeader,
  Panel,
  SkeletonPage,
  fmtDuration,
  fmtZulu,
  shortId,
} from '../../components/ui';
import { ConfirmDialog } from '../../components/ConfirmDialog';

type Decision = 'APPROVED' | 'REJECTED';

export const ReviewPage: React.FC = () => {
  const [versions, setVersions] = useState<ScheduleVersion[]>([]);
  const [selected, setSelected] = useState<ScheduleVersion | null>(null);
  const [run, setRun] = useState<OptimisationRun | null>(null);
  const [comparison, setComparison] = useState<ScheduleComparison | null>(null);
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [reason, setReason] = useState('');
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [pending, setPending] = useState<Decision | null>(null);
  const [result, setResult] = useState<{ tone: 'ok' | 'crit'; text: string } | null>(null);

  const openVersion = useCallback(async (id: string) => {
    setDetailLoading(true);
    setRun(null);
    setComparison(null);
    try {
      const [full, val] = await Promise.all([api.getSchedule(id), api.validateSchedule(id)]);
      setSelected(full);
      setValidation(val);
      // Only optimiser-produced versions have a run; the baseline does not
      try {
        const r = await api.getRunForSchedule(id);
        setRun(r);
        setComparison(await api.getComparison(r.id));
      } catch {
        /* not produced by the optimiser */
      }
    } catch (err: any) {
      setError(err?.message || 'Could not load schedule version.');
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const scenarios = await api.getScenarios();
      if (!scenarios.length) return;
      const list = await api.getScenarioSchedules(scenarios[0].id);
      setVersions(list);
      const first = list.find((s) => s.status === 'PROPOSED') ?? list[0];
      if (first) await openVersion(first.id);
    } catch (err: any) {
      setError(err?.message || 'Could not load the review queue.');
    } finally {
      setLoading(false);
    }
  }, [openVersion]);

  useEffect(() => {
    load();
  }, [load]);

  const decide = async (decision: Decision) => {
    setPending(null);
    if (!selected || !run) return;
    setSubmitting(true);
    setResult(null);
    try {
      if (decision === 'APPROVED') await api.approveProposal(run.id, reason.trim());
      else await api.rejectProposal(run.id, reason.trim());
      setResult({
        tone: 'ok',
        text:
          decision === 'APPROVED'
            ? `v${selected.version_number} approved. It is now the active schedule; the previous approved version is superseded.`
            : `v${selected.version_number} rejected.`,
      });
      setReason('');
      await load();
    } catch (err: any) {
      setResult({ tone: 'crit', text: err?.message || 'The decision was not accepted.' });
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) return <SkeletonPage />;

  const queue = versions.filter((v) => v.status === 'PROPOSED');
  const decidable = selected?.status === 'PROPOSED' && !!run;
  const reasonOk = reason.trim().length >= 10;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Review"
        subtitle="Proposed schedule versions wait here until a reviewer approves or rejects them. Every decision is written to the audit log."
      />

      {error && <ErrorState message={error} onRetry={load} />}
      {result && (
        <Notice tone={result.tone} onDismiss={() => setResult(null)}>
          {result.text}
        </Notice>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-12 gap-4">
        <Panel title="Versions" right={`${queue.length} awaiting review`} className="xl:col-span-3">
          {versions.length === 0 ? (
            <EmptyState
              compact
              title="No versions"
              action={
                <Link to="/optimisation" className="btn-secondary">
                  Open optimiser
                </Link>
              }
            />
          ) : (
            <ul className="text-xs">
              {versions.map((v) => (
                <li key={v.id}>
                  <button
                    onClick={() => openVersion(v.id)}
                    className={`w-full flex items-center justify-between gap-2 px-3 py-2 border-b border-slate-800/70 text-left border-l-2 ${
                      selected?.id === v.id ? 'bg-slate-900 border-l-indigo-400' : 'border-l-transparent hover:bg-slate-900/60'
                    }`}
                  >
                    <span>
                      <span className="font-mono text-slate-100">v{v.version_number}</span>
                      <span className="block text-[10px] text-slate-500 font-mono">{fmtZulu(v.created_at)}</span>
                    </span>
                    <Badge status={v.status} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <div className="xl:col-span-9 space-y-4">
          {!selected ? (
            <Panel>
              <EmptyState title="Nothing selected" description="Pick a version on the left." />
            </Panel>
          ) : (
            <>
              <Panel
                title={`Version v${selected.version_number}`}
                right={<span className="font-mono">{shortId(selected.id)}</span>}
              >
                <div className="grid grid-cols-2 md:grid-cols-4 divide-x divide-slate-800 text-xs">
                  <div className="px-3 py-2.5">
                    <div className="text-slate-500">Status</div>
                    <div className="mt-1">
                      <Badge status={selected.status} />
                    </div>
                  </div>
                  <div className="px-3 py-2.5">
                    <div className="text-slate-500">Validator</div>
                    <div className={`mt-1 font-mono ${validation?.is_valid ? 'text-ok' : 'text-crit'}`}>
                      {detailLoading ? '…' : validation?.is_valid ? 'Pass' : `${validation?.conflict_count ?? 0} conflicts`}
                    </div>
                  </div>
                  <div className="px-3 py-2.5">
                    <div className="text-slate-500">Assignments</div>
                    <div className="mt-1 font-mono text-slate-100">{selected.assignments.length}</div>
                  </div>
                  <div className="px-3 py-2.5">
                    <div className="text-slate-500">Changes vs parent</div>
                    <div className="mt-1 font-mono text-slate-100">
                      {comparison ? `${comparison.tasks_reassigned} moved · ${comparison.tasks_time_shifted} retimed` : '—'}
                    </div>
                  </div>
                </div>
                {validation && !validation.is_valid && (
                  <div className="border-t border-slate-800 px-3 py-2 text-xs text-crit">
                    {validation.conflicts.slice(0, 3).map((c, i) => (
                      <div key={i}>
                        <span className="font-mono">[{c.code}]</span> {c.explanation}
                      </div>
                    ))}
                  </div>
                )}
              </Panel>

              {decidable ? (
                <Panel title="Decision">
                  <div className="p-3 space-y-3 text-xs">
                    <div>
                      <label className="label" htmlFor="rv-reason">
                        Reason (recorded in the audit log, min. 10 characters)
                      </label>
                      <textarea
                        id="rv-reason"
                        rows={3}
                        className="field w-full"
                        value={reason}
                        onChange={(e) => setReason(e.target.value)}
                        placeholder="e.g. Reassignment of C-130 sorties checked against crew rest; acceptable."
                      />
                    </div>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="text-slate-500">
                        Requires REVIEWER or ADMIN. Approval makes this version active and read-only.
                      </span>
                      <div className="flex gap-2">
                        <button
                          onClick={() => setPending('REJECTED')}
                          disabled={submitting || !reasonOk}
                          className="btn-danger"
                        >
                          Reject
                        </button>
                        <button
                          onClick={() => setPending('APPROVED')}
                          disabled={submitting || !reasonOk || !validation?.is_valid}
                          className="btn-primary"
                          title={!validation?.is_valid ? 'Cannot approve a version with conflicts' : undefined}
                        >
                          {submitting ? 'Submitting…' : 'Approve'}
                        </button>
                      </div>
                    </div>
                  </div>
                </Panel>
              ) : (
                <Notice tone="info">
                  {selected.status === 'PROPOSED'
                    ? 'This version has no optimiser run attached, so it cannot be decided here.'
                    : `This version is ${selected.status.toLowerCase()}; only proposed versions can be decided.`}
                </Notice>
              )}

              <Panel title="Assignments" right={`${selected.assignments.length} rows`}>
                {selected.assignments.length === 0 ? (
                  <EmptyState compact title="No assignments" />
                ) : (
                  <div className="overflow-auto max-h-[420px]">
                    <table className="data-table w-full text-xs">
                      <thead className="sticky top-0 bg-slate-925">
                        <tr>
                          <th>Task</th>
                          <th>Resource</th>
                          <th>Start</th>
                          <th>End</th>
                          <th className="text-right">Duration</th>
                        </tr>
                      </thead>
                      <tbody>
                        {[...selected.assignments]
                          .sort((a, b) => a.start_at.localeCompare(b.start_at))
                          .map((a) => (
                            <tr key={a.id}>
                              <td className="text-slate-200">{a.task_name}</td>
                              <td className="font-mono text-slate-300">{a.resource_name}</td>
                              <td className="font-mono text-slate-400 whitespace-nowrap">{fmtZulu(a.start_at)}</td>
                              <td className="font-mono text-slate-400 whitespace-nowrap">{fmtZulu(a.end_at)}</td>
                              <td className="text-right font-mono text-slate-400">{fmtDuration(a.start_at, a.end_at)}</td>
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
      </div>

      <ConfirmDialog
        isOpen={pending != null}
        title={pending === 'APPROVED' ? `Approve v${selected?.version_number}?` : `Reject v${selected?.version_number}?`}
        description={
          pending === 'APPROVED'
            ? 'This becomes the active schedule and cannot be edited afterwards. The current approved version will be superseded.'
            : 'The proposal will be marked rejected. You can run the optimiser again to produce a new one.'
        }
        confirmLabel={pending === 'APPROVED' ? 'Approve' : 'Reject'}
        isDestructive={pending === 'REJECTED'}
        onConfirm={() => pending && decide(pending)}
        onCancel={() => setPending(null)}
      />
    </div>
  );
};
