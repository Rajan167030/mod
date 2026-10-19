import React from 'react';
import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  Layers,
  Plane,
  ListTodo,
  CalendarDays,
  Zap,
  Sliders,
  CheckCircle,
  FileBarChart2,
  ScrollText,
  CloudSun,
  CloudLightning,
  GitCompare,
  Radio,
  Network,
  Map as MapIcon,
  Upload,
  Bell,
  GitBranch,
  ShieldAlert,
  Users,
  Gauge,
  Globe2,
  PlaneTakeoff,
  BarChart3,
} from 'lucide-react';
import { UserRole } from '../types/api';

interface SidebarProps {
  userRole?: UserRole;
}

const navGroups = [
  {
    title: 'Overview',
    items: [
      { to: '/', label: 'Dashboard', icon: LayoutDashboard },
      { to: '/execution', label: 'Mission execution', icon: PlaneTakeoff },
      { to: '/exercise', label: 'Live exercise', icon: Radio },
      { to: '/explorer', label: 'Object explorer', icon: Network },
      { to: '/ops-map', label: 'Ops map', icon: MapIcon },
      { to: '/scenarios', label: 'Scenarios', icon: Layers },
      { to: '/compare', label: 'Compare branches', icon: GitBranch },
      { to: '/import', label: 'Data import', icon: Upload },
    ],
  },
  {
    title: 'Battlespace',
    items: [
      { to: '/theatre', label: 'Theatre map', icon: Globe2 },
      { to: '/threats', label: 'Threats & airspace', icon: ShieldAlert },
      { to: '/readiness', label: 'Crews & stores', icon: Users },
      { to: '/risk', label: 'Mission risk', icon: Gauge },
    ],
  },
  {
    title: 'Weather',
    items: [
      { to: '/weather', label: 'Stations & map', icon: CloudSun },
      { to: '/scheduling-impact', label: 'Schedule impact', icon: CloudLightning },
    ],
  },
  {
    title: 'Planning',
    items: [
      { to: '/resources', label: 'Resources', icon: Plane },
      { to: '/tasks', label: 'Missions', icon: ListTodo },
      { to: '/capacity', label: 'Capacity', icon: BarChart3 },
      { to: '/schedule', label: 'Timeline', icon: CalendarDays },
      { to: '/disruptions', label: 'Disruptions', icon: Zap },
      { to: '/courses-of-action', label: 'Courses of action', icon: GitCompare },
      { to: '/optimisation', label: 'Optimiser', icon: Sliders },
    ],
  },
  {
    title: 'Governance',
    items: [
      { to: '/alerts', label: 'Alerts', icon: Bell },
      { to: '/review', label: 'Review', icon: CheckCircle },
      { to: '/reports', label: 'Reports', icon: FileBarChart2 },
      { to: '/audit', label: 'Audit log', icon: ScrollText },
    ],
  },
];

export const Sidebar: React.FC<SidebarProps> = () => {
  return (
    <aside className="w-52 shrink-0 select-none print:hidden border-r border-slate-800 bg-slate-925 flex flex-col">
      <div className="h-12 px-4 flex items-center gap-2 border-b border-slate-800">
        <Plane className="w-4 h-4 text-indigo-400 -rotate-45" />
        <span className="text-sm font-semibold text-slate-100 tracking-tight">AirOps</span>
        <span className="ml-auto font-mono text-[10px] text-slate-500">PS-26250</span>
      </div>

      <nav className="flex-1 overflow-y-auto py-2">
        {navGroups.map((group) => (
          <div key={group.title} className="mb-2">
            <div className="px-4 pt-2 pb-1 text-[10px] font-medium uppercase tracking-[0.1em] text-slate-500">
              {group.title}
            </div>
            {group.items.map((item) => {
              const Icon = item.icon;
              return (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.to === '/'}
                  className={({ isActive }) =>
                    `flex items-center gap-2.5 h-8 px-4 text-[13px] border-l-2 transition-colors ${
                      isActive
                        ? 'border-indigo-400 bg-slate-900 text-slate-100'
                        : 'border-transparent text-slate-400 hover:text-slate-200 hover:bg-slate-900/60'
                    }`
                  }
                >
                  <Icon className="w-3.5 h-3.5 shrink-0" />
                  <span>{item.label}</span>
                </NavLink>
              );
            })}
          </div>
        ))}
      </nav>

      <div className="px-4 py-3 border-t border-slate-800 text-[11px] leading-snug text-slate-500">
        Training prototype. Fictional assets and sites; weather is live.
      </div>
    </aside>
  );
};
