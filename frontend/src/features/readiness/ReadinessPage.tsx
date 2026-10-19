import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api/client';
import { Crew, CrewStatus, Scenario, StoreItem } from '../../types/api';
import { Badge, EmptyState, ErrorState, Notice, PageHeader, Panel, SkeletonTable, StatStrip, fmtZulu, humanize } from '../../components/ui';

const hm = (min: number) => `${Math.floor(min / 60)}h${String(min % 60).padStart(2, '0')}`;

const Bar: React.FC<{ value: number; max: number; tone?: string }> = ({ value, max, tone }) => {
  const pct = Math.min(100, Math.round((value / Math.max(1, max)) * 100));
  const color = tone ?? (pct >= 85 ? 'bg-crit' : pct >= 70 ? 'bg-warn' : 'bg-ok');
  return (
    <div className="h-1.5 w-28 bg-slate-800" title={`${pct}%`}>
      <div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
    </div>
  );
};

export const ReadinessPage: React.FC = () => {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenarioId, setScenarioId] = useState('');
  const [crews, setCrews] = useState<Crew[] | null>(null);
  const [stores, setStores] = useState<StoreItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [changed, setChanged] = useState(false);

  useEffect(() => {
    api.getScenarios().then((s) => {
      setScenarios(s);
      if (s[0]) setScenarioId(s[0].id);
    }).catch((e) => setError(e?.message || 'Could not load scenarios.'));
  }, []);

  const load = useCallback(async () => {
    if (!scenarioId) return;
    setError(null);
    try {
      const [c, s] = await Promise.all([api.getCrews(scenarioId), api.getStores(scenarioId)]);
      setCrews(c);
      setStores(s);
    } catch (e: any) {
      setError(e?.message || 'Could not load readiness.');
    }
  }, [scenarioId]);

  useEffect(() => {
    setCrews(null);
    setStores(null);
    setChanged(false);
    load();
  }, [load]);

  const setStatus = async (c: Crew, status: CrewStatus) => {
    try {
      await api.updateCrew(c.id, { status });
      setChanged(true);
      await load();
    } catch (e: any) {
      setError(e?.message || 'Could not update the crew.');
    }
  };

  const setQty = async (s: StoreItem, qty: number) => {
    if (qty === s.quantity || Number.isNaN(qty)) return;
    try {
      await api.updateStore(s.id, qty);
      setChanged(true);
      await load();
    } catch (e: any) {
      setError(e?.message || 'Could not update the stock.');
    }
  };

  const available = crews?.filter((c) => c.status === 'AVAILABLE') ?? [];
  const tired = crews?.filter((c) => c.duty_ratio >= 0.85) ?? [];
  const short = stores?.filter((s) => s.planned_use > s.quantity) ?? [];
  const noReserve = stores?.filter((s) => s.planned_use >= s.quantity && s.planned_use > 0) ?? [];

  return (
    <div className="space-y-4">
      <PageHeader
        title="Crews & stores"
        subtitle="Every sortie needs a crew current on the aircraft type, rested and inside its duty limit, and uses up the stores it carries. The optimiser plans within these limits; change them here and re-plan."
        actions={
          <select className="field max-w-[280px]" value={scenarioId} onChange={(e) => setScenarioId(e.target.value)} aria-label="Scenario">
            {scenarios.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        }
      />
      {error && <ErrorState message={error} onRetry={load} />}
      {changed && (
        <Notice tone="warn" onDismiss={() => setChanged(false)}>
          Readiness changed. The active plan may now break a rule.{' '}
          <Link to="/schedule" className="underline">Check the timeline</Link> or{' '}
          <Link to="/courses-of-action" className="underline">generate courses of action →</Link>
        </Notice>
      )}

      <StatStrip
        loading={!crews || !stores}
        items={[
          { label: 'Crews available', value: `${available.length}/${crews?.length ?? 0}`, tone: available.length < (crews?.length ?? 0) ? 'warn' : 'ok' },
          { label: 'Crews near duty limit', value: tired.length, hint: '85% or more after the plan', tone: tired.length ? 'warn' : 'default' },
          { label: 'Sorties crewed', value: crews?.reduce((n, c) => n + c.planned_sorties, 0) ?? 0 },
          { label: 'Store types', value: stores?.length ?? 0 },
          { label: 'Short of stock', value: short.length, tone: short.length ? 'crit' : 'ok' },
          { label: 'No reserve left', value: noReserve.length, tone: noReserve.length ? 'warn' : 'default' },
        ]}
      />

      <Panel title="Crews" right="duty after the active plan">
        {!crews ? (
          <SkeletonTable rows={6} cols={7} />
        ) : crews.length === 0 ? (
          <EmptyState compact title="No crews in this scenario" description="Without crews the optimiser only plans aircraft." />
        ) : (
          <div className="overflow-x-auto">
            <table className="data-table w-full text-xs">
              <thead>
                <tr>
                  <th>Crew</th>
                  <th>Flies</th>
                  <th>Status</th>
                  <th>Sorties</th>
                  <th>Duty used</th>
                  <th>Rest rule</th>
                  <th>Shift</th>
                  <th>Next sortie</th>
                </tr>
              </thead>
              <tbody>
                {crews.map((c) => (
                  <tr key={c.id} className={c.status === 'AVAILABLE' ? '' : 'opacity-60'}>
                    <td>
                      <div className="text-slate-200">{c.name}</div>
                      {c.notes && <div className="text-slate-500 max-w-xs truncate" title={c.notes}>{c.notes}</div>}
                    </td>
                    <td className="text-slate-400">{c.aircraft_types.map(humanize).join(', ') || 'any'}</td>
                    <td>
                      <select
                        className={`field h-7 ${c.status === 'AVAILABLE' ? '' : 'text-crit'}`}
                        value={c.status}
                        onChange={(e) => setStatus(c, e.target.value as CrewStatus)}
                        aria-label={`Status of ${c.name}`}
                      >
                        <option value="AVAILABLE">Available</option>
                        <option value="RESTING">Resting</option>
                        <option value="UNFIT">Unfit</option>
                      </select>
                    </td>
                    <td className="font-mono text-slate-300">{c.planned_sorties}</td>
                    <td>
                      <div className="flex items-center gap-2">
                        <Bar value={c.duty_used_minutes + c.planned_minutes} max={c.max_duty_minutes} />
                        <span className="font-mono text-slate-400 whitespace-nowrap">
                          {hm(c.duty_used_minutes + c.planned_minutes)} / {hm(c.max_duty_minutes)}
                        </span>
                      </div>
                      {c.duty_used_minutes > 0 && <div className="text-slate-500">{hm(c.duty_used_minutes)} flown before the plan</div>}
                    </td>
                    <td className="font-mono text-slate-400">{c.min_rest_minutes} min</td>
                    <td className="font-mono text-slate-400 whitespace-nowrap">
                      {c.duty_start || c.duty_end ? `${c.duty_start ? fmtZulu(c.duty_start) : 'open'} → ${c.duty_end ? fmtZulu(c.duty_end) : 'open'}` : 'open'}
                    </td>
                    <td className="font-mono text-slate-400 whitespace-nowrap">{c.next_sortie_at ? fmtZulu(c.next_sortie_at) : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel title="Stores: weapons, countermeasures, kits" right="held against what the active plan uses">
        {!stores ? (
          <SkeletonTable rows={3} cols={6} />
        ) : stores.length === 0 ? (
          <EmptyState compact title="No stores held" description="Tasks that need stores cannot be flown." />
        ) : (
          <div className="overflow-x-auto">
            <table className="data-table w-full text-xs">
              <thead>
                <tr>
                  <th>Store</th>
                  <th>Category</th>
                  <th>Held</th>
                  <th>Plan uses</th>
                  <th>All tasks need</th>
                  <th>Carried by</th>
                </tr>
              </thead>
              <tbody>
                {stores.map((s) => (
                  <tr key={s.id}>
                    <td>
                      <div className="text-slate-200">{s.name}</div>
                      <div className="font-mono text-slate-500">{s.store_type}</div>
                    </td>
                    <td><Badge status={s.category} tone={s.category === 'WEAPON' ? 'crit' : s.category === 'COUNTERMEASURE' ? 'warn' : 'info'} /></td>
                    <td>
                      <span className="flex items-center gap-1.5">
                        <input
                          key={`${s.id}-${s.quantity}`}
                          type="number"
                          min={0}
                          defaultValue={s.quantity}
                          onBlur={(e) => setQty(s, Number(e.target.value))}
                          onKeyDown={(e) => e.key === 'Enter' && (e.target as HTMLInputElement).blur()}
                          className="field h-7 w-16 font-mono"
                          aria-label={`Quantity of ${s.name}`}
                        />
                        <span className="text-slate-500">{s.unit}</span>
                      </span>
                    </td>
                    <td>
                      <div className="flex items-center gap-2">
                        <Bar value={s.planned_use} max={s.quantity} tone={s.planned_use > s.quantity ? 'bg-crit' : s.planned_use === s.quantity ? 'bg-warn' : 'bg-ok'} />
                        <span className={`font-mono ${s.planned_use > s.quantity ? 'text-crit' : 'text-slate-300'}`}>{s.planned_use}</span>
                      </div>
                    </td>
                    <td className={`font-mono ${s.demand > s.quantity ? 'text-warn' : 'text-slate-400'}`}>
                      {s.demand}{s.demand > s.quantity && ' · not enough for all'}
                    </td>
                    <td className="text-slate-400">{s.carriers.join(', ') || <span className="text-crit">no aircraft</span>}</td>
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
