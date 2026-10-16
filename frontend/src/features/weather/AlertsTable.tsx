import React, { useMemo } from 'react';
import { WeatherAlertItem } from '../../types/api';
import { EmptyState } from '../../components/ui';
import { displayName, severityRank, severityText, toKt, zuluDayTime } from './format';

interface AlertsTableProps {
  alerts: WeatherAlertItem[];
  onlyLocationId?: string;
}

const variableLabel: Record<string, string> = {
  wind_speed: 'Wind',
  precipitation: 'Precip',
  temperature: 'Temp',
  all: 'No data',
};

const valueText = (a: WeatherAlertItem) => {
  if (a.variable === 'wind_speed') return `${toKt(a.observed_value)} kt / ${toKt(a.threshold)}`;
  if (a.variable === 'precipitation') return `${a.observed_value.toFixed(1)} mm / ${a.threshold}`;
  if (a.variable === 'temperature') return `${a.observed_value.toFixed(0)}° / ${a.threshold}°`;
  return '—';
};

export const AlertsTable: React.FC<AlertsTableProps> = ({ alerts, onlyLocationId }) => {
  const rows = useMemo(
    () =>
      alerts
        .filter((a) => !onlyLocationId || a.location_id === onlyLocationId)
        .sort(
          (a, b) =>
            severityRank[b.severity] - severityRank[a.severity] ||
            a.forecast_timestamp.localeCompare(b.forecast_timestamp),
        ),
    [alerts, onlyLocationId],
  );

  if (rows.length === 0) {
    return <EmptyState compact title="No limits exceeded" description="Nothing in the forecast window crosses the alert thresholds." />;
  }

  return (
    <div className="overflow-auto max-h-[360px]">
      <table className="data-table w-full text-xs">
        <thead className="sticky top-0 bg-slate-925">
          <tr>
            <th>Sev</th>
            <th>Valid</th>
            {!onlyLocationId && <th>Site</th>}
            <th>Param</th>
            <th className="text-right">Value / limit</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((a, i) => (
            <tr key={i} title={a.explanation} className="hover:bg-slate-900">
              <td className={`font-mono text-[11px] ${severityText[a.severity]}`}>{a.severity.slice(0, 4)}</td>
              <td className="font-mono text-slate-300">{zuluDayTime(a.forecast_timestamp)}</td>
              {!onlyLocationId && <td className="text-slate-300">{displayName({ name: a.location_name })}</td>}
              <td className="text-slate-400">{variableLabel[a.variable] ?? a.variable}</td>
              <td className="text-right font-mono text-slate-200">{valueText(a)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};
