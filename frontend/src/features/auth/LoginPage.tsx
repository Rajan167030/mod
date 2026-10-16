import React, { useState } from 'react';
import { Plane } from 'lucide-react';
import { api } from '../../api/client';
import { UserRole } from '../../types/api';

interface LoginPageProps {
  onLoginSuccess: (user: { email: string; role: UserRole }) => void;
}

const DEMO_ACCOUNTS: { role: UserRole; email: string; pass: string; can: string }[] = [
  { role: 'PLANNER', email: 'planner@airops.demo', pass: 'PlannerPass123!', can: 'Edit scenarios, log disruptions, run the optimiser' },
  { role: 'REVIEWER', email: 'reviewer@airops.demo', pass: 'ReviewerPass123!', can: 'Approve or reject proposed schedules' },
  { role: 'ADMIN', email: 'admin@airops.demo', pass: 'AdminPass123!', can: 'Everything, including the audit log' },
  { role: 'VIEWER', email: 'viewer@airops.demo', pass: 'ViewerPass123!', can: 'Read-only' },
];

export const LoginPage: React.FC<LoginPageProps> = ({ onLoginSuccess }) => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await api.login(email, password);
      onLoginSuccess({ email: res.email, role: res.role });
    } catch (err: any) {
      setError(err?.message || 'Sign-in failed. Check the email and password.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 flex items-center justify-center p-6">
      <div className="w-full max-w-[880px] grid grid-cols-1 md:grid-cols-[1fr_1fr] panel">
        <form onSubmit={handleLogin} className="p-8 space-y-4 border-b md:border-b-0 md:border-r border-slate-800">
          <div className="flex items-center gap-2 mb-6">
            <Plane className="w-4 h-4 text-indigo-400 -rotate-45" />
            <span className="text-sm font-semibold text-slate-100">AirOps Scheduler</span>
          </div>

          <h1 className="text-lg font-semibold text-slate-100">Sign in</h1>

          {error && (
            <div role="alert" className="border border-crit/40 bg-crit/5 px-3 py-2 text-xs text-crit">
              {error}
            </div>
          )}

          <div>
            <label className="label" htmlFor="login-email">
              Email
            </label>
            <input
              id="login-email"
              type="email"
              autoComplete="username"
              className="field w-full h-9"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoFocus
            />
          </div>
          <div>
            <label className="label" htmlFor="login-pass">
              Password
            </label>
            <input
              id="login-pass"
              type="password"
              autoComplete="current-password"
              className="field w-full h-9"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>

          <button type="submit" disabled={loading} className="btn-primary w-full h-9">
            {loading ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        <div className="p-8">
          <div className="text-[11px] uppercase tracking-[0.08em] text-slate-500 mb-3">Demo accounts</div>
          <ul className="space-y-1">
            {DEMO_ACCOUNTS.map((a) => (
              <li key={a.role}>
                <button
                  type="button"
                  onClick={() => {
                    setEmail(a.email);
                    setPassword(a.pass);
                    setError(null);
                  }}
                  className={`w-full text-left px-3 py-2 border text-xs ${
                    email === a.email ? 'border-indigo-500 bg-indigo-950/40' : 'border-slate-800 hover:border-slate-700'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-slate-200">{a.role}</span>
                    <span className="font-mono text-[10px] text-slate-500">{a.email}</span>
                  </div>
                  <div className="text-slate-500 mt-0.5">{a.can}</div>
                </button>
              </li>
            ))}
          </ul>
          <p className="text-[11px] text-slate-500 mt-4">
            Training prototype with fictional assets. Click an account to fill the form.
          </p>
        </div>
      </div>
    </div>
  );
};
