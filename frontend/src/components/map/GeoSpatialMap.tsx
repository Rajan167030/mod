import React, { useEffect, useMemo, useRef } from 'react';
import { Location, MetarObservation, WeatherAlertItem, WeatherDataPoint } from '../../types/api';
import { displayName, highestSeverity, toKt, windGroup } from '../../features/weather/format';
import { useActiveTheme } from '../useTheme';

interface GeoSpatialMapProps {
  locations: Location[];
  alerts?: WeatherAlertItem[];
  weatherByLocation?: Record<string, WeatherDataPoint>;
  metarStations?: MetarObservation[];
  selectedLocationId?: string | null;
  onSelectLocation?: (location: Location) => void;
}

// CSS colours resolve against the theme tokens, so markers follow light/dark mode
const SEVERITY_COLOR = { CRITICAL: 'rgb(var(--st-crit))', WARNING: 'rgb(var(--st-warn))', INFO: 'rgb(var(--slate-400))' } as const;
const NOMINAL_COLOR = 'rgb(var(--accent-400))';
const BG = 'rgb(var(--slate-950))';
const ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services';
const BASEMAPS = {
  dark: ['Canvas/World_Dark_Gray_Base', 'Elevation/World_Hillshade_Dark', 'Canvas/World_Dark_Gray_Reference'],
  light: ['Canvas/World_Light_Gray_Base', 'Elevation/World_Hillshade', 'Canvas/World_Light_Gray_Reference'],
} as const;
const FLTCAT_COLOR: Record<string, string> = {
  VFR: '#3fb950',
  MVFR: '#4c8eda',
  IFR: '#e5534b',
  LIFR: '#c95fc9',
};

const escapeHtml = (s: string) =>
  s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!);

export const GeoSpatialMap: React.FC<GeoSpatialMapProps> = ({
  locations,
  alerts = [],
  weatherByLocation = {},
  metarStations = [],
  selectedLocationId,
  onSelectLocation,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<any>(null);
  const layerRef = useRef<any>(null);
  const fittedRef = useRef(false);
  const tilesRef = useRef<any>(null);
  const theme = useActiveTheme();

  const alertsByLocation = useMemo(() => {
    const map: Record<string, WeatherAlertItem[]> = {};
    for (const a of alerts) (map[a.location_id] ||= []).push(a);
    return map;
  }, [alerts]);

  useEffect(() => {
    const L = (window as any).L;
    if (!L || !containerRef.current || mapRef.current) return;

    const map = L.map(containerRef.current, { center: [34, 76.5], zoom: 7, zoomControl: false });
    L.control.zoom({ position: 'bottomright' }).addTo(map);
    L.control.scale({ position: 'bottomleft', imperial: false }).addTo(map);

    layerRef.current = L.layerGroup().addTo(map);
    mapRef.current = map;

    return () => {
      map.remove();
      tilesRef.current = null;
      mapRef.current = null;
      fittedRef.current = false;
    };
  }, []);

  // Esri basemaps need no API key (CARTO now does). Hillshade gives terrain relief for the mountain sites.
  useEffect(() => {
    const L = (window as any).L;
    const map = mapRef.current;
    if (!L || !map) return;
    tilesRef.current?.remove();
    const [base, relief, labels] = BASEMAPS[theme];
    const tile = (path: string, opts: object = {}) =>
      L.tileLayer(`${ESRI}/${path}/MapServer/tile/{z}/{y}/{x}`, { maxZoom: 16, ...opts });
    tilesRef.current = L.layerGroup([
      tile(base, { attribution: 'Tiles &copy; Esri' }),
      tile(relief, { opacity: theme === 'dark' ? 0.55 : 0.35 }),
      tile(labels),
    ]).addTo(map);
  }, [theme]);

  // Fit to the scenario's locations once they arrive
  useEffect(() => {
    const L = (window as any).L;
    if (!L || !mapRef.current || locations.length === 0 || fittedRef.current) return;
    const bounds = L.latLngBounds(locations.map((l) => [l.latitude, l.longitude]));
    mapRef.current.fitBounds(bounds, { padding: [60, 60], maxZoom: 9 });
    fittedRef.current = true;
  }, [locations]);

  useEffect(() => {
    const L = (window as any).L;
    const group = layerRef.current;
    if (!L || !group) return;
    group.clearLayers();

    // METAR reporting airports (reference only, not selectable)
    const seen = new Set<string>();
    for (const st of metarStations) {
      if (seen.has(st.station_id)) continue;
      seen.add(st.station_id);
      const color = FLTCAT_COLOR[st.flight_category ?? ''] ?? 'rgb(var(--slate-400))';
      const icon = L.divIcon({
        className: '',
        iconSize: [0, 0],
        html: `<div style="position:absolute;transform:translate(-50%,-50%);display:flex;align-items:center;gap:4px;white-space:nowrap">
          <span style="width:9px;height:9px;border-radius:50%;border:2px solid ${color};background:${BG}"></span>
          <span style="font:500 10px 'IBM Plex Mono',monospace;color:${color}">${escapeHtml(st.station_id)}</span>
        </div>`,
      });
      L.marker([st.latitude, st.longitude], { icon, interactive: true })
        .bindTooltip(
          `<div style="font:11px 'IBM Plex Mono',monospace;max-width:320px;white-space:normal">${escapeHtml(st.raw_metar)}</div>`,
          { direction: 'top', offset: [0, -6] },
        )
        .addTo(group);
    }

    for (const loc of locations) {
      const sev = highestSeverity(alertsByLocation[loc.id] || []);
      const color = sev && sev !== 'INFO' ? SEVERITY_COLOR[sev] : NOMINAL_COLOR;
      const selected = loc.id === selectedLocationId;
      const wx = weatherByLocation[loc.id];
      const wind = wx
        ? windGroup(wx.wind_direction_deg, toKt(wx.wind_speed_kmh), toKt(wx.wind_gust_kmh))
        : '';
      const temp = wx?.temperature_celsius != null ? `${Math.round(wx.temperature_celsius)}°` : '';

      if (sev === 'CRITICAL' || sev === 'WARNING') {
        L.circle([loc.latitude, loc.longitude], {
          radius: sev === 'CRITICAL' ? 20000 : 12000,
          color,
          weight: 1,
          opacity: 0.6,
          fillOpacity: 0.06,
          interactive: false,
        }).addTo(group);
      }

      const icon = L.divIcon({
        className: '',
        iconSize: [0, 0],
        html: `<div style="position:absolute;transform:translate(-6px,-6px);display:flex;align-items:flex-start;gap:6px;white-space:nowrap;cursor:pointer">
          <span style="flex:none;width:12px;height:12px;background:${color};border:2px solid ${selected ? 'rgb(var(--slate-50))' : BG};outline:${selected ? `2px solid ${color}` : 'none'}"></span>
          <span style="margin-top:-3px;padding:1px 5px;background:rgb(var(--slate-950) / 0.88);border:1px solid ${selected ? 'rgb(var(--slate-400))' : 'rgb(var(--slate-800))'};font:11px 'IBM Plex Sans',sans-serif;color:rgb(var(--slate-100));line-height:1.35">
            ${escapeHtml(displayName(loc))}
            <br/><span style="font:10px 'IBM Plex Mono',monospace;color:rgb(var(--slate-400))">${temp} ${wind}</span>
          </span>
        </div>`,
      });

      L.marker([loc.latitude, loc.longitude], { icon, zIndexOffset: selected ? 1000 : 0 })
        .on('click', () => onSelectLocation?.(loc))
        .addTo(group);
    }
  }, [locations, alertsByLocation, weatherByLocation, metarStations, selectedLocationId, onSelectLocation]);

  useEffect(() => {
    const target = locations.find((l) => l.id === selectedLocationId);
    if (mapRef.current && target) {
      mapRef.current.panTo([target.latitude, target.longitude], { animate: true });
    }
  }, [selectedLocationId, locations]);

  return (
    <div className="relative h-full w-full">
      <div ref={containerRef} className="absolute inset-0" />
      <div className="absolute top-2 left-2 z-[1000] flex items-center gap-3 px-2 py-1 bg-slate-950/85 border border-slate-800 text-[10px] text-slate-400">
        <span className="flex items-center gap-1">
          <span className="w-2 h-2" style={{ background: NOMINAL_COLOR }} /> Nominal
        </span>
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 bg-warn" /> Warning
        </span>
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 bg-crit" /> Critical
        </span>
        <span className="flex items-center gap-1 pl-2 border-l border-slate-800">
          <span className="w-2 h-2 rounded-full border-2 border-fltcat-vfr" /> METAR airport
        </span>
      </div>
    </div>
  );
};
