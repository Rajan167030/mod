import React from 'react';
import { ConflictItem } from '../../types/api';
import { EmptyState, fmtZulu } from '../../components/ui';

interface ConflictPanelProps {
  conflicts: ConflictItem[];
  isValid: boolean;
}

export const ConflictPanel: React.FC<ConflictPanelProps> = ({ conflicts, isValid }) => {
  if (isValid && conflicts.length === 0) {
    return (
      <EmptyState
        compact
        title="No conflicts"
        description="The independent validator found no overlap, availability, time-window or qualification breaches."
      />
    );
  }

  return (
    <div className="overflow-auto max-h-[420px]">
      <table className="data-table w-full text-xs">
        <thead className="sticky top-0 bg-slate-925">
          <tr>
            <th>Rule</th>
            <th>Resource</th>
            <th>Window</th>
            <th>Tasks</th>
            <th>Explanation</th>
          </tr>
        </thead>
        <tbody>
          {conflicts.map((c, i) => (
            <tr key={i} className="align-top">
              <td className={`font-mono whitespace-nowrap ${c.severity === 'CRITICAL' ? 'text-crit' : 'text-warn'}`}>{c.code}</td>
              <td className="font-mono text-slate-300 whitespace-nowrap">{c.resource_name ?? '—'}</td>
              <td className="font-mono text-slate-500 whitespace-nowrap">
                {c.conflict_start ? `${fmtZulu(c.conflict_start)} – ${fmtZulu(c.conflict_end)}` : '—'}
              </td>
              <td className="text-slate-300">{c.task_names.join(', ') || '—'}</td>
              <td className="text-slate-400 max-w-lg">{c.explanation}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};
