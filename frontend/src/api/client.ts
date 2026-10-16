import {
  AuthResponse, User, Scenario, Resource, Task, ScheduleVersion,
  ValidationResult, Disruption, OptimisationRun, ScheduleComparison,
  DashboardKPI, AuditEvent, Location, LocationCreate, LocationGeoJSONResponse,
  WeatherCurrentResponse, WeatherForecastResponse, WeatherAlertsResponse,
  WeatherRefreshResponse, WeatherThresholdConfig, MetarResponse,
  CoaSet, CoaAdoptResult, CoaKey, ExerciseState, CopilotReply
} from '../types/api';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

class ApiClient {
  private token: string | null = null;

  constructor() {
    this.token = localStorage.getItem('airops_token');
  }

  setToken(token: string | null) {
    this.token = token;
    if (token) {
      localStorage.setItem('airops_token', token);
    } else {
      localStorage.removeItem('airops_token');
    }
  }

  getToken(): string | null {
    return this.token;
  }

  private async request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...(options.headers as Record<string, string>),
    };

    if (this.token) {
      headers['Authorization'] = `Bearer ${this.token}`;
    }

    const response = await fetch(`${API_BASE}${endpoint}`, {
      ...options,
      headers,
    });

    if (!response.ok) {
      let errorData;
      try {
        errorData = await response.json();
      } catch {
        errorData = { message: response.statusText };
      }
      throw new Error(errorData.message || errorData.detail || 'API request failed');
    }

    if (response.status === 204) {
      return {} as T;
    }

    return response.json();
  }

  // Auth
  async login(email: string, password: string): Promise<AuthResponse> {
    const res = await this.request<AuthResponse>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
    this.setToken(res.access_token);
    return res;
  }

  async logout(): Promise<void> {
    try {
      await this.request('/auth/logout', { method: 'POST' });
    } finally {
      this.setToken(null);
    }
  }

  async getMe(): Promise<User> {
    return this.request<User>('/auth/me');
  }

  // Scenarios
  async getScenarios(): Promise<Scenario[]> {
    return this.request<Scenario[]>('/scenarios');
  }

  async getScenario(id: string): Promise<Scenario> {
    return this.request<Scenario>(`/scenarios/${id}`);
  }

  async createScenario(data: Partial<Scenario>): Promise<Scenario> {
    return this.request<Scenario>('/scenarios', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async generateSyntheticData(scenarioId: string): Promise<any> {
    return this.request(`/scenarios/${scenarioId}/generate-data`, {
      method: 'POST',
    });
  }

  // Resources
  async getResources(scenarioId?: string): Promise<Resource[]> {
    const query = scenarioId ? `?scenario_id=${scenarioId}` : '';
    return this.request<Resource[]>(`/resources${query}`);
  }

  async createResource(data: any): Promise<Resource> {
    return this.request<Resource>('/resources', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async updateResource(id: string, data: any): Promise<Resource> {
    return this.request<Resource>(`/resources/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  // Tasks
  async getTasks(scenarioId?: string): Promise<Task[]> {
    const query = scenarioId ? `?scenario_id=${scenarioId}` : '';
    return this.request<Task[]>(`/tasks${query}`);
  }

  async createTask(data: any): Promise<Task> {
    return this.request<Task>('/tasks', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  // Schedules
  async getScenarioSchedules(scenarioId: string): Promise<ScheduleVersion[]> {
    return this.request<ScheduleVersion[]>(`/scenarios/${scenarioId}/schedules`);
  }

  async getSchedule(scheduleId: string): Promise<ScheduleVersion> {
    return this.request<ScheduleVersion>(`/schedules/${scheduleId}`);
  }

  async validateSchedule(scheduleId: string): Promise<ValidationResult> {
    return this.request<ValidationResult>(`/schedules/${scheduleId}/validate`, {
      method: 'POST',
    });
  }

  // Disruptions
  async getDisruptions(scenarioId: string): Promise<Disruption[]> {
    return this.request<Disruption[]>(`/scenarios/${scenarioId}/disruptions`);
  }

  async injectDisruption(scenarioId: string, type: string, payload: any): Promise<Disruption> {
    return this.request<Disruption>(`/scenarios/${scenarioId}/disruptions`, {
      method: 'POST',
      body: JSON.stringify({
        scenario_id: scenarioId,
        type,
        payload_json: payload,
      }),
    });
  }

  // Optimisation
  async triggerOptimisation(scheduleId: string, options: any = {}): Promise<OptimisationRun> {
    return this.request<OptimisationRun>(`/schedules/${scheduleId}/optimisation-runs`, {
      method: 'POST',
      body: JSON.stringify({
        schedule_id: scheduleId,
        ...options,
      }),
    });
  }

  async getOptimisationRun(runId: string): Promise<OptimisationRun> {
    return this.request<OptimisationRun>(`/optimisation-runs/${runId}`);
  }

  /** The run that produced a proposed schedule version (needed to approve/reject it). */
  async getRunForSchedule(scheduleId: string): Promise<OptimisationRun> {
    return this.request<OptimisationRun>(`/schedules/${scheduleId}/optimisation-run`);
  }

  async getComparison(runId: string): Promise<ScheduleComparison> {
    return this.request<ScheduleComparison>(`/optimisation-runs/${runId}/comparison`);
  }

  // Courses of Action
  async generateCoursesOfAction(scheduleId: string, includeWeather: boolean, timeLimitSeconds = 8): Promise<CoaSet> {
    return this.request<CoaSet>(`/schedules/${scheduleId}/courses-of-action`, {
      method: 'POST',
      body: JSON.stringify({ include_weather: includeWeather, time_limit_seconds: timeLimitSeconds }),
    });
  }

  async getCoaSet(coaSetId: string): Promise<CoaSet> {
    return this.request<CoaSet>(`/courses-of-action/${coaSetId}`);
  }

  // Planning copilot
  async copilotStatus(): Promise<{ configured: boolean; model: string }> {
    return this.request('/copilot/status');
  }

  async copilotChat(scenarioId: string, message: string, conversationId?: string | null): Promise<CopilotReply> {
    return this.request<CopilotReply>('/copilot/chat', {
      method: 'POST',
      body: JSON.stringify({ scenario_id: scenarioId, message, conversation_id: conversationId ?? null }),
    });
  }

  // Live exercise
  async startExercise(speed = 60): Promise<ExerciseState> {
    return this.request<ExerciseState>('/replays', { method: 'POST', body: JSON.stringify({ script: 'winter_lift', speed }) });
  }

  async latestExercise(): Promise<ExerciseState | null> {
    return this.request<ExerciseState | null>('/replays/latest');
  }

  async getExercise(id: string): Promise<ExerciseState> {
    return this.request<ExerciseState>(`/replays/${id}`);
  }

  async controlExercise(id: string, action: 'pause' | 'resume' | 'speed' | 'skip', speed?: number): Promise<ExerciseState> {
    return this.request<ExerciseState>(`/replays/${id}/control`, { method: 'POST', body: JSON.stringify({ action, speed }) });
  }

  async decideExerciseEvent(
    id: string,
    idx: number,
    body: { action: 'adopt' | 'approve'; course?: CoaKey; reason?: string },
  ): Promise<ExerciseState> {
    return this.request<ExerciseState>(`/replays/${id}/events/${idx}/decision`, { method: 'POST', body: JSON.stringify(body) });
  }

  async closeExercise(id: string): Promise<void> {
    await this.request(`/replays/${id}`, { method: 'DELETE' });
  }

  async adoptCourseOfAction(coaSetId: string, key: CoaKey): Promise<CoaAdoptResult> {
    return this.request<CoaAdoptResult>(`/courses-of-action/${coaSetId}/${key}/adopt`, { method: 'POST' });
  }

  // Approvals
  async approveProposal(runId: string, reason: string): Promise<any> {
    return this.request(`/optimisation-runs/${runId}/approve`, {
      method: 'POST',
      body: JSON.stringify({ decision: 'APPROVED', reason }),
    });
  }

  async rejectProposal(runId: string, reason: string): Promise<any> {
    return this.request(`/optimisation-runs/${runId}/reject`, {
      method: 'POST',
      body: JSON.stringify({ decision: 'REJECTED', reason }),
    });
  }

  // Reports & KPIs
  async getDashboardKPI(): Promise<DashboardKPI> {
    return this.request<DashboardKPI>('/reports/dashboard');
  }

  async getScenarioReport(scenarioId: string): Promise<any> {
    return this.request(`/reports/scenario/${scenarioId}`);
  }

  getExportCsvUrl(scenarioId: string): string {
    return `${API_BASE}/reports/scenario/${scenarioId}/export-csv`;
  }

  // Audit
  async getAuditEvents(): Promise<AuditEvent[]> {
    return this.request<AuditEvent[]>('/audit-events');
  }

  // Locations (Geospatial GIS)
  async getLocations(scenarioId?: string): Promise<Location[]> {
    const query = scenarioId ? `?scenario_id=${scenarioId}` : '';
    return this.request<Location[]>(`/locations${query}`);
  }

  async createLocation(data: LocationCreate): Promise<Location> {
    return this.request<Location>('/locations', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async getLocationsGeoJSON(scenarioId?: string): Promise<LocationGeoJSONResponse> {
    const query = scenarioId ? `?scenario_id=${scenarioId}` : '';
    return this.request<LocationGeoJSONResponse>(`/locations/geojson${query}`);
  }

  // Weather Data & Alerts
  async getCurrentWeather(locationId: string): Promise<WeatherCurrentResponse> {
    return this.request<WeatherCurrentResponse>(`/weather/current?location_id=${locationId}`);
  }

  async getWeatherForecast(locationId: string): Promise<WeatherForecastResponse> {
    return this.request<WeatherForecastResponse>(`/weather/forecast?location_id=${locationId}`);
  }

  async getMetar(locationId: string): Promise<MetarResponse> {
    return this.request<MetarResponse>(`/weather/metar?location_id=${locationId}`);
  }

  async getWeatherAlerts(
    scenarioId: string,
    _thresholds?: WeatherThresholdConfig // backend applies configured thresholds
  ): Promise<WeatherAlertsResponse> {
    const query = `?scenario_id=${scenarioId}`;
    return this.request<WeatherAlertsResponse>(`/weather/alerts${query}`);
  }

  async refreshWeather(scenarioId: string, force: boolean = false): Promise<WeatherRefreshResponse> {
    return this.request<WeatherRefreshResponse>('/weather/refresh', {
      method: 'POST',
      body: JSON.stringify({ scenario_id: scenarioId, force }),
    });
  }
}

export const api = new ApiClient();
