import React, { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { api } from './api/client';
import { UserRole } from './types/api';
import { AppLayout } from './components/AppLayout';
import { LoginPage } from './features/auth/LoginPage';
import { DashboardPage } from './features/dashboard/DashboardPage';
import { ScenarioListPage } from './features/scenarios/ScenarioListPage';
import { ResourceManagementPage } from './features/resources/ResourceManagementPage';
import { TaskManagementPage } from './features/tasks/TaskManagementPage';
import { SchedulePage } from './features/schedule/SchedulePage';
import { DisruptionSimulator } from './features/disruptions/DisruptionSimulator';
import { OptimisationRunPanel } from './features/optimisation/OptimisationRunPanel';
import { ReviewPage } from './features/approvals/ReviewPage';
import { ReportsPage } from './features/reports/ReportsPage';
import { AuditPage } from './features/audit/AuditPage';
import { WeatherGISPage } from './features/weather/WeatherGISPage';
import { SchedulingImpactPage } from './features/scheduling-impact/SchedulingImpactPage';
import { CoursesOfActionPage } from './features/coa/CoursesOfActionPage';
import { ExercisePage } from './features/exercise/ExercisePage';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

export const App: React.FC = () => {
  const [currentUser, setCurrentUser] = useState<{ email: string; role: UserRole } | null>(null);
  const [authChecked, setAuthChecked] = useState(false);

  useEffect(() => {
    checkAuth();
  }, []);

  const checkAuth = async () => {
    const token = api.getToken();
    if (token) {
      try {
        const user = await api.getMe();
        setCurrentUser({ email: user.email, role: user.role });
      } catch {
        api.setToken(null);
        setCurrentUser(null);
      }
    } else {
      // Auto-login as PLANNER demo persona for seamless first-load inspection
      try {
        const loginRes = await api.login('planner@airops.demo', 'PlannerPass123!');
        setCurrentUser({ email: loginRes.email, role: loginRes.role });
      } catch {
        // Fallback to unauthenticated state if offline
      }
    }
    setAuthChecked(true);
  };

  const handleLogout = async () => {
    await api.logout();
    setCurrentUser(null);
  };

  const handleRoleSwitch = async (targetRole: UserRole) => {
    const roleMap: Record<UserRole, { email: string; pass: string }> = {
      ADMIN: { email: 'admin@airops.demo', pass: 'AdminPass123!' },
      PLANNER: { email: 'planner@airops.demo', pass: 'PlannerPass123!' },
      REVIEWER: { email: 'reviewer@airops.demo', pass: 'ReviewerPass123!' },
      VIEWER: { email: 'viewer@airops.demo', pass: 'ViewerPass123!' },
    };
    const target = roleMap[targetRole];
    if (target) {
      try {
        const res = await api.login(target.email, target.pass);
        setCurrentUser({ email: res.email, role: res.role });
      } catch (err) {
        console.error('Role switch failed', err);
      }
    }
  };

  if (!authChecked) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center text-slate-500 font-mono text-xs">
        Connecting…
      </div>
    );
  }

  if (!currentUser) {
    return <LoginPage onLoginSuccess={setCurrentUser} />;
  }

  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route
            element={
              <AppLayout
                currentUser={currentUser}
                onLogout={handleLogout}
                onRoleSwitch={handleRoleSwitch}
              />
            }
          >
            <Route path="/" element={<DashboardPage />} />
            <Route path="/scenarios" element={<ScenarioListPage />} />
            <Route path="/weather" element={<WeatherGISPage />} />
            <Route path="/scheduling-impact" element={<SchedulingImpactPage />} />
            <Route path="/resources" element={<ResourceManagementPage />} />
            <Route path="/tasks" element={<TaskManagementPage />} />
            <Route path="/schedule" element={<SchedulePage />} />
            <Route path="/disruptions" element={<DisruptionSimulator />} />
            <Route path="/optimisation" element={<OptimisationRunPanel />} />
            <Route path="/courses-of-action" element={<CoursesOfActionPage />} />
            <Route path="/exercise" element={<ExercisePage />} />
            <Route path="/review" element={<ReviewPage />} />
            <Route path="/reports" element={<ReportsPage />} />
            <Route path="/audit" element={<AuditPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
};

export default App;
