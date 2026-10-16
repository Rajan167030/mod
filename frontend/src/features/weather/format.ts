import { AlertSeverity, FlightCategory, Location, WeatherAlertItem } from '../../types/api';

export const KMH_PER_KT = 1.852;

export const toKt = (kmh?: number | null): number | null =>
  kmh == null ? null : Math.round(kmh / KMH_PER_KT);

const pad = (n: number, width = 2) => String(Math.round(n)).padStart(width, '0');

/** "1430Z" */
export const zuluTime = (iso?: string | null): string => {
  if (!iso) return '----Z';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '----Z';
  return `${pad(d.getUTCHours())}${pad(d.getUTCMinutes())}Z`;
};

/** "16/1430Z" — day of month + Zulu time, as on a TAF */
export const zuluDayTime = (iso?: string | null): string => {
  if (!iso) return '--/----Z';
  const d = new Date(iso);
  return `${pad(d.getUTCDate())}/${zuluTime(iso)}`;
};

export const minutesAgo = (iso?: string | null): string => {
  if (!iso) return '—';
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins} min ago`;
  return `${Math.floor(mins / 60)} h ${mins % 60} min ago`;
};

/** METAR-style wind group: "320/12G24KT", "VRB/03KT", "CALM" */
export const windGroup = (
  dirDeg: number | null | undefined,
  speedKt: number | null | undefined,
  gustKt?: number | null,
): string => {
  if (speedKt == null) return '—';
  if (speedKt < 1) return 'CALM';
  const dir = dirDeg == null ? 'VRB' : pad(Math.round(dirDeg / 10) * 10 || 360, 3);
  const gust = gustKt != null && gustKt - speedKt >= 10 ? `G${pad(gustKt)}` : '';
  return `${dir}/${pad(speedKt)}${gust}KT`;
};

export const visibilityKm = (m?: number | null): string => {
  if (m == null) return '—';
  if (m >= 10000) return '10+';
  return (m / 1000).toFixed(m < 5000 ? 1 : 0);
};

export const fmt = (v: number | null | undefined, digits = 0, unit = ''): string =>
  v == null ? '—' : `${v.toFixed(digits)}${unit}`;

/** Strip demo suffixes such as "(FICTIONAL)" for compact display. */
export const displayName = (loc: Pick<Location, 'name'>): string =>
  loc.name.replace(/\s*\((FICTIONAL|SYNTHETIC)\)\s*$/i, '');

export const locationTypeLabel: Record<string, string> = {
  BASE: 'Base',
  LOGISTICS_HUB: 'Logistics hub',
  WEATHER_STATION: 'Wx station',
  WAYPOINT: 'Waypoint',
  POI: 'Point of interest',
};

export const severityRank: Record<AlertSeverity, number> = { CRITICAL: 3, WARNING: 2, INFO: 1 };

export const highestSeverity = (alerts: WeatherAlertItem[]): AlertSeverity | null =>
  alerts.reduce<AlertSeverity | null>(
    (best, a) => (best == null || severityRank[a.severity] > severityRank[best] ? a.severity : best),
    null,
  );

export const severityText: Record<AlertSeverity, string> = {
  CRITICAL: 'text-crit',
  WARNING: 'text-warn',
  INFO: 'text-slate-400',
};

export const severityDot: Record<AlertSeverity, string> = {
  CRITICAL: 'bg-crit',
  WARNING: 'bg-warn',
  INFO: 'bg-slate-500',
};

export const fltCatClass: Record<FlightCategory, string> = {
  VFR: 'bg-fltcat-vfr/15 text-fltcat-vfr border-fltcat-vfr/40',
  MVFR: 'bg-fltcat-mvfr/15 text-fltcat-mvfr border-fltcat-mvfr/40',
  IFR: 'bg-fltcat-ifr/15 text-fltcat-ifr border-fltcat-ifr/40',
  LIFR: 'bg-fltcat-lifr/15 text-fltcat-lifr border-fltcat-lifr/40',
};

/** Wind thresholds (km/h) come from the alert rules the backend applied; fall back to its defaults. */
export const windThresholdsKmh = (alerts: WeatherAlertItem[]) => {
  const wind = alerts.filter((a) => a.variable === 'wind_speed');
  const warn = wind.find((a) => a.severity === 'WARNING')?.threshold ?? 45;
  const crit = wind.find((a) => a.severity === 'CRITICAL')?.threshold ?? 65;
  return { warn, crit };
};
