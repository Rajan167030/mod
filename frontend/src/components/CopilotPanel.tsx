import React, { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Send, X } from 'lucide-react';
import { api } from '../api/client';
import { CopilotStep, Scenario } from '../types/api';
import { Skeleton } from './ui';

interface CopilotPanelProps {
  open: boolean;
  onClose: () => void;
}

type Turn =
  | { role: 'user'; text: string }
  | { role: 'assistant'; text: string; steps: CopilotStep[] }
  | { role: 'error'; text: string };

const SUGGESTIONS = [
  'What is the situation right now?',
  'Which sites have weather limits in the next 12 hours?',
  'Why can WL-07 only fly on one aircraft?',
  'What happens if C-130-Bravo is unavailable for 6 hours?',
];

/** Minimal formatting for replies: paragraphs, bullet lines and **bold**. */
const Reply: React.FC<{ text: string }> = ({ text }) => (
  <div className="space-y-2">
    {text.split(/\n{2,}/).map((para, i) => {
      const lines = para.split('\n');
      const bullets = lines.every((l) => /^\s*[-•*]\s+/.test(l));
      const fmt = (s: string) =>
        s.split(/(\*\*[^*]+\*\*)/g).map((part, j) =>
          part.startsWith('**') && part.endsWith('**') ? (
            <strong key={j} className="text-slate-100 font-medium">
              {part.slice(2, -2)}
            </strong>
          ) : (
            <React.Fragment key={j}>{part}</React.Fragment>
          ),
        );
      return bullets ? (
        <ul key={i} className="list-disc pl-4 space-y-0.5">
          {lines.map((l, j) => (
            <li key={j}>{fmt(l.replace(/^\s*[-•*]\s+/, ''))}</li>
          ))}
        </ul>
      ) : (
        <p key={i} className="whitespace-pre-line">
          {fmt(para)}
        </p>
      );
    })}
  </div>
);

export const CopilotPanel: React.FC<CopilotPanelProps> = ({ open, onClose }) => {
  const [status, setStatus] = useState<{ configured: boolean; model: string } | null>(null);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenarioId, setScenarioId] = useState('');
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    api.copilotStatus().then(setStatus).catch(() => setStatus({ configured: false, model: '' }));
    api
      .getScenarios()
      .then((s) => {
        setScenarios(s);
        setScenarioId((cur) => cur || s[0]?.id || '');
      })
      .catch(() => undefined);
  }, [open]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth' });
  }, [turns, busy]);

  const changeScenario = (id: string) => {
    setScenarioId(id);
    setConversationId(null);
    setTurns([]);
  };

  const send = async (text: string) => {
    const message = text.trim();
    if (!message || busy || !scenarioId) return;
    setDraft('');
    setTurns((t) => [...t, { role: 'user', text: message }]);
    setBusy(true);
    try {
      const r = await api.copilotChat(scenarioId, message, conversationId);
      setConversationId(r.conversation_id);
      setTurns((t) => [...t, { role: 'assistant', text: r.reply, steps: r.steps }]);
    } catch (e: any) {
      setTurns((t) => [...t, { role: 'error', text: e?.message || 'The copilot could not answer.' }]);
    } finally {
      setBusy(false);
    }
  };

  if (!open) return null;

  return (
    <aside
      className="fixed right-0 top-0 bottom-0 z-50 w-full max-w-[440px] bg-slate-925 border-l border-slate-800 shadow-2xl flex flex-col print:hidden"
      aria-label="Planning copilot"
    >
      <div className="h-12 shrink-0 flex items-center justify-between px-4 border-b border-slate-800">
        <div>
          <div className="text-sm font-medium text-slate-100">Copilot</div>
          <div className="text-[10px] text-slate-500">Answers and simulates. It cannot change a plan.</div>
        </div>
        <button onClick={onClose} className="btn-ghost h-7 px-2" aria-label="Close copilot">
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="px-4 py-2 border-b border-slate-800 flex items-center gap-2 text-xs">
        <span className="text-slate-500 shrink-0">Scenario</span>
        <select className="field h-7 flex-1 min-w-0" value={scenarioId} onChange={(e) => changeScenario(e.target.value)}>
          {scenarios.map((s) => (
            <option key={s.id} value={s.id}>
              {s.name}
            </option>
          ))}
        </select>
        {turns.length > 0 && (
          <button onClick={() => changeScenario(scenarioId)} className="btn-ghost h-7 px-2">
            New
          </button>
        )}
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4 text-xs">
        {status && !status.configured && (
          <div className="border border-warn/40 bg-warn/10 text-warn px-3 py-2 space-y-1">
            <div className="font-medium">Copilot is not set up on this server.</div>
            <div className="text-slate-300">
              Add <code className="font-mono">ANTHROPIC_API_KEY=…</code> to <code className="font-mono">backend/.env</code> and restart the
              backend. Everything else in the app works without it.
            </div>
          </div>
        )}

        {turns.length === 0 && status?.configured !== false && (
          <div className="space-y-2">
            <div className="text-slate-400">Ask about the plan, the fleet or the weather. Try:</div>
            {SUGGESTIONS.map((s) => (
              <button
                key={s}
                onClick={() => send(s)}
                disabled={busy || !scenarioId}
                className="block w-full text-left px-3 py-2 border border-slate-800 text-slate-300 hover:border-slate-700 hover:bg-slate-900"
              >
                {s}
              </button>
            ))}
          </div>
        )}

        {turns.map((t, i) =>
          t.role === 'user' ? (
            <div key={i} className="ml-8 bg-slate-800 text-slate-100 px-3 py-2">
              {t.text}
            </div>
          ) : t.role === 'error' ? (
            <div key={i} className="border border-crit/40 bg-crit/5 text-crit px-3 py-2">
              {t.text}
            </div>
          ) : (
            <div key={i} className="space-y-1.5">
              {t.steps.length > 0 && (
                <div className="font-mono text-[10px] text-slate-500 space-y-0.5">
                  {t.steps.map((s, j) => (
                    <div key={j} className={s.error ? 'text-warn' : ''}>
                      ↳ {s.label}
                      {s.tool === 'explain_task' && ` · ${String(s.input.task ?? '')}`}
                      {s.tool === 'what_if_unavailable' && ` · ${String(s.input.aircraft ?? '')} ${String(s.input.hours ?? '')}h`}
                    </div>
                  ))}
                </div>
              )}
              <div className="text-slate-300 leading-relaxed">
                <Reply text={t.text} />
              </div>
            </div>
          ),
        )}

        {busy && (
          <div className="space-y-1.5" role="status" aria-label="Thinking">
            <div className="font-mono text-[10px] text-slate-500">Looking into it…</div>
            <Skeleton className="h-3 w-5/6" />
            <Skeleton className="h-3 w-2/3" />
          </div>
        )}
        <div ref={bottom} />
      </div>

      <form
        className="shrink-0 border-t border-slate-800 p-3 space-y-1.5"
        onSubmit={(e) => {
          e.preventDefault();
          send(draft);
        }}
      >
        <div className="flex gap-2">
          <input
            className="field h-9 flex-1"
            placeholder={status?.configured === false ? 'Copilot not configured' : 'Ask a question'}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            disabled={busy || status?.configured === false}
            maxLength={2000}
            aria-label="Message"
          />
          <button type="submit" disabled={busy || !draft.trim() || status?.configured === false} className="btn-primary h-9 px-3" aria-label="Send">
            <Send className="w-3.5 h-3.5" />
          </button>
        </div>
        <div className="text-[10px] text-slate-600">
          {status?.model ? `${status.model} · ` : ''}AI answers can be wrong; check figures on the{' '}
          <Link to="/schedule" className="underline">
            timeline
          </Link>{' '}
          before acting.
        </div>
      </form>
    </aside>
  );
};
