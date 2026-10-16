import React, { useEffect, useState } from 'react';
import { LogOut, ChevronDown, Moon, Sun, Printer, MessageSquare } from 'lucide-react';
import { useTheme } from './useTheme';
import { UserRole } from '../types/api';

interface HeaderProps {
  currentUser: { email: string; role: UserRole } | null;
  onLogout: () => void;
  onRoleSwitch: (role: UserRole) => void;
  onToggleCopilot?: () => void;
  copilotOpen?: boolean;
}

const demoRoles: UserRole[] = ['ADMIN', 'PLANNER', 'REVIEWER', 'VIEWER'];

const pad = (n: number) => String(n).padStart(2, '0');

const useClock = () => {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(id);
  }, []);
  return now;
};

export const Header: React.FC<HeaderProps> = ({ currentUser, onLogout, onRoleSwitch, onToggleCopilot, copilotOpen }) => {
  const [roleMenuOpen, setRoleMenuOpen] = useState(false);
  const now = useClock();
  const { theme, toggle } = useTheme();

  const zulu = `${pad(now.getUTCHours())}:${pad(now.getUTCMinutes())}:${pad(now.getUTCSeconds())}Z`;
  const local = `${pad(now.getHours())}:${pad(now.getMinutes())}`;
  const date = now.toISOString().slice(0, 10);

  return (
    <header className="print:hidden h-12 shrink-0 border-b border-slate-800 bg-slate-925 px-5 flex items-center justify-between">
      <div className="flex items-center gap-5 font-mono text-xs">
        <span className="text-slate-100 text-[13px]">{zulu}</span>
        <span className="text-slate-500">
          LCL {local} <span className="mx-1.5 text-slate-700">|</span> {date}
        </span>
      </div>

      <div className="flex items-center gap-3 text-xs">
        {onToggleCopilot && (
          <button
            onClick={onToggleCopilot}
            aria-pressed={copilotOpen}
            className={`flex items-center gap-1.5 h-7 px-2.5 rounded border ${
              copilotOpen ? 'border-indigo-500 text-slate-100 bg-slate-800' : 'border-slate-800 text-slate-300 hover:border-slate-700'
            }`}
          >
            <MessageSquare className="w-3.5 h-3.5" />
            Copilot
          </button>
        )}
        <div className="relative">
          <button
            onClick={() => setRoleMenuOpen(!roleMenuOpen)}
            className="flex items-center gap-2 h-7 px-2.5 rounded border border-slate-800 text-slate-300 hover:border-slate-700"
          >
            <span className="text-slate-500">Role</span>
            <span className="font-medium">{currentUser?.role || 'VIEWER'}</span>
            <ChevronDown className="w-3 h-3 text-slate-500" />
          </button>

          {roleMenuOpen && (
            <div className="absolute right-0 mt-1 w-40 rounded glass-dropdown py-1 z-50">
              <div className="px-3 py-1 text-[10px] uppercase tracking-[0.1em] text-slate-500">Demo persona</div>
              {demoRoles.map((role) => (
                <button
                  key={role}
                  onClick={() => {
                    onRoleSwitch(role);
                    setRoleMenuOpen(false);
                  }}
                  className={`w-full text-left px-3 py-1.5 ${
                    currentUser?.role === role ? 'text-indigo-300 bg-slate-800' : 'text-slate-300 hover:bg-slate-800'
                  }`}
                >
                  {role}
                </button>
              ))}
            </div>
          )}
        </div>

        <span className="text-slate-400 hidden sm:inline">{currentUser?.email}</span>

        <button
          onClick={() => window.print()}
          title="Print this page"
          className="p-1.5 rounded text-slate-500 hover:text-slate-200 hover:bg-slate-800"
        >
          <Printer className="w-3.5 h-3.5" />
        </button>

        <button
          onClick={toggle}
          title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
          aria-label="Toggle colour theme"
          className="p-1.5 rounded text-slate-500 hover:text-slate-200 hover:bg-slate-800"
        >
          {theme === 'dark' ? <Sun className="w-3.5 h-3.5" /> : <Moon className="w-3.5 h-3.5" />}
        </button>

        <button
          onClick={onLogout}
          title="Sign out"
          className="p-1.5 rounded text-slate-500 hover:text-slate-200 hover:bg-slate-800"
        >
          <LogOut className="w-3.5 h-3.5" />
        </button>
      </div>
    </header>
  );
};
