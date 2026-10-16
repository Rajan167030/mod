import React, { useState } from 'react';
import { ScheduleComparison, TaskChange } from '../../types/api';
import { Badge, EmptyState, Panel, StatStrip, fmtZulu } from '../../components/ui';

interface ComparisonViewProps {
  comparison: ScheduleComparison;
}

const changeTone: Record<TaskChange['change_type'], 'default' | 'ok' | 'warn' | 'crit' | 'info'> = {
  UNCHANGED: 'default',
  REASSIGNED: 'info',
  TIME_SHIFTED: 'warn',
  NEWLY_ASSIGNED: 'ok',
  DROPPED: 'crit',
};

export const ComparisonView: React.FC<ComparisonViewProps> = ({ comparison: c }) => {
  const [showUnchanged, setShowUnchanged] = useState(false);
  const rows = c.changes.filter((ch) => showUnchanged || ch.change_type !== 'UNCHANGED');
  const unchanged = c.changes.length - c.changes.filter((ch) => ch.change_type !== 'UNCHANGED').length;
  const delay = c.delay_change_minutes;

  return (
    <div className="space-y-4">
      <StatStrip
        items={[
          {
            label: 'Assigned',
            value: `${c.proposed_assigned}/${c.total_tasks}`,
            hint: `was ${c.baseline_assigned}`,
            tone: c.proposed_assigned >= c.baseline_assigned ? 'ok' : 'warn',
          },
          { label: 'Reassigned', value: c.tasks_reassigned, hint: 'different resource' },
          { label: 'Retimed', value: c.tasks_time_shifted, hint: 'same resource, new slot' },
          {
            label: 'Total delay',
            value: `${delay > 0 ? '+' : ''}${delay}m`,
            hint: `${c.total_delay_minutes_baseline}m → ${c.total_delay_minutes_proposed}m`,
            tone: delay > 0 ? 'warn' : 'ok',
          },
          { label: 'Unchanged', value: unchanged },
          { label: 'Versions', value: `v${c.baseline_version_number}→v${c.proposed_version_number}` },
        ]}
      />

      <Panel
        title={`Task changes · v${c.baseline_version_number} → v${c.proposed_version_number}`}
        right={
          <label className="flex items-center gap-1.5 cursor-pointer print:hidden">
            <input
              type="checkbox"
              checked={showUnchanged}
              onChange={(e) => setShowUnchanged(e.target.checked)}
              className="accent-indigo-500"
            />
            Show unchanged
          </label>
        }
      >
        {rows.length === 0 ? (
          <EmptyState compact title="No task changes" description="The proposal keeps every assignment as it was." />
        ) : (
          <div className="overflow-x-auto">
            <table className="data-table w-full text-xs">
              <thead>
                <tr>
                  <th>Task</th>
                  <th>Change</th>
                  <th>Before</th>
                  <th>After</th>
                  <th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((ch) => (
                  <tr key={ch.task_id} className="align-top">
                    <td className="text-slate-100">{ch.task_name}</td>
                    <td>
                      <Badge status={ch.change_type} tone={changeTone[ch.change_type]} />
                    </td>
                    <td className="font-mono whitespace-nowrap">
                      {ch.baseline_resource ? (
                        <>
                          <div className="text-slate-300">{ch.baseline_resource}</div>
                          <div className="text-[10px] text-slate-500">{fmtZulu(ch.baseline_start)}</div>
                        </>
                      ) : (
                        <span className="text-slate-600">unscheduled</span>
                      )}
                    </td>
                    <td className="font-mono whitespace-nowrap">
                      {ch.proposed_resource ? (
                        <>
                          <div className="text-slate-100">{ch.proposed_resource}</div>
                          <div className="text-[10px] text-slate-400">{fmtZulu(ch.proposed_start)}</div>
                        </>
                      ) : (
                        <span className="text-crit">unassigned</span>
                      )}
                    </td>
                    <td className="text-slate-400 max-w-md">{ch.details || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
};
