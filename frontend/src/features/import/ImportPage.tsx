import React, { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Upload } from 'lucide-react';
import { api } from '../../api/client';
import { ImportKind, ImportPreview, Scenario } from '../../types/api';
import { EmptyState, ErrorState, Notice, PageHeader, Panel, SkeletonTable } from '../../components/ui';

const KINDS: { key: ImportKind; label: string; help: string }[] = [
  { key: 'aircraft', label: 'Aircraft', help: 'Name, type, qualifications (add DASS for self-protection), payload, status, stores it can carry. Existing names are updated.' },
  { key: 'tasks', label: 'Tasks', help: 'Name, priority, duration, window, qualification, site, stores needed (e.g. ROCKET_POD:2;FLARE_SET). Existing names are updated.' },
  { key: 'maintenance', label: 'Maintenance', help: 'Aircraft, start, end. Each row blocks that aircraft for the period.' },
  { key: 'sites', label: 'Sites', help: 'Name, latitude, longitude, type, elevation. Live weather starts for new sites.' },
  { key: 'crews', label: 'Crews', help: 'Name, aircraft types flown, status, duty limit, minimum rest, duty already flown, shift. Existing names are updated.' },
  { key: 'stores', label: 'Stores', help: 'Store type, name, category (weapon, countermeasure, mission kit), quantity held, unit. Existing types are updated.' },
  { key: 'threats', label: 'Threats & airspace', help: 'Name, kind (SAM, AAA, MANPADS, RADAR, RESTRICTED, NO_FLY), rule, centre, radius, active window, exemption, source, confidence.' },
];

const fmtValue = (v: unknown): string => {
  if (v == null || v === '') return '—';
  if (Array.isArray(v)) return v.join(', ');
  if (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(v)) {
    const d = new Date(v);
    return `${String(d.getUTCDate()).padStart(2, '0')} ${d.toLocaleString('en-GB', { month: 'short', timeZone: 'UTC' })} ${String(d.getUTCHours()).padStart(2, '0')}${String(d.getUTCMinutes()).padStart(2, '0')}Z`;
  }
  return String(v);
};

export const ImportPage: React.FC = () => {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenarioId, setScenarioId] = useState('');
  const [kind, setKind] = useState<ImportKind>('tasks');
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [busy, setBusy] = useState<'preview' | 'commit' | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [onlyErrors, setOnlyErrors] = useState(false);
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.getScenarios().then((s) => {
      setScenarios(s);
      if (s[0]) setScenarioId(s[0].id);
    }).catch((e) => setError(e?.message || 'Could not load scenarios.'));
  }, []);

  const reset = () => {
    setFile(null);
    setPreview(null);
    setError(null);
    if (input.current) input.current.value = '';
  };

  const choose = async (f: File | null) => {
    setDone(null);
    setError(null);
    setPreview(null);
    setFile(f);
    if (!f || !scenarioId) return;
    setBusy('preview');
    try {
      setPreview(await api.importFile(scenarioId, kind, 'preview', f));
    } catch (e: any) {
      setError(e?.message || 'Could not read the file.');
    } finally {
      setBusy(null);
    }
  };

  const commit = async () => {
    if (!file) return;
    setBusy('commit');
    setError(null);
    try {
      const r = await api.importFile(scenarioId, kind, 'commit', file);
      setDone(`${r.rows} rows imported: ${r.created} created, ${r.updated} updated.`);
      reset();
    } catch (e: any) {
      setError(e?.message || 'Import failed.');
    } finally {
      setBusy(null);
    }
  };

  const columns = preview ? Object.keys(preview.rows[0]?.values ?? {}) : [];
  const rows = preview ? preview.rows.filter((r) => !onlyErrors || r.errors.length) : [];
  const blocked = !preview || preview.summary.invalid > 0 || preview.missing_columns.length > 0 || preview.summary.total === 0;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Data import"
        subtitle="Bring in fleet, task, maintenance, site, crew, stores and threat data from other systems as CSV or Excel. Every row is checked before anything is saved."
        actions={
          <select className="field max-w-[280px]" value={scenarioId} onChange={(e) => { setScenarioId(e.target.value); reset(); }} aria-label="Scenario">
            {scenarios.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        }
      />

      {done && (
        <Notice tone="ok" onDismiss={() => setDone(null)}>
          {done} Check the <Link to="/explorer" className="underline">object explorer</Link> or run the{' '}
          <Link to="/courses-of-action" className="underline">courses of action</Link> to plan with the new data.
        </Notice>
      )}
      {error && <ErrorState message={error} />}

      <div className="grid grid-cols-1 xl:grid-cols-12 gap-4">
        <Panel title="1 · What are you importing?" className="xl:col-span-4">
          <div className="p-3 space-y-2 text-xs">
            {KINDS.map((k) => (
              <label key={k.key} className={`flex items-start gap-2.5 px-2.5 py-2 border cursor-pointer ${kind === k.key ? 'border-indigo-500 bg-indigo-950/40' : 'border-slate-800 hover:border-slate-700'}`}>
                <input type="radio" name="kind" checked={kind === k.key} onChange={() => { setKind(k.key); reset(); }} className="mt-0.5 accent-indigo-500" />
                <span>
                  <span className="block text-slate-200">{k.label}</span>
                  <span className="block text-slate-500">{k.help}</span>
                </span>
              </label>
            ))}
            <a href={api.getImportTemplateUrl(kind)} className="btn-secondary w-full">Download {kind} template (.csv)</a>
            <p className="text-slate-500">Column names are matched loosely: “Callsign”, “Deadline”, “Window opens” and similar headers are recognised. Times are UTC, e.g. 2026-10-17T06:00Z.</p>
          </div>
        </Panel>

        <Panel title="2 · Choose a file" className="xl:col-span-8">
          <div className="p-3">
            <div
              onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => { e.preventDefault(); setDragging(false); choose(e.dataTransfer.files[0] ?? null); }}
              className={`flex flex-col items-center justify-center gap-2 border border-dashed py-10 text-xs ${dragging ? 'border-indigo-400 bg-indigo-950/30' : 'border-slate-700'}`}
            >
              <Upload className="w-5 h-5 text-slate-500" />
              <div className="text-slate-300">{file ? file.name : 'Drop a .csv or .xlsx file here'}</div>
              <button onClick={() => input.current?.click()} className="btn-secondary h-7">Browse…</button>
              <input ref={input} type="file" accept=".csv,.xlsx" className="hidden" onChange={(e) => choose(e.target.files?.[0] ?? null)} />
            </div>
          </div>
        </Panel>
      </div>

      {busy === 'preview' && <Panel title="3 · Check"><SkeletonTable rows={6} cols={6} /></Panel>}

      {preview && (
        <Panel
          title="3 · Check before saving"
          right={
            <label className="flex items-center gap-1.5 cursor-pointer">
              <input type="checkbox" checked={onlyErrors} onChange={(e) => setOnlyErrors(e.target.checked)} className="accent-indigo-500" />
              Only rows with errors
            </label>
          }
        >
          <div className="p-3 space-y-3 text-xs border-b border-slate-800">
            <div className="flex flex-wrap gap-4 font-mono">
              <span className="text-slate-300">{preview.summary.total} rows</span>
              <span className="text-ok">{preview.summary.valid} valid</span>
              <span className={preview.summary.invalid ? 'text-crit' : 'text-slate-500'}>{preview.summary.invalid} with errors</span>
              <span className="text-slate-400">{preview.summary.create} new · {preview.summary.update} updates</span>
            </div>
            <div className="flex flex-wrap gap-1.5 items-center">
              <span className="text-slate-500">Columns:</span>
              {Object.entries(preview.columns).map(([field, header]) => (
                <span key={field} className="px-1.5 border border-slate-700 font-mono text-[10px] text-slate-300">
                  {header} → {field}
                </span>
              ))}
              {preview.unused_columns.map((h) => (
                <span key={h} className="px-1.5 border border-dashed border-slate-700 font-mono text-[10px] text-slate-500" title="Not recognised; ignored">{h} (ignored)</span>
              ))}
            </div>
            {preview.missing_columns.length > 0 && (
              <div className="text-crit">Missing required columns: {preview.missing_columns.join(', ')}. Download the template to see the expected headers.</div>
            )}
            {preview.warnings.map((w, i) => <div key={i} className="text-warn">{w}</div>)}
          </div>

          {rows.length === 0 ? (
            <EmptyState compact title={onlyErrors ? 'No rows with errors' : 'The file has no data rows'} />
          ) : (
            <div className="overflow-auto max-h-[460px]">
              <table className="data-table w-full text-xs">
                <thead className="sticky top-0 bg-slate-925">
                  <tr>
                    <th>Row</th>
                    <th>Action</th>
                    {columns.map((c) => <th key={c}>{c.replace(/_/g, ' ')}</th>)}
                    <th>Problems</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.row} className={r.errors.length ? 'bg-crit/5' : ''}>
                      <td className="font-mono text-slate-500">{r.row}</td>
                      <td className={`font-mono ${r.errors.length ? 'text-slate-600' : r.action === 'update' ? 'text-info' : 'text-ok'}`}>
                        {r.errors.length ? 'skip' : r.action}
                      </td>
                      {columns.map((c) => (
                        <td key={c} className="font-mono text-slate-300 whitespace-nowrap max-w-[220px] truncate">{fmtValue(r.values[c])}</td>
                      ))}
                      <td className="text-crit">{r.errors.join('; ')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div className="flex items-center justify-between gap-3 px-3 py-2 border-t border-slate-800 text-xs">
            <span className="text-slate-500">
              {blocked ? 'Fix the file and choose it again. Nothing is saved until every row passes.' : 'All rows pass. Saving is recorded in the audit log.'}
            </span>
            <div className="flex gap-2">
              <button onClick={reset} className="btn-secondary">Cancel</button>
              <button onClick={commit} disabled={blocked || busy === 'commit'} className="btn-primary">
                {busy === 'commit' ? 'Importing…' : `Import ${preview.summary.valid} rows`}
              </button>
            </div>
          </div>
        </Panel>
      )}
    </div>
  );
};
