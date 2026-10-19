import { OpsZone } from '../../types/api';

const esc = (s: string) => s.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!);

/** Threats that block are red, threats to avoid amber, airspace restrictions blue. */
export const zoneColor = (z: Pick<OpsZone, 'category' | 'effect'>) =>
  z.category === 'AIRSPACE' ? 'rgb(var(--st-info))' : z.effect === 'BLOCK' ? 'rgb(var(--st-crit))' : 'rgb(var(--st-warn))';

export const zoneRule = (z: OpsZone) =>
  z.effect === 'AVOID' ? 'Avoid where possible' : z.exempt_capability ? `No flying without ${z.exempt_capability}` : 'No flying';

export const isActiveAt = (z: OpsZone, t: number) =>
  (!z.active_from || new Date(z.active_from).getTime() <= t) && (!z.active_until || t < new Date(z.active_until).getTime());

/**
 * Draw zones into a Leaflet layer group. With `at`, zones active at that moment are solid
 * and the rest are faint dashed outlines; without it every zone is drawn solid.
 */
export function drawZones(L: any, group: any, zones: OpsZone[], at?: number, onClick?: (z: OpsZone) => void, renderer?: any) {
  for (const z of zones) {
    const active = at == null || isActiveAt(z, at);
    const color = zoneColor(z);
    const style = {
      color,
      weight: active ? 1.5 : 1,
      opacity: active ? 0.9 : 0.45,
      dashArray: active ? undefined : '4 5',
      fillColor: color,
      fillOpacity: active ? (z.effect === 'BLOCK' ? 0.16 : 0.1) : 0.02,
      ...(renderer ? { renderer } : {}),
    };
    const shape = z.polygon
      ? L.polygon(z.polygon, style)
      : z.center_lat != null && z.center_lon != null && z.radius_km
        ? L.circle([z.center_lat, z.center_lon], { ...style, radius: z.radius_km * 1000 })
        : null;
    if (!shape) continue;
    shape.bindTooltip(
      `<b>${esc(z.name)}</b><br>${esc(z.kind)} · ${esc(zoneRule(z))}${active ? '' : ' · not active now'}` +
        `<br>${esc(z.source ?? 'unknown source')} · ${Math.round(z.confidence * 100)}% confidence`,
      { sticky: true },
    );
    if (onClick) shape.on('click', () => onClick(z));
    shape.addTo(group);
  }
}
