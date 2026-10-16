import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Search } from 'lucide-react';
import { api } from '../../api/client';
import { Resource } from '../../types/api';
import {
  Badge,
  EmptyState,
  ErrorState,
  PageHeader,
  Panel,
  SkeletonTable,
  StatStrip,
  humanize,
  shortId,
} from '../../components/ui';

const capacityText = (r: Resource) => {
  const m = r.metadata_json ?? {};
  if (m.max_payload_kg) return `${m.max_payload_kg.toLocaleString()} kg payload`;
  if (m.capacity) return `${m.capacity} concurrent`;
  return '—';
};

export const ResourceManagementPage: React.FC = () => {
  const [resources, setResources] = useState<Resource[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState('ALL');

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setResources(await api.getResources());
    } catch (err: any) {
      setError(err?.message || 'Could not load resources.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const types = useMemo(() => Array.from(new Set(resources.map((r) => r.resource_type))).sort(), [resources]);

  const filtered = resources.filter((r) => {
    const q = search.toLowerCase();
    const quals: string[] = r.metadata_json?.qualifications ?? [];
    const matches =
      !q || r.name.toLowerCase().includes(q) || quals.some((x) => x.toLowerCase().includes(q));
    return matches && (typeFilter === 'ALL' || r.resource_type === typeFilter);
  });

  const count = (status: Resource['status']) => resources.filter((r) => r.status === status).length;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Resources"
        subtitle="Aircraft, crews and facilities available to the scheduler, with the qualifications tasks can require."
      />

      {error && <ErrorState message={error} onRetry={load} />}

      <StatStrip
        loading={loading}
        items={[
          { label: 'Total', value: resources.length },
          { label: 'Available', value: count('AVAILABLE'), tone: 'ok' },
          { label: 'Maintenance', value: count('MAINTENANCE'), tone: count('MAINTENANCE') ? 'warn' : 'default' },
          { label: 'Grounded', value: count('GROUNDED'), tone: count('GROUNDED') ? 'crit' : 'default' },
          { label: 'Types', value: types.length },
          { label: 'Unavailable', value: count('UNAVAILABLE') },
        ]}
      />

      <Panel
        title="Inventory"
        right={
          <div className="flex items-center gap-2 print:hidden">
            <div className="relative">
              <Search className="w-3 h-3 text-slate-500 absolute left-2 top-1/2 -translate-y-1/2" />
              <input
                className="field h-7 pl-6 w-48"
                placeholder="Name or qualification"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                aria-label="Search resources"
              />
            </div>
            <select className="field h-7" value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)} aria-label="Filter by type">
              <option value="ALL">All types</option>
              {types.map((t) => (
                <option key={t} value={t}>
                  {humanize(t)}
                </option>
              ))}
            </select>
          </div>
        }
      >
        {loading ? (
          <SkeletonTable rows={8} cols={5} />
        ) : resources.length === 0 ? (
          <EmptyState title="No resources" description="Add demo data from the Scenarios page to populate the fleet." />
        ) : filtered.length === 0 ? (
          <EmptyState compact title="No matches" description="Try a different name, qualification or type." />
        ) : (
          <div className="overflow-x-auto">
            <table className="data-table w-full text-xs">
              <thead>
                <tr>
                  <th>Callsign</th>
                  <th>Type</th>
                  <th>Status</th>
                  <th>Capacity</th>
                  <th>Qualifications</th>
                  <th>ID</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((r) => (
                  <tr key={r.id} className="hover:bg-slate-900">
                    <td className="font-mono text-slate-100 whitespace-nowrap">{r.name}</td>
                    <td className="text-slate-400 whitespace-nowrap">{humanize(r.resource_type)}</td>
                    <td>
                      <Badge status={r.status} />
                    </td>
                    <td className="font-mono text-slate-400 whitespace-nowrap">{capacityText(r)}</td>
                    <td>
                      <div className="flex flex-wrap gap-1">
                        {(r.metadata_json?.qualifications ?? []).map((q: string) => (
                          <span key={q} className="px-1.5 border border-slate-700 font-mono text-[10px] text-slate-400">
                            {q}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="font-mono text-slate-500">{shortId(r.id)}</td>
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
