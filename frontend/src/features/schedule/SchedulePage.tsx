import React, { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../../api/client';
import { ScheduleVersion, Resource, ValidationResult, WeatherAlertItem } from '../../types/api';
import {
  ErrorState,
  Notice,
  PageHeader,
  Panel,
  SkeletonPage,
  SkeletonTable,
  StatStrip,
  shortId,
} from '../../components/ui';
import { ScheduleTimeline } from './ScheduleTimeline';
import { ConflictPanel } from './ConflictPanel';

const HORIZONS = [24, 48, 72];

export const SchedulePage: React.FC = () => {
  const navigate = useNavigate();
  const [versions, setVersions] = useState<ScheduleVersion[]>([]);
  const [schedule, setSchedule] = useState<ScheduleVersion | null>(null);
  const [resources, setResources] = useState<Resource[]>([]);
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [weatherAlerts, setWeatherAlerts] = useState<WeatherAlertItem[]>([]);
  const [weatherState, setWeatherState] = useState<'loading' | 'ok' | 'error'>('loading');
  const [showWeather, setShowWeather] = useState(true);
  const [horizon, setHorizon] = useState(48);
  const [loading, setLoading] = useState(true);
  const [switching, setSwitching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const openVersion = useCallback(async (id: string) => {
    setSwitching(true);
    try {
      const [full, val] = await Promise.all([api.getSchedule(id), api.validateSchedule(id)]);
      setSchedule(full);
      setValidation(val);
    } catch (err: any) {
      setError(err?.message || 'Could not load schedule version.');
    } finally {
      setSwitching(false);
    }
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const scenarios = await api.getScenarios();
      if (!scenarios.length) return;
      const sc = scenarios[0];
      const [res, list] = await Promise.all([api.getResources(sc.id), api.getScenarioSchedules(sc.id)]);
      setResources(res);
      setVersions(list);
      const active = list.find((s) => s.status === 'APPROVED') ?? list[0];
      if (active) await openVersion(active.id);

      // Weather is fetched from live providers; don't hold the timeline for it
      setWeatherState('loading');
      api
        .getWeatherAlerts(sc.id)
        .then((r) => {
          setWeatherAlerts(r.alerts || []);
          setWeatherState('ok');
        })
        .catch(() => setWeatherState('error'));
    } catch (err: any) {
      setError(err?.message || 'Could not load the schedule.');
    } finally {
      setLoading(false);
    }
  }, [openVersion]);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) return <SkeletonPage />;

  const conflictResourceIds = (validation?.conflicts.map((c) => c.resource_id).filter(Boolean) as string[]) ?? [];
  const critHours = new Set(
    weatherAlerts.filter((a) => a.severity === 'CRITICAL').map((a) => a.forecast_timestamp.slice(0, 13)),
  ).size;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Timeline"
        subtitle="Assignments per resource over time, with forecast weather limits overlaid."
        actions={
          <>
            <select
              className="field font-mono"
              value={schedule?.id ?? ''}
              onChange={(e) => openVersion(e.target.value)}
              aria-label="Schedule version"
            >
              {versions.map((s) => (
                <option key={s.id} value={s.id}>
                  v{s.version_number} · {s.status.toLowerCase()}
                </option>
              ))}
            </select>
            <button onClick={() => schedule && openVersion(schedule.id)} disabled={switching} className="btn-secondary">
              {switching ? 'Validating…' : 'Re-validate'}
            </button>
            <button onClick={() => navigate('/disruptions')} className="btn-secondary">
              Log disruption
            </button>
            <button onClick={() => navigate('/optimisation')} className="btn-primary">
              Run optimiser
            </button>
          </>
        }
      />

      {error && <ErrorState message={error} onRetry={load} />}

      <StatStrip
        items={[
          { label: 'Version', value: schedule ? `v${schedule.version_number}` : '—', hint: schedule?.status.toLowerCase() },
          { label: 'Assignments', value: schedule?.assignments.length ?? 0 },
          {
            label: 'Conflicts',
            value: validation?.conflict_count ?? 0,
            tone: validation?.conflict_count ? 'crit' : 'ok',
          },
          {
            label: 'Unassigned',
            value: validation?.unassigned_task_count ?? 0,
            tone: validation?.unassigned_task_count ? 'warn' : 'default',
          },
          {
            label: 'Critical wx hours',
            value: weatherState === 'loading' ? '…' : weatherState === 'error' ? 'n/a' : critHours,
            tone: critHours ? 'crit' : 'default',
          },
          { label: 'Version ID', value: <span className="text-sm">{shortId(schedule?.id)}</span> },
        ]}
      />

      {weatherState === 'error' && showWeather && (
        <Notice tone="warn">Weather limits could not be loaded, so the overlay is empty. Missing data is not the same as clear weather.</Notice>
      )}

      <Panel
        title="Resource timeline"
        right={
          <div className="flex items-center gap-3 print:hidden">
            <label className="flex items-center gap-1.5 cursor-pointer">
              <input
                type="checkbox"
                checked={showWeather}
                onChange={(e) => setShowWeather(e.target.checked)}
                className="accent-indigo-500"
              />
              Weather overlay
            </label>
            <div className="flex border border-slate-800" role="group" aria-label="Time range">
              {HORIZONS.map((h) => (
                <button
                  key={h}
                  onClick={() => setHorizon(h)}
                  className={`px-2 h-6 font-mono ${horizon === h ? 'bg-slate-800 text-slate-100' : 'text-slate-500 hover:text-slate-300'}`}
                >
                  {h}h
                </button>
              ))}
            </div>
          </div>
        }
      >
        {switching && !schedule ? (
          <SkeletonTable rows={8} cols={6} />
        ) : schedule ? (
          <ScheduleTimeline
            resources={resources}
            assignments={schedule.assignments}
            conflictResourceIds={conflictResourceIds}
            weatherAlerts={showWeather ? weatherAlerts : []}
            horizonHours={horizon}
          />
        ) : (
          <div className="p-4 text-xs text-slate-500">No schedule version for this scenario.</div>
        )}
      </Panel>

      {validation && (
        <Panel title="Conflicts" right={`${validation.conflict_count} found by the independent validator`}>
          <ConflictPanel conflicts={validation.conflicts} isValid={validation.is_valid} />
        </Panel>
      )}
    </div>
  );
};
