import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Search } from 'lucide-react';
import { api } from '../../api/client';
import { AuditEvent } from '../../types/api';
import {
  Badge,
  EmptyState,
  ErrorState,
  PageHeader,
  Panel,
  SkeletonTable,
  fmtZulu,
  humanize,
  shortId,
} from '../../components/ui';

const metadataSummary = (m?: Record<string, unknown>) => {
  if (!m || Object.keys(m).length === 0) return '';
  return Object.entries(m)
    .map(([k, v]) => `${k}=${typeof v === 'object' ? JSON.stringify(v) : String(v)}`)
    .join('  ');
};

export const AuditPage: React.FC = () => {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [entity, setEntity] = useState('ALL');
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setEvents(await api.getAuditEvents());
    } catch (err: any) {
      setError(err?.message || 'Could not load the audit log. Viewers do not have access to it.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const entities = useMemo(() => Array.from(new Set(events.map((e) => e.entity_type))).sort(), [events]);

  const filtered = events.filter((e) => {
    const q = search.toLowerCase();
    const matches =
      !q ||
      e.action.toLowerCase().includes(q) ||
      (e.actor_email ?? '').toLowerCase().includes(q) ||
      (e.entity_id ?? '').toLowerCase().includes(q);
    return matches && (entity === 'ALL' || e.entity_type === entity);
  });

  return (
    <div className="space-y-4">
      <PageHeader
        title="Audit log"
        subtitle="Append-only record of sign-ins, data changes, solver runs and approvals. Passwords and tokens are never stored."
      />

      {error && <ErrorState message={error} onRetry={load} />}

      <Panel
        title="Events"
        right={
          <div className="flex items-center gap-2 print:hidden">
            <span className="text-slate-500">
              {filtered.length} of {events.length}
            </span>
            <div className="relative">
              <Search className="w-3 h-3 text-slate-500 absolute left-2 top-1/2 -translate-y-1/2" />
              <input
                className="field h-7 pl-6 w-52"
                placeholder="Action, user or entity ID"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                aria-label="Search audit events"
              />
            </div>
            <select className="field h-7" value={entity} onChange={(e) => setEntity(e.target.value)} aria-label="Filter by entity">
              <option value="ALL">All entities</option>
              {entities.map((x) => (
                <option key={x} value={x}>
                  {humanize(x)}
                </option>
              ))}
            </select>
          </div>
        }
      >
        {loading ? (
          <SkeletonTable rows={12} cols={5} />
        ) : events.length === 0 && !error ? (
          <EmptyState title="No events recorded" />
        ) : filtered.length === 0 ? (
          <EmptyState compact title="No matches" description="Try a different search or entity filter." />
        ) : (
          <div className="overflow-x-auto">
            <table className="data-table w-full text-xs">
              <thead>
                <tr>
                  <th>Time (UTC)</th>
                  <th>Action</th>
                  <th>Entity</th>
                  <th>Actor</th>
                  <th>Details</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((e) => {
                  const meta = metadataSummary(e.metadata_json);
                  const open = expanded === e.id;
                  return (
                    <tr
                      key={e.id}
                      className={`align-top ${meta ? 'cursor-pointer hover:bg-slate-900' : ''}`}
                      onClick={() => meta && setExpanded(open ? null : e.id)}
                    >
                      <td className="font-mono text-slate-500 whitespace-nowrap">{fmtZulu(e.created_at)}</td>
                      <td className="font-mono text-slate-200 whitespace-nowrap">{e.action}</td>
                      <td className="whitespace-nowrap">
                        <Badge status={e.entity_type} />
                        {e.entity_id && <span className="ml-1.5 font-mono text-[10px] text-slate-500">{shortId(e.entity_id)}</span>}
                      </td>
                      <td className="text-slate-400 whitespace-nowrap">{e.actor_email ?? 'system'}</td>
                      <td className="font-mono text-[11px] text-slate-500 max-w-[480px]">
                        {open ? (
                          <pre className="whitespace-pre-wrap break-words text-slate-300">
                            {JSON.stringify(e.metadata_json, null, 2)}
                          </pre>
                        ) : (
                          <div className="truncate">{meta || '—'}</div>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
};
