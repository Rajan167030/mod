import React from 'react';
import { WeatherDataPoint } from '../../types/api';
import { fmt, toKt, visibilityKm, windGroup, zuluTime } from './format';

interface ForecastTableProps {
  points: WeatherDataPoint[];
  windWarnKmh: number;
  windCritKmh: number;
}

/** Hour-by-hour grid (columns = hours), the layout forecasters use on point-forecast sheets. */
export const ForecastTable: React.FC<ForecastTableProps> = ({ points, windWarnKmh, windCritKmh }) => {
  const windCell = (p: WeatherDataPoint) => {
    const peak = Math.max(p.wind_speed_kmh ?? 0, p.wind_gust_kmh ?? 0);
    if (peak >= windCritKmh) return 'bg-crit/15 text-crit';
    if (peak >= windWarnKmh) return 'bg-warn/15 text-warn';
    return 'text-slate-200';
  };

  const rows: { label: string; render: (p: WeatherDataPoint) => React.ReactNode; cls?: (p: WeatherDataPoint) => string }[] = [
    {
      label: 'Wind kt',
      render: (p) => windGroup(p.wind_direction_deg, toKt(p.wind_speed_kmh), toKt(p.wind_gust_kmh)).replace('KT', ''),
      cls: windCell,
    },
    { label: 'Temp °C', render: (p) => fmt(p.temperature_celsius) },
    { label: 'Dew °C', render: (p) => fmt(p.dew_point_celsius) },
    {
      label: 'Vis km',
      render: (p) => visibilityKm(p.visibility_m),
      cls: (p) => (p.visibility_m != null && p.visibility_m < 5000 ? 'text-warn' : ''),
    },
    { label: 'Cloud %', render: (p) => fmt(p.cloud_cover_pct) },
    {
      label: 'Precip mm',
      render: (p) => (p.precipitation_mm ? p.precipitation_mm.toFixed(1) : '·'),
      cls: (p) => (p.precipitation_mm ? 'text-info' : 'text-slate-600'),
    },
    { label: 'RH %', render: (p) => fmt(p.relative_humidity_pct) },
    { label: 'QNH hPa', render: (p) => fmt(p.pressure_hpa) },
  ];

  return (
    <div className="overflow-x-auto">
      <table className="text-[11px] font-mono border-collapse">
        <thead>
          <tr>
            <th className="sticky left-0 bg-slate-925 z-10 px-3 py-1.5 text-left font-sans font-medium text-slate-500 border-b border-r border-slate-800">
              UTC
            </th>
            {points.map((p, i) => {
              const d = new Date(p.forecast_timestamp);
              const newDay = i > 0 && d.getUTCHours() === 0;
              return (
                <th
                  key={p.forecast_timestamp}
                  className={`px-2 py-1.5 font-medium text-slate-400 border-b border-slate-800 text-center ${newDay ? 'border-l border-l-slate-600' : ''}`}
                >
                  {zuluTime(p.forecast_timestamp).slice(0, 2)}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.label}>
              <td className="sticky left-0 bg-slate-925 z-10 px-3 py-1.5 font-sans text-slate-500 border-b border-r border-slate-800 whitespace-nowrap">
                {row.label}
              </td>
              {points.map((p, i) => {
                const newDay = i > 0 && new Date(p.forecast_timestamp).getUTCHours() === 0;
                return (
                  <td
                    key={p.forecast_timestamp}
                    className={`px-2 py-1.5 text-center whitespace-nowrap border-b border-slate-800/60 ${newDay ? 'border-l border-l-slate-600' : ''} ${row.cls?.(p) ?? 'text-slate-300'}`}
                  >
                    {row.render(p)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};
