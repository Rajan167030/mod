import React from 'react';
import { AlertTriangle, Inbox, RotateCw } from 'lucide-react';

/* ------------------------------------------------------------------ */
/* Layout                                                              */
/* ------------------------------------------------------------------ */

export const PageHeader: React.FC<{
  title: string;
  subtitle?: React.ReactNode;
  actions?: React.ReactNode;
}> = ({ title, subtitle, actions }) => (
  <div className="flex flex-wrap items-end justify-between gap-3">
    <div className="min-w-0">
      <h1 className="text-lg font-semibold text-slate-100">{title}</h1>
      {subtitle && <p className="text-xs text-slate-500 mt-0.5">{subtitle}</p>}
    </div>
    {actions && <div className="flex flex-wrap items-center gap-2 print:hidden">{actions}</div>}
  </div>
);

export const Panel: React.FC<{
  title?: React.ReactNode;
  right?: React.ReactNode;
  className?: string;
  bodyClassName?: string;
  children: React.ReactNode;
}> = ({ title, right, className = '', bodyClassName = '', children }) => (
  <section className={`panel flex flex-col min-h-0 ${className}`}>
    {title != null && (
      <div className="panel-head shrink-0">
        <span className="truncate">{title}</span>
        {right && <span className="normal-case tracking-normal font-normal text-slate-500">{right}</span>}
      </div>
    )}
    <div className={`flex-1 min-h-0 ${bodyClassName}`}>{children}</div>
  </section>
);

type Tone = 'default' | 'ok' | 'warn' | 'crit' | 'info';

const toneText: Record<Tone, string> = {
  default: 'text-slate-100',
  ok: 'text-ok',
  warn: 'text-warn',
  crit: 'text-crit',
  info: 'text-info',
};

/** A row of key figures separated by rules, rather than a grid of icon cards. */
export const StatStrip: React.FC<{
  items: { label: string; value: React.ReactNode; hint?: React.ReactNode; tone?: Tone }[];
  loading?: boolean;
}> = ({ items, loading }) => (
  <div className="panel grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 divide-x divide-slate-800">
    {items.map((it) => (
      <div key={it.label} className="px-4 py-3 min-w-0 border-b border-slate-800 md:border-b-0">
        <div className="text-[11px] text-slate-500 truncate">{it.label}</div>
        {loading ? (
          <Skeleton className="h-6 w-16 mt-1" />
        ) : (
          <div className={`mt-0.5 font-mono text-xl leading-7 ${toneText[it.tone ?? 'default']}`}>{it.value}</div>
        )}
        {it.hint && !loading && <div className="text-[11px] text-slate-500 truncate">{it.hint}</div>}
      </div>
    ))}
  </div>
);

/* ------------------------------------------------------------------ */
/* Status                                                              */
/* ------------------------------------------------------------------ */

const statusTone: Record<string, Tone> = {
  CRITICAL: 'crit',
  GROUNDED: 'crit',
  INFEASIBLE: 'crit',
  REJECTED: 'crit',
  FAILED: 'crit',
  UNAVAILABLE: 'crit',
  HIGH: 'warn',
  WARNING: 'warn',
  MAINTENANCE: 'warn',
  STALE: 'warn',
  OPTIMAL: 'ok',
  APPROVED: 'ok',
  COMPLETED: 'ok',
  AVAILABLE: 'ok',
  FRESH: 'ok',
  ACTIVE: 'ok',
  FEASIBLE: 'info',
  PROPOSED: 'info',
  SCHEDULED: 'info',
  RUNNING: 'info',
  MEDIUM: 'info',
};

const badgeTone: Record<Tone, string> = {
  default: 'text-slate-400 border-slate-700',
  ok: 'text-ok border-ok/40 bg-ok/10',
  warn: 'text-warn border-warn/40 bg-warn/10',
  crit: 'text-crit border-crit/40 bg-crit/10',
  info: 'text-info border-info/40 bg-info/10',
};

export const Badge: React.FC<{ status: string; tone?: Tone; className?: string }> = ({ status, tone, className = '' }) => {
  const t = tone ?? statusTone[status.toUpperCase()] ?? 'default';
  return (
    <span
      className={`inline-flex items-center px-1.5 h-[18px] border rounded-sm font-mono text-[10px] uppercase tracking-wide whitespace-nowrap ${badgeTone[t]} ${className}`}
    >
      {status.replace(/_/g, ' ')}
    </span>
  );
};

/* ------------------------------------------------------------------ */
/* Loading / empty / error                                             */
/* ------------------------------------------------------------------ */

export const Skeleton: React.FC<{ className?: string }> = ({ className = '' }) => (
  <span aria-hidden className={`block rounded-sm bg-slate-800 animate-shimmer ${className}`} />
);

/** Placeholder rows shaped like the table that will replace them. */
export const SkeletonTable: React.FC<{ rows?: number; cols?: number }> = ({ rows = 6, cols = 5 }) => (
  <div role="status" aria-label="Loading" className="divide-y divide-slate-800/70">
    {Array.from({ length: rows }, (_, r) => (
      <div key={r} className="flex items-center gap-4 px-3 py-2.5">
        {Array.from({ length: cols }, (_, c) => (
          <Skeleton key={c} className={`h-3 ${c === 0 ? 'w-40' : 'flex-1'}`} />
        ))}
      </div>
    ))}
  </div>
);

export const SkeletonPage: React.FC<{ panels?: number }> = ({ panels = 2 }) => (
  <div role="status" aria-label="Loading" className="space-y-4">
    <div className="space-y-2">
      <Skeleton className="h-5 w-48" />
      <Skeleton className="h-3 w-80" />
    </div>
    <div className="panel grid grid-cols-2 md:grid-cols-4 divide-x divide-slate-800">
      {Array.from({ length: 4 }, (_, i) => (
        <div key={i} className="px-4 py-3 space-y-2">
          <Skeleton className="h-3 w-20" />
          <Skeleton className="h-6 w-14" />
        </div>
      ))}
    </div>
    {Array.from({ length: panels }, (_, i) => (
      <div key={i} className="panel">
        <div className="panel-head">
          <Skeleton className="h-3 w-24" />
        </div>
        <SkeletonTable rows={4} />
      </div>
    ))}
  </div>
);

export const EmptyState: React.FC<{
  title: string;
  description?: React.ReactNode;
  action?: React.ReactNode;
  icon?: React.ReactNode;
  compact?: boolean;
}> = ({ title, description, action, icon, compact }) => (
  <div className={`flex flex-col items-center justify-center text-center ${compact ? 'px-4 py-6' : 'px-6 py-12'}`}>
    <div className="text-slate-600 mb-2">{icon ?? <Inbox className="w-5 h-5" />}</div>
    <div className="text-sm text-slate-300">{title}</div>
    {description && <div className="text-xs text-slate-500 mt-1 max-w-sm">{description}</div>}
    {action && <div className="mt-3">{action}</div>}
  </div>
);

export const ErrorState: React.FC<{ message: string; onRetry?: () => void }> = ({ message, onRetry }) => (
  <div className="flex items-start gap-3 border border-crit/40 bg-crit/5 px-3 py-2.5 text-xs">
    <AlertTriangle className="w-4 h-4 text-crit shrink-0 mt-px" />
    <div className="flex-1 text-slate-300">{message}</div>
    {onRetry && (
      <button onClick={onRetry} className="btn-ghost h-6 px-2">
        <RotateCw className="w-3 h-3" /> Retry
      </button>
    )}
  </div>
);

export const Notice: React.FC<{ tone?: Tone; children: React.ReactNode; onDismiss?: () => void }> = ({
  tone = 'info',
  children,
  onDismiss,
}) => (
  <div className={`flex items-start gap-3 border px-3 py-2 text-xs ${badgeTone[tone]}`}>
    <div className="flex-1">{children}</div>
    {onDismiss && (
      <button onClick={onDismiss} className="opacity-70 hover:opacity-100" aria-label="Dismiss">
        ×
      </button>
    )}
  </div>
);

/* ------------------------------------------------------------------ */
/* Formatting                                                          */
/* ------------------------------------------------------------------ */

const pad = (n: number) => String(n).padStart(2, '0');

/** "16 Oct 1430Z" */
export const fmtZulu = (iso?: string | null): string => {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  const mon = d.toLocaleString('en-GB', { month: 'short', timeZone: 'UTC' });
  return `${pad(d.getUTCDate())} ${mon} ${pad(d.getUTCHours())}${pad(d.getUTCMinutes())}Z`;
};

/** "1430Z" */
export const fmtZuluTime = (iso?: string | null): string => {
  if (!iso) return '—';
  const d = new Date(iso);
  return `${pad(d.getUTCHours())}${pad(d.getUTCMinutes())}Z`;
};

export const fmtDuration = (startIso: string, endIso: string): string => {
  const mins = Math.round((new Date(endIso).getTime() - new Date(startIso).getTime()) / 60000);
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return h ? `${h}h${m ? ` ${pad(m)}m` : ''}` : `${m}m`;
};

export const shortId = (id?: string | null) => (id ? id.slice(0, 8) : '—');

export const humanize = (s?: string | null) =>
  s ? s.toLowerCase().replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase()) : '—';
