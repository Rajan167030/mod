import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { api } from '../../api/client';
import { Scenario } from '../../types/api';
import {
  Badge,
  EmptyState,
  ErrorState,
  Notice,
  PageHeader,
  Panel,
  SkeletonTable,
  fmtZulu,
  shortId,
} from '../../components/ui';

export const ScenarioListPage: React.FC = () => {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ tone: 'ok' | 'crit'; text: string } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setScenarios(await api.getScenarios());
    } catch (err: any) {
      setError(err?.message || 'Could not load scenarios.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      await api.createScenario({ name, description, status: 'ACTIVE' });
      setName('');
      setDescription('');
      setFormOpen(false);
      setNotice({ tone: 'ok', text: `Scenario “${name}” created.` });
      load();
    } catch (err: any) {
      setNotice({ tone: 'crit', text: err?.message || 'Could not create scenario.' });
    } finally {
      setSaving(false);
    }
  };

  const handleGenerate = async (s: Scenario) => {
    setBusyId(s.id);
    try {
      const res = await api.generateSyntheticData(s.id);
      setNotice({
        tone: 'ok',
        text: `Added ${res.resources_generated} resources and ${res.tasks_generated} tasks to “${s.name}”.`,
      });
      load();
    } catch (err: any) {
      setNotice({ tone: 'crit', text: err?.message || 'Could not generate data.' });
    } finally {
      setBusyId(null);
    }
  };

  const [pendingDelete, setPendingDelete] = useState<Scenario | null>(null);

  const handleBranch = async (s: Scenario) => {
    setBusyId(s.id);
    try {
      const b = await api.createBranch(s.id);
      setNotice({ tone: 'ok', text: `Branch “${b.name}” created. Change it freely, then compare it with the original.` });
      load();
    } catch (err: any) {
      setNotice({ tone: 'crit', text: err?.message || 'Could not create the branch.' });
    } finally {
      setBusyId(null);
    }
  };

  const handleDelete = async () => {
    const s = pendingDelete;
    setPendingDelete(null);
    if (!s) return;
    try {
      await api.deleteBranch(s.id);
      setNotice({ tone: 'ok', text: `Branch “${s.name}” deleted.` });
      load();
    } catch (err: any) {
      setNotice({ tone: 'crit', text: err?.message || 'Could not delete the branch.' });
    }
  };

  const nameOf = (id?: string | null) => scenarios.find((x) => x.id === id)?.name ?? 'a deleted scenario';

  return (
    <div className="space-y-4">
      <PageHeader
        title="Scenarios"
        subtitle="Each scenario is an isolated planning sandbox with its own resources, tasks and schedule versions."
        actions={
          <button onClick={() => setFormOpen((v) => !v)} className="btn-primary">
            {formOpen ? 'Cancel' : 'New scenario'}
          </button>
        }
      />

      {notice && (
        <Notice tone={notice.tone} onDismiss={() => setNotice(null)}>
          {notice.text}
        </Notice>
      )}

      {formOpen && (
        <Panel title="New scenario">
          <form onSubmit={handleCreate} className="p-3 grid grid-cols-1 md:grid-cols-[260px_1fr_auto] gap-3 items-end">
            <div>
              <label className="label" htmlFor="sc-name">
                Name
              </label>
              <input
                id="sc-name"
                className="field w-full"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. Winter airlift rotation"
                required
                autoFocus
              />
            </div>
            <div>
              <label className="label" htmlFor="sc-desc">
                Description
              </label>
              <input
                id="sc-desc"
                className="field w-full"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Context and constraints"
              />
            </div>
            <button type="submit" className="btn-primary" disabled={saving}>
              {saving ? 'Creating…' : 'Create'}
            </button>
          </form>
        </Panel>
      )}

      {error && <ErrorState message={error} onRetry={load} />}

      <Panel title="All scenarios" right={!loading && `${scenarios.length} total`}>
        {loading ? (
          <SkeletonTable rows={3} cols={4} />
        ) : scenarios.length === 0 ? (
          <EmptyState
            title="No scenarios yet"
            description="Create a scenario to start adding resources, tasks and weather sites."
            action={
              <button onClick={() => setFormOpen(true)} className="btn-primary">
                New scenario
              </button>
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="data-table w-full text-xs">
              <thead>
                <tr>
                  <th>Scenario</th>
                  <th>Status</th>
                  <th>Created</th>
                  <th>ID</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {scenarios.map((s) => (
                  <tr key={s.id} className="hover:bg-slate-900">
                    <td className="max-w-xl">
                      <div className="text-slate-100">{s.parent_scenario_id && <span className="text-slate-500 mr-1">↳</span>}{s.name}</div>
                      {s.parent_scenario_id ? (
                        <div className="text-slate-500 truncate">branch of {nameOf(s.parent_scenario_id)}</div>
                      ) : (
                        s.description && <div className="text-slate-500 truncate">{s.description}</div>
                      )}
                    </td>
                    <td>
                      <Badge status={s.status} />
                    </td>
                    <td className="font-mono text-slate-400 whitespace-nowrap">{fmtZulu(s.created_at)}</td>
                    <td className="font-mono text-slate-500">{shortId(s.id)}</td>
                    <td className="text-right whitespace-nowrap space-x-1.5">
                      {s.parent_scenario_id && (
                        <>
                          <Link to={`/compare?a=${s.parent_scenario_id}&b=${s.id}`} className="btn-secondary h-7">Compare</Link>
                          <button onClick={() => setPendingDelete(s)} className="btn-danger h-7">Delete</button>
                        </>
                      )}
                      <button onClick={() => handleBranch(s)} disabled={busyId === s.id} className="btn-secondary h-7" title="Copy this scenario to try changes safely">
                        Branch
                      </button>
                      <button
                        onClick={() => handleGenerate(s)}
                        disabled={busyId === s.id}
                        className="btn-secondary h-7"
                        title="Append generated demo resources and tasks"
                      >
                        {busyId === s.id ? 'Generating…' : 'Add demo data'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
          <ConfirmDialog
        isOpen={pendingDelete != null}
        title={`Delete branch “${pendingDelete?.name}”?`}
        description="The branch and everything in it is removed. The scenario it was branched from is not affected."
        confirmLabel="Delete branch"
        isDestructive
        onConfirm={handleDelete}
        onCancel={() => setPendingDelete(null)}
      />
    </div>
  );
};
