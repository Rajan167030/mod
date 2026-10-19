import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Trash2 } from 'lucide-react';
import { api } from '../../api/client';
import { AlertEvaluation, AlertKind, AlertKindInfo, AlertRule, Scenario } from '../../types/api';
import { Badge, EmptyState, ErrorState, PageHeader, Panel, SkeletonTable, fmtZulu } from '../../components/ui';

const PRIORITIES = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'];

export const AlertsPage: React.FC = () => {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenarioId, setScenarioId] = useState('');
  const [kinds, setKinds] = useState<Record<string, AlertKindInfo>>({});
  const [rules, setRules] = useState<AlertRule[] | null>(null);
  const [result, setResult] = useState<AlertEvaluation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState({ name: '', kind: 'TASK_DELAY' as AlertKind, threshold: '60', min_priority: 'HIGH', severity: 'WARNING' as 'WARNING' | 'CRITICAL' });
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.getScenarios().then((s) => {
      setScenarios(s);
      if (s[0]) setScenarioId(s[0].id);
    }).catch((e) => setError(e?.message || 'Could not load scenarios.'));
    api.getAlertKinds().then(setKinds).catch(() => undefined);
  }, []);

  const load = useCallback(async () => {
    if (!scenarioId) return;
    setError(null);
    try {
      const [r, ev] = await Promise.all([api.getAlertRules(scenarioId), api.evaluateAlerts(scenarioId)]);
      setRules(r);
      setResult(ev);
    } catch (e: any) {
      setError(e?.message || 'Could not evaluate alerts.');
    }
  }, [scenarioId]);

  useEffect(() => {
    setRules(null);
    setResult(null);
    load();
  }, [load]);

  const save = async (rule: AlertRule) => {
    try {
      await api.updateAlertRule(rule);
      await load();
    } catch (e: any) {
      setError(e?.message || 'Could not save the rule.');
    }
  };

  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      await api.createAlertRule(scenarioId, {
        name: draft.name || kinds[draft.kind]?.label || draft.kind,
        kind: draft.kind,
        threshold: kinds[draft.kind]?.unit ? Number(draft.threshold) : null,
        min_priority: draft.min_priority,
        severity: draft.severity,
        enabled: true,
      });
      setDraft((d) => ({ ...d, name: '' }));
      await load();
    } catch (err: any) {
      setError(err?.message || 'Could not add the rule.');
    } finally {
      setSaving(false);
    }
  };

  const remove = async (rule: AlertRule) => {
    try {
      await api.deleteAlertRule(rule.id);
      await load();
    } catch (e: any) {
      setError(e?.message || 'Could not delete the rule.');
    }
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title="Alerts"
        subtitle="Conditions you want watched on the active plan. Each alert links to the object it is about."
        actions={
          <>
            <select className="field max-w-[280px]" value={scenarioId} onChange={(e) => setScenarioId(e.target.value)} aria-label="Scenario">
              {scenarios.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
            <button onClick={load} className="btn-secondary">Re-check</button>
          </>
        }
      />
      {error && <ErrorState message={error} onRetry={load} />}

      <Panel
        title="Firing now"
        right={result ? `${result.critical} critical · ${result.warning} warning · ${result.rules_checked} rules · plan v${result.active_version ?? '—'} · ${fmtZulu(result.evaluated_at)}` : undefined}
      >
        {!result ? (
          <SkeletonTable rows={5} cols={3} />
        ) : result.alerts.length === 0 ? (
          <EmptyState compact title="Nothing firing" description="Every enabled rule passes on the active plan." />
        ) : (
          <table className="data-table w-full text-xs">
            <tbody>
              {result.alerts.map((a, i) => (
                <tr key={i}>
                  <td className="w-20"><Badge status={a.severity} /></td>
                  <td className="text-slate-500 whitespace-nowrap">{a.rule}</td>
                  <td className="text-slate-200">{a.message}</td>
                  <td className="text-right whitespace-nowrap">
                    {a.object && (
                      <Link to={`/explorer?scenario=${scenarioId}&type=${a.object.type}&id=${encodeURIComponent(a.object.id)}`} className="btn-ghost h-6 px-2">
                        Open {a.object.type} →
                      </Link>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>

      <Panel title="Rules" right={rules ? `${rules.filter((r) => r.enabled).length} of ${rules.length} on` : undefined}>
        {!rules ? (
          <SkeletonTable rows={6} cols={5} />
        ) : (
          <div className="overflow-x-auto">
            <table className="data-table w-full text-xs">
              <thead>
                <tr>
                  <th>On</th>
                  <th>Rule</th>
                  <th>Checks</th>
                  <th>Limit</th>
                  <th>Applies to</th>
                  <th>Severity</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rules.map((r) => {
                  const info = kinds[r.kind];
                  return (
                    <tr key={r.id} className={r.enabled ? '' : 'opacity-50'}>
                      <td><input type="checkbox" checked={r.enabled} onChange={(e) => save({ ...r, enabled: e.target.checked })} className="accent-indigo-500" aria-label={`Enable ${r.name}`} /></td>
                      <td className="text-slate-200">{r.name}</td>
                      <td className="text-slate-400">{info?.label ?? r.kind}</td>
                      <td>
                        {info?.unit ? (
                          <span className="flex items-center gap-1.5">
                            <input
                              type="number"
                              min={0}
                              defaultValue={r.threshold ?? undefined}
                              onBlur={(e) => Number(e.target.value) !== r.threshold && save({ ...r, threshold: Number(e.target.value) })}
                              className="field h-7 w-16 font-mono"
                              aria-label="Limit"
                            />
                            <span className="text-slate-500">{info.unit}</span>
                          </span>
                        ) : <span className="text-slate-600">—</span>}
                      </td>
                      <td>
                        <select className="field h-7" value={r.min_priority} onChange={(e) => save({ ...r, min_priority: e.target.value })} aria-label="Minimum priority">
                          {PRIORITIES.map((p) => <option key={p} value={p}>{p.toLowerCase()} and above</option>)}
                        </select>
                      </td>
                      <td>
                        <select className="field h-7" value={r.severity} onChange={(e) => save({ ...r, severity: e.target.value as AlertRule['severity'] })} aria-label="Severity">
                          <option value="WARNING">warning</option>
                          <option value="CRITICAL">critical</option>
                        </select>
                      </td>
                      <td className="text-right">
                        <button onClick={() => remove(r)} className="btn-ghost h-7 px-2" aria-label={`Delete ${r.name}`}><Trash2 className="w-3.5 h-3.5" /></button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <form onSubmit={add} className="flex flex-wrap items-end gap-2 p-3 border-t border-slate-800 text-xs">
          <div>
            <label className="label" htmlFor="nr-kind">New rule</label>
            <select id="nr-kind" className="field" value={draft.kind} onChange={(e) => {
              const k = e.target.value as AlertKind;
              setDraft((d) => ({ ...d, kind: k, threshold: String(kinds[k]?.threshold ?? '') }));
            }}>
              {Object.entries(kinds).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
            </select>
          </div>
          {kinds[draft.kind]?.unit && (
            <div>
              <label className="label" htmlFor="nr-thr">Limit ({kinds[draft.kind].unit})</label>
              <input id="nr-thr" type="number" min={0} className="field w-24 font-mono" value={draft.threshold} onChange={(e) => setDraft((d) => ({ ...d, threshold: e.target.value }))} />
            </div>
          )}
          <div>
            <label className="label" htmlFor="nr-prio">Applies to</label>
            <select id="nr-prio" className="field" value={draft.min_priority} onChange={(e) => setDraft((d) => ({ ...d, min_priority: e.target.value }))}>
              {PRIORITIES.map((p) => <option key={p} value={p}>{p.toLowerCase()} and above</option>)}
            </select>
          </div>
          <div>
            <label className="label" htmlFor="nr-sev">Severity</label>
            <select id="nr-sev" className="field" value={draft.severity} onChange={(e) => setDraft((d) => ({ ...d, severity: e.target.value as 'WARNING' | 'CRITICAL' }))}>
              <option value="WARNING">warning</option>
              <option value="CRITICAL">critical</option>
            </select>
          </div>
          <div className="flex-1 min-w-[200px]">
            <label className="label" htmlFor="nr-name">Name (optional)</label>
            <input id="nr-name" className="field w-full" value={draft.name} onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))} placeholder={kinds[draft.kind]?.label} />
          </div>
          <button type="submit" disabled={saving} className="btn-primary">{saving ? 'Adding…' : 'Add rule'}</button>
        </form>
      </Panel>
    </div>
  );
};
