import React from 'react';
import { Location, MetarResponse, WeatherAlertItem, WeatherDataPoint } from '../../types/api';
import {
  displayName,
  fltCatClass,
  highestSeverity,
  severityDot,
  toKt,
  visibilityKm,
  windGroup,
} from './format';

interface StationTableProps {
  locations: Location[];
  weatherByLocation: Record<string, WeatherDataPoint>;
  metarByLocation: Record<string, MetarResponse>;
  alerts: WeatherAlertItem[];
  selectedLocationId?: string;
  onSelect: (loc: Location) => void;
}

export const StationTable: React.FC<StationTableProps> = ({
  locations,
  weatherByLocation,
  metarByLocation,
  alerts,
  selectedLocationId,
  onSelect,
}) => (
  <div className="overflow-auto h-full">
    <table className="data-table w-full text-xs">
      <thead className="sticky top-0 bg-slate-925 z-10">
        <tr>
          <th className="w-4" />
          <th>Site</th>
          <th className="text-right">Temp</th>
          <th>Wind</th>
          <th className="text-right">Vis km</th>
          <th>Ref. METAR</th>
        </tr>
      </thead>
      <tbody>
        {locations.map((loc) => {
          const wx = weatherByLocation[loc.id];
          const obs = metarByLocation[loc.id]?.observation;
          const locAlerts = alerts.filter((a) => a.location_id === loc.id);
          const sev = highestSeverity(locAlerts);
          const selected = loc.id === selectedLocationId;
          return (
            <tr
              key={loc.id}
              onClick={() => onSelect(loc)}
              className={`cursor-pointer ${selected ? 'bg-slate-800/70' : 'hover:bg-slate-900'}`}
            >
              <td className="!pr-0">
                <span
                  title={sev ? `${locAlerts.length} alert(s), highest ${sev}` : 'No alerts'}
                  className={`block w-2 h-2 ${sev ? severityDot[sev] : 'bg-slate-700'}`}
                />
              </td>
              <td>
                <div className={`whitespace-nowrap ${selected ? 'text-slate-100' : 'text-slate-300'}`}>{displayName(loc)}</div>
                <div className="font-mono text-[10px] text-slate-500 whitespace-nowrap">
                  {loc.latitude.toFixed(2)}N {loc.longitude.toFixed(2)}E
                  {loc.metadata_json?.elevation_m != null && ` · ${loc.metadata_json.elevation_m} m`}
                </div>
              </td>
              <td className="text-right font-mono text-slate-200">
                {wx?.temperature_celsius != null ? `${Math.round(wx.temperature_celsius)}°` : '—'}
              </td>
              <td className="font-mono text-slate-300 whitespace-nowrap">
                {wx ? windGroup(wx.wind_direction_deg, toKt(wx.wind_speed_kmh), toKt(wx.wind_gust_kmh)) : '—'}
              </td>
              <td className="text-right font-mono text-slate-300">{visibilityKm(wx?.visibility_m)}</td>
              <td>
                {obs ? (
                  <span className="inline-flex items-center gap-1.5 font-mono whitespace-nowrap">
                    <span className="text-slate-300">{obs.station_id}</span>
                    {obs.flight_category && (
                      <span className={`px-1 border text-[10px] leading-4 ${fltCatClass[obs.flight_category]}`}>
                        {obs.flight_category}
                      </span>
                    )}
                    <span className="text-[10px] text-slate-500">{Math.round(obs.distance_km)} km</span>
                  </span>
                ) : (
                  <span className="text-slate-600">—</span>
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  </div>
);
