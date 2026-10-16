import React, { useState } from 'react';
import { Outlet } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { Header } from './Header';
import { CopilotPanel } from './CopilotPanel';
import { UserRole } from '../types/api';

interface AppLayoutProps {
  currentUser: { email: string; role: UserRole } | null;
  onLogout: () => void;
  onRoleSwitch: (role: UserRole) => void;
}

export const AppLayout: React.FC<AppLayoutProps> = ({ currentUser, onLogout, onRoleSwitch }) => {
  const [copilotOpen, setCopilotOpen] = useState(false);
  return (
    <div className="app-shell flex h-screen bg-slate-950 overflow-hidden">
      <Sidebar userRole={currentUser?.role} />
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <Header
          currentUser={currentUser}
          onLogout={onLogout}
          onRoleSwitch={onRoleSwitch}
          onToggleCopilot={() => setCopilotOpen((v) => !v)}
          copilotOpen={copilotOpen}
        />
        <main className="flex-1 overflow-y-auto p-5">
          <div className="max-w-[1600px] mx-auto space-y-5">
            <Outlet />
          </div>
        </main>
      </div>
      <CopilotPanel open={copilotOpen} onClose={() => setCopilotOpen(false)} />
    </div>
  );
};
