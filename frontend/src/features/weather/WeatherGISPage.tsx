import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { api } from '../../api/client';
import {
  Location,
  MetarResponse,
  Scenario,
  WeatherAlertItem,
  WeatherDataPoint,
  WeatherForecastResponse,
} from '../../types/api';
import { GeoSpatialMap } from '../../components/map/GeoSpatialMap';
import { StationTable } from './StationTable';
import { MetarPanel } from './MetarPanel';
import { ForecastTable } from './ForecastTable';
import { WindChart } from './WindChart';
import { AlertsTable } from './AlertsTable';
import { EmptyState, ErrorState, Panel, Skeleton, SkeletonTable } from '../../components/ui';
import { displayName, locationTypeLabel, minutesAgo, windThresholdsKmh, zuluTime } from './format';

const FORECAST_HOURS = 36;

export const WeatherGISPage: React.FC = () => {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenarioId, setScenarioId] = useState('');
  const [locations, setLocations] = useState<Location[]>([]);
  const [selected, setSelected] = useState<Location | null>(null);

  const [alerts, setAlerts] = useState<WeatherAlertItem[]>([]);
  const [weatherByLocation, setWeatherByLocation] = useState<Record<string, WeatherDataPoint>>({});
  const [metarByLocation, setMetarByLocation] = useState<Record<string, MetarResponse>>({});
  const [forecast, setForecast] = useState<WeatherForecastResponse | null>(null);
  const [retrievedAt, setRetrievedAt] = useState<string | null>(null);

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getScenarios()
      .then((s) => {
        setScenarios(s);
        if (s.length) setScenarioId(s[0].id);
        else setLoading(false);
      })
      .catch(() => {
        setError('Could not load scenarios.');
        setLoading(false);
      });
  }, []);

  const loadStations = useCallback(async (locs: Location[]) => {
    const current: Record<string, WeatherDataPoint> = {};
    const metars: Record<string, MetarResponse> = {};
    let latest: string | null = null;

    await Promise.all(
      locs.map(async (loc) => {
        const [cur, met] = await Promise.allSettled([api.getCurrentWeather(loc.id), api.getMetar(loc.id)]);
        if (cur.status === 'fulfilled' && cur.value.data) {
          current[loc.id] = cur.value.data;
          if (cur.value.retrieved_at && (!latest || cur.value.retrieved_at > latest)) latest = cur.value.retrieved_at;
        }
        if (met.status === 'fulfilled') metars[loc.id] = met.value;
      }),
    );

    setWeatherByLocation(current);
    setMetarByLocation(metars);
    setRetrievedAt(latest);
    if (locs.length && Object.keys(current).length === 0) {
      setError('Weather provider returned no data. Check the backend can reach api.open-meteo.com.');
    }
  }, []);

  useEffect(() => {
    if (!scenarioId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);

    (async () => {
      try {
        const [locs, alertResp] = await Promise.all([
          api.getLocations(scenarioId),
          api.getWeatherAlerts(scenarioId),
        ]);
        if (cancelled) return;
        setLocations(locs);
        setAlerts(alertResp.alerts || []);
        setSelected((prev) => locs.find((l) => l.id === prev?.id) ?? locs[0] ?? null);
        await loadStations(locs);
      } catch {
        if (!cancelled) setError('Could not load sites for this scenario.');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [scenarioId, loadStations]);

  useEffect(() => {
    if (!selected) return;
    setForecast(null);
    api.getWeatherForecast(selected.id).then(setForecast).catch(() => setForecast(null));
  }, [selected]);

  const handleRefresh = async () => {
    if (!scenarioId) return;
    setRefreshing(true);
    setError(null);
    try {
      await api.refreshWeather(scenarioId, true);
      const alertResp = await api.getWeatherAlerts(scenarioId);
      setAlerts(alertResp.alerts || []);
      await loadStations(locations);
      if (selected) setForecast(await api.getWeatherForecast(selected.id));
    } catch (err: any) {
      setError(err?.message || 'Refresh failed.');
    } finally {
      setRefreshing(false);
    }
  };

  const upcoming = useMemo(() => {
    const from = Date.now() - 60 * 60 * 1000;
    return (forecast?.forecast_points || [])
      .filter((p) => new Date(p.forecast_timestamp).getTime() >= from)
      .slice(0, FORECAST_HOURS);
  }, [forecast]);

  const { warn, crit } = windThresholdsKmh(alerts);
  const critCount = alerts.filter((a) => a.severity === 'CRITICAL').length;
  const warnCount = alerts.filter((a) => a.severity === 'WARNING').length;
  const selectedAlerts = alerts.filter((a) => a.location_id === selected?.id);

  return (
    <div className="space-y-4 pb-8">
      {/* Title row */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-slate-100">Weather</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            {locations.length} sites · hourly model forecast (Open-Meteo) · nearest airport METAR/TAF (NOAA AWC)
          </p>
        </div>

        <div className="flex items-center gap-2 text-xs">
          <span className="text-slate-500 mr-2">
            {retrievedAt ? (
              <>
                Model run fetched <span className="font-mono text-slate-300">{zuluTime(retrievedAt)}</span> ({minutesAgo(retrievedAt)})
              </>
            ) : loading ? (
              'Loading…'
            ) : (
              'No data'
            )}
          </span>
          <select
            value={scenarioId}
            onChange={(e) => setScenarioId(e.target.value)}
            className="field max-w-[260px] print:hidden"
          >
            {scenarios.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={handleRefresh}
            disabled={refreshing || !scenarioId}
            className="btn-secondary print:hidden"
          >
            <RefreshCw className={`w-3 h-3 ${refreshing ? 'animate-spin' : ''}`} />
            {refreshing ? 'Refreshing' : 'Refresh'}
          </button>
        </div>
      </div>

      {error && <ErrorState message={error} onRetry={handleRefresh} />}

      {/* Sites + map */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-4">
        <Panel
          title="Sites"
          right={
            <span className="font-mono">
              <span className="text-crit">{critCount} crit</span> · <span className="text-warn">{warnCount} warn</span>
            </span>
          }
          className="xl:col-span-5 h-[460px]"
        >
          {loading && locations.length === 0 ? (
            <SkeletonTable rows={6} cols={4} />
          ) : locations.length === 0 ? (
            <EmptyState
              compact
              title="No sites in this scenario"
              description="Add locations to the scenario to see their weather here."
            />
          ) : (
            <StationTable
              locations={locations}
              weatherByLocation={weatherByLocation}
              metarByLocation={metarByLocation}
              alerts={alerts}
              selectedLocationId={selected?.id}
              onSelect={setSelected}
            />
          )}
        </Panel>

        <Panel title="Map" right="Click a site to inspect" className="xl:col-span-7 h-[460px] print:hidden">
          <GeoSpatialMap
            locations={locations}
            alerts={alerts}
            weatherByLocation={weatherByLocation}
            metarStations={Object.values(metarByLocation)
              .map((m) => m.observation)
              .filter((o): o is NonNullable<typeof o> => o != null)}
            selectedLocationId={selected?.id}
            onSelectLocation={setSelected}
          />
        </Panel>
      </div>

      {selected && (
        <>
          <div className="flex items-baseline gap-3 pt-2 border-t border-slate-800">
            <h2 className="text-base font-semibold text-slate-100">{displayName(selected)}</h2>
            <span className="text-xs text-slate-500">
              {locationTypeLabel[selected.location_type] ?? selected.location_type}
              {selected.metadata_json?.elevation_m != null && ` · ${selected.metadata_json.elevation_m} m AMSL`}
              <span className="font-mono ml-2">
                {selected.latitude.toFixed(3)}N {selected.longitude.toFixed(3)}E
              </span>
            </span>
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-12 gap-4">
            <Panel title="Nearest observation" right="METAR · TAF" className="xl:col-span-5">
              <MetarPanel metar={metarByLocation[selected.id]} isLoading={loading} />
            </Panel>

            <Panel
              title="Wind forecast"
              right={`kt · next ${upcoming.length} h`}
              className="xl:col-span-7"
            >
              <div className="p-2">
                {upcoming.length ? (
                  <WindChart points={upcoming} windWarnKmh={warn} windCritKmh={crit} />
                ) : (
                  <Skeleton className="h-[220px] w-full" />
                )}
              </div>
            </Panel>
          </div>

          <Panel title="Hourly forecast" right={forecast ? `${forecast.provider} · model grid point` : undefined}>
            {upcoming.length ? (
              <ForecastTable points={upcoming} windWarnKmh={warn} windCritKmh={crit} />
            ) : (
              <SkeletonTable rows={8} cols={10} />
            )}
          </Panel>

          <Panel title="Limit exceedances" right={`${selectedAlerts.length} for this site · ${alerts.length} total`}>
            <AlertsTable alerts={alerts} onlyLocationId={selected.id} />
          </Panel>
        </>
      )}

      <p className="text-[11px] text-slate-600">
        Sites and limits are fictional training values. Model and METAR data are live and unverified — not for
        operational use.
      </p>
    </div>
  );
};
