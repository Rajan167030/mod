import React, { useCallback, useEffect, useState } from 'react';
import { Search } from 'lucide-react';
import { api } from '../../api/client';
import { Task } from '../../types/api';
import {
  Badge,
  EmptyState,
  ErrorState,
  PageHeader,
  Panel,
  SkeletonTable,
  StatStrip,
  fmtZulu,
  shortId,
} from '../../components/ui';

const PRIORITIES: Task['priority'][] = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'];
const priorityRank: Record<string, number> = { CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3 };

const fmtMinutes = (m: number) => (m >= 60 ? `${Math.floor(m / 60)}h${m % 60 ? ` ${m % 60}m` : ''}` : `${m}m`);

export const TaskManagementPage: React.FC = () => {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [priorityFilter, setPriorityFilter] = useState('ALL');

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setTasks(await api.getTasks());
    } catch (err: any) {
      setError(err?.message || 'Could not load tasks.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const filtered = tasks
    .filter((t) => {
      const q = search.toLowerCase();
      const matches =
        !q || t.name.toLowerCase().includes(q) || t.requirements.some((r) => r.requirement_value.toLowerCase().includes(q));
      return matches && (priorityFilter === 'ALL' || t.priority === priorityFilter);
    })
    .sort(
      (a, b) =>
        priorityRank[a.priority] - priorityRank[b.priority] || a.earliest_start.localeCompare(b.earliest_start),
    );

  const byPriority = (p: string) => tasks.filter((t) => t.priority === p).length;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Tasks"
        subtitle="Sorties and jobs to schedule. Each must fit inside its window on a resource holding the required qualification."
      />

      {error && <ErrorState message={error} onRetry={load} />}

      <StatStrip
        loading={loading}
        items={[
          { label: 'Total', value: tasks.length },
          { label: 'Critical', value: byPriority('CRITICAL'), tone: byPriority('CRITICAL') ? 'crit' : 'default' },
          { label: 'High', value: byPriority('HIGH'), tone: byPriority('HIGH') ? 'warn' : 'default' },
          { label: 'Medium / low', value: byPriority('MEDIUM') + byPriority('LOW') },
          { label: 'Scheduled', value: tasks.filter((t) => t.status === 'SCHEDULED').length, tone: 'ok' },
          { label: 'Pending', value: tasks.filter((t) => t.status === 'PENDING').length },
        ]}
      />

      <Panel
        title="Task list"
        right={
          <div className="flex items-center gap-2 print:hidden">
            <div className="relative">
              <Search className="w-3 h-3 text-slate-500 absolute left-2 top-1/2 -translate-y-1/2" />
              <input
                className="field h-7 pl-6 w-48"
                placeholder="Name or qualification"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                aria-label="Search tasks"
              />
            </div>
            <select
              className="field h-7"
              value={priorityFilter}
              onChange={(e) => setPriorityFilter(e.target.value)}
              aria-label="Filter by priority"
            >
              <option value="ALL">All priorities</option>
              {PRIORITIES.map((p) => (
                <option key={p} value={p}>
                  {p.charAt(0) + p.slice(1).toLowerCase()}
                </option>
              ))}
            </select>
          </div>
        }
      >
        {loading ? (
          <SkeletonTable rows={10} cols={6} />
        ) : tasks.length === 0 ? (
          <EmptyState title="No tasks" description="Add demo data from the Scenarios page to create a task backlog." />
        ) : filtered.length === 0 ? (
          <EmptyState compact title="No matches" description="Try a different name, qualification or priority." />
        ) : (
          <div className="overflow-x-auto">
            <table className="data-table w-full text-xs">
              <thead>
                <tr>
                  <th>Task</th>
                  <th>Priority</th>
                  <th className="text-right">Duration</th>
                  <th>Window opens</th>
                  <th>Must finish by</th>
                  <th>Requires</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((t) => (
                  <tr key={t.id} className="hover:bg-slate-900">
                    <td>
                      <div className="text-slate-100">{t.name}</div>
                      <div className="font-mono text-[10px] text-slate-500">{shortId(t.id)}</div>
                    </td>
                    <td>
                      <Badge status={t.priority} />
                    </td>
                    <td className="text-right font-mono text-slate-300">{fmtMinutes(t.duration_minutes)}</td>
                    <td className="font-mono text-slate-400 whitespace-nowrap">{fmtZulu(t.earliest_start)}</td>
                    <td className="font-mono text-slate-400 whitespace-nowrap">{fmtZulu(t.latest_finish)}</td>
                    <td>
                      <div className="flex flex-wrap gap-1">
                        {t.requirements.length === 0 && <span className="text-slate-600">—</span>}
                        {t.requirements.map((r, i) => (
                          <span key={i} className="px-1.5 border border-slate-700 font-mono text-[10px] text-slate-400">
                            {r.requirement_value}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td>
                      <Badge status={t.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
};
