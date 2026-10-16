import React from 'react';
import { MetarResponse } from '../../types/api';
import { Skeleton } from '../../components/ui';
import { fltCatClass, fmt, minutesAgo, windGroup, zuluDayTime } from './format';

interface MetarPanelProps {
  metar?: MetarResponse;
  isLoading: boolean;
}

const Row: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <div className="flex justify-between gap-4 py-1 border-b border-slate-800/60 last:border-0">
    <dt className="text-slate-500">{label}</dt>
    <dd className="font-mono text-slate-200 text-right">{children}</dd>
  </div>
);

/** Breaks a TAF into its change groups so each period reads on its own line. */
const tafLines = (raw: string) => raw.split(/\s+(?=(?:FM\d{6}|BECMG|TEMPO|PROB\d{2}))/);

export const MetarPanel: React.FC<MetarPanelProps> = ({ metar, isLoading }) => {
  if (isLoading && !metar) {
    return (
      <div className="p-3 space-y-3">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-16 w-full" />
      </div>
    );
  }
  const obs = metar?.observation;
  if (!obs) {
    return (
      <div className="p-4 text-xs text-slate-500">
        {metar?.message ?? 'No observation available.'}
      </div>
    );
  }

  return (
    <div className="p-3 space-y-3 text-xs">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-mono text-sm text-slate-100">{obs.station_id}</span>
            {obs.flight_category && (
              <span className={`px-1.5 border font-mono text-[10px] leading-4 ${fltCatClass[obs.flight_category]}`}>
                {obs.flight_category}
              </span>
            )}
          </div>
          <div className="text-slate-500 mt-0.5">
            {obs.station_name} · {obs.distance_km} km from site
          </div>
        </div>
        <div className="text-right text-slate-500">
          <div className="font-mono text-slate-300">{zuluDayTime(obs.observed_at)}</div>
          <div>{minutesAgo(obs.observed_at)}</div>
        </div>
      </div>

      <pre className="font-mono text-[12px] leading-relaxed text-ok bg-slate-950 border border-slate-800 px-2.5 py-2 whitespace-pre-wrap break-words">
        {obs.raw_metar}
      </pre>

      <dl className="grid grid-cols-2 gap-x-6">
        <div>
          <Row label="Wind">{windGroup(obs.wind_direction_deg, obs.wind_speed_kt, obs.wind_gust_kt)}</Row>
          <Row label="Visibility">{obs.visibility != null ? `${obs.visibility} SM` : '—'}</Row>
          <Row label="Temp / Dew">
            {fmt(obs.temperature_celsius, 0, '°')} / {fmt(obs.dew_point_celsius, 0, '°')}
          </Row>
        </div>
        <div>
          <Row label="QNH">{fmt(obs.altimeter_hpa, 0, ' hPa')}</Row>
          <Row label="Clouds">
            {obs.clouds.length
              ? obs.clouds.map((c) => `${c.cover}${c.base_ft != null ? String(c.base_ft / 100).padStart(3, '0') : ''}`).join(' ')
              : 'NSC'}
          </Row>
          <Row label="Elevation">{fmt(obs.elevation_m, 0, ' m')}</Row>
        </div>
      </dl>

      {obs.raw_taf && (
        <div>
          <div className="text-[10px] uppercase tracking-[0.08em] text-slate-500 mb-1">TAF</div>
          <pre className="font-mono text-[11px] leading-relaxed text-slate-300 bg-slate-950 border border-slate-800 px-2.5 py-2 whitespace-pre-wrap">
            {tafLines(obs.raw_taf).map((line, i) => (
              <div key={i} className={i ? 'pl-4' : ''}>
                {line}
              </div>
            ))}
          </pre>
        </div>
      )}
    </div>
  );
};
