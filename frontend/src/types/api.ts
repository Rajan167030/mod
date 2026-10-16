export type UserRole = 'ADMIN' | 'PLANNER' | 'REVIEWER' | 'VIEWER';

export interface User {
  id: string;
  email: string;
  role: UserRole;
  is_active: boolean;
  created_at: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user_id: string;
  email: string;
  role: UserRole;
}

export interface Scenario {
  id: string;
  name: string;
  description?: string;
  status: 'ACTIVE' | 'ARCHIVED' | 'DRAFT';
  created_by?: string;
  created_at: string;
  updated_at: string;
}

export interface ResourceAvailability {
  id?: string;
  start_at: string;
  end_at: string;
  available: boolean;
}

export interface Resource {
  id: string;
  scenario_id: string;
  name: string;
  resource_type: string;
  status: 'AVAILABLE' | 'MAINTENANCE' | 'GROUNDED' | 'UNAVAILABLE';
  metadata_json?: {
    qualifications?: string[];
    max_payload_kg?: number;
    capacity?: number;
    [key: string]: any;
  };
  availabilities?: ResourceAvailability[];
}

export interface TaskRequirement {
  id?: string;
  requirement_type: string;
  requirement_value: string;
}

export interface Task {
  id: string;
  scenario_id: string;
  name: string;
  description?: string;
  duration_minutes: number;
  earliest_start: string;
  latest_finish: string;
  priority: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW';
  status: 'PENDING' | 'SCHEDULED' | 'BLOCKED' | 'COMPLETED';
  location_id?: string | null;
  requirements: TaskRequirement[];
}

export interface Assignment {
  id: string;
  schedule_version_id: string;
  task_id: string;
  resource_id: string;
  start_at: string;
  end_at: string;
  task_name?: string;
  resource_name?: string;
  priority?: string;
  task_location_id?: string | null;
}

export interface ScheduleVersion {
  id: string;
  scenario_id: string;
  version_number: number;
  parent_version_id?: string | null;
  status: 'DRAFT' | 'PROPOSED' | 'APPROVED' | 'REJECTED' | 'SUPERSEDED';
  created_by?: string;
  created_at: string;
  assignments: Assignment[];
}

export interface ConflictItem {
  code: string;
  severity: 'CRITICAL' | 'WARNING';
  resource_id?: string;
  resource_name?: string;
  task_ids: string[];
  task_names: string[];
  conflict_start?: string;
  conflict_end?: string;
  explanation: string;
}

export interface ValidationResult {
  schedule_id: string;
  is_valid: boolean;
  total_assignments: number;
  conflict_count: number;
  conflicts: ConflictItem[];
  unassigned_task_count: number;
  unassigned_task_ids: string[];
}

export interface Disruption {
  id: string;
  scenario_id: string;
  type: string;
  payload_json: Record<string, any>;
  created_by?: string;
  created_at: string;
}

export interface OptimisationRun {
  id: string;
  schedule_version_id: string;
  new_schedule_version_id?: string;
  status: 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED';
  solver_status?: 'OPTIMAL' | 'FEASIBLE' | 'INFEASIBLE' | 'UNKNOWN';
  objective_value?: number;
  metrics_json?: {
    execution_time_seconds?: number;
    total_tasks?: number;
    assigned_tasks?: number;
    unassigned_tasks?: number;
    branches?: number;
    conflicts?: number;
    [key: string]: any;
  };
  started_at: string;
  finished_at?: string;
  error_summary?: string;
  validation?: ValidationResult;
  advisory_explanation?: string;
}

export interface TaskChange {
  task_id: string;
  task_name: string;
  change_type: 'UNCHANGED' | 'REASSIGNED' | 'TIME_SHIFTED' | 'NEWLY_ASSIGNED' | 'DROPPED';
  details: string;
  baseline_resource?: string;
  proposed_resource?: string;
  baseline_start?: string;
  proposed_start?: string;
}

export interface ScheduleComparison {
  baseline_version_id: string;
  proposed_version_id: string;
  baseline_version_number: number;
  proposed_version_number: number;
  total_tasks: number;
  baseline_assigned: number;
  proposed_assigned: number;
  tasks_reassigned: number;
  tasks_time_shifted: number;
  total_delay_minutes_baseline: number;
  total_delay_minutes_proposed: number;
  delay_change_minutes: number;
  changes: TaskChange[];
}

export interface AuditEvent {
  id: string;
  actor_id?: string;
  actor_email?: string;
  action: string;
  entity_type: string;
  entity_id?: string;
  metadata_json?: Record<string, any>;
  created_at: string;
}

export interface DashboardKPI {
  scenario_id?: string | null;
  scenario_name?: string | null;
  active_version_number?: number | null;
  total_scenarios: number;
  total_resources: number;
  total_tasks: number;
  assigned_tasks: number;
  unassigned_tasks: number;
  active_conflicts: number;
  latest_optimisation_status?: string;
  schedule_completion_rate: number;
  resource_utilization_rate: number;
  recent_audits: AuditEvent[];
}

// ==========================================
// Weather & Geospatial Types (Synthetic Only)
// ==========================================
export type LocationType = 'BASE' | 'WAYPOINT' | 'WEATHER_STATION' | 'POI' | 'LOGISTICS_HUB';

export interface Location {
  id: string;
  scenario_id: string;
  name: string;
  latitude: number;
  longitude: number;
  location_type: LocationType;
  metadata_json?: {
    description?: string;
    elevation_m?: number;
    [key: string]: any;
  };
  created_at: string;
}

export interface LocationCreate {
  scenario_id: string;
  name: string;
  latitude: number;
  longitude: number;
  location_type: LocationType;
  metadata_json?: Record<string, any>;
}

export interface GeoJSONGeometry {
  type: 'Point';
  coordinates: [number, number]; // [lon, lat]
}

export interface GeoJSONFeature {
  type: 'Feature';
  geometry: GeoJSONGeometry;
  properties: {
    id: string;
    name: string;
    location_type: LocationType;
    scenario_id: string;
    metadata: Record<string, any>;
    active_alerts_count?: number;
    highest_severity?: 'CRITICAL' | 'WARNING' | 'INFO' | null;
  };
}

export interface LocationGeoJSONResponse {
  type: 'FeatureCollection';
  features: GeoJSONFeature[];
}

export type FreshnessStatus = 'FRESH' | 'STALE' | 'UNKNOWN';

export interface WeatherDataPoint {
  forecast_timestamp: string;
  temperature_celsius?: number | null;
  precipitation_mm?: number | null;
  wind_speed_kmh?: number | null;
  weather_condition?: string | null;
  wind_gust_kmh?: number | null;
  wind_direction_deg?: number | null;
  visibility_m?: number | null;
  cloud_cover_pct?: number | null;
  relative_humidity_pct?: number | null;
  pressure_hpa?: number | null;
  dew_point_celsius?: number | null;
  units?: Record<string, string>;
}

// Mirrors backend app/schemas/weather_schemas.py
export interface WeatherCurrentResponse {
  location_id: string;
  location_name: string;
  latitude: number | null;
  longitude: number | null;
  provider: string;
  data: WeatherDataPoint | null;
  freshness: FreshnessStatus;
  retrieved_at: string | null;
  data_source: string;
  disclaimer: string;
}

export interface WeatherForecastResponse {
  location_id: string;
  location_name: string;
  latitude: number | null;
  longitude: number | null;
  provider: string;
  forecast_points: WeatherDataPoint[];
  freshness: FreshnessStatus;
  retrieved_at: string | null;
  data_source: string;
  disclaimer: string;
}

export type FlightCategory = 'VFR' | 'MVFR' | 'IFR' | 'LIFR';

export interface MetarObservation {
  station_id: string;
  station_name: string | null;
  latitude: number;
  longitude: number;
  elevation_m: number | null;
  distance_km: number;
  observed_at: string | null;
  raw_metar: string;
  raw_taf: string | null;
  flight_category: FlightCategory | null;
  temperature_celsius: number | null;
  dew_point_celsius: number | null;
  wind_direction_deg: number | null;
  wind_speed_kt: number | null;
  wind_gust_kt: number | null;
  visibility: string | null;
  altimeter_hpa: number | null;
  clouds: { cover: string; base_ft: number | null }[];
}

export interface MetarResponse {
  location_id: string;
  location_name: string;
  provider: string;
  search_radius_km: number;
  observation: MetarObservation | null;
  message: string | null;
}

export type AlertSeverity = 'CRITICAL' | 'WARNING' | 'INFO';

export interface WeatherAlertItem {
  location_id: string;
  location_name: string;
  forecast_timestamp: string;
  source_timestamp: string;
  variable: 'wind_speed' | 'precipitation' | 'temperature' | 'all';
  observed_value: number;
  threshold: number;
  severity: AlertSeverity;
  freshness: FreshnessStatus;
  explanation: string;
  source?: 'forecast' | 'exercise';
}

export interface WeatherThresholdConfig {
  wind_speed_warning_kmh?: number;
  wind_speed_critical_kmh?: number;
  precipitation_warning_mm?: number;
  precipitation_critical_mm?: number;
  temperature_low_warning_celsius?: number;
  temperature_low_critical_celsius?: number;
}

export interface WeatherAlertsResponse {
  scenario_id: string;
  alerts: WeatherAlertItem[];
  total_alerts: number;
  critical_count: number;
  warning_count: number;
  freshness_summary: FreshnessStatus;
  thresholds_used: WeatherThresholdConfig;
}

export interface WeatherConstraint {
  alert: WeatherAlertItem;
  constraint_type: 'HARD_BLACKOUT' | 'SOFT_PENALTY' | 'REVIEW_FLAG';
  affected_resource_ids?: string[];
  affected_task_ids?: string[];
  penalty_weight?: number;
  explanation: string;
}

export interface WeatherConstraintsResponse {
  scenario_id: string;
  constraints: WeatherConstraint[];
  total_constraints: number;
  hard_constraints: number;
  soft_constraints: number;
  review_flags: number;
  weather_data_available: boolean;
  freshness_summary: FreshnessStatus;
}

export interface WeatherRefreshResponse {
  success: boolean;
  refreshed_locations: number;
  errors: string[];
  refreshed_at: string;
}


// ==========================================
// Courses of Action
// ==========================================
export type CoaKey = 'FASTEST' | 'STABLE' | 'SAFEST' | 'PRIORITY';
export type CoaChange = 'UNCHANGED' | 'REASSIGNED' | 'RETIMED' | 'NEW' | 'DROPPED' | 'UNASSIGNED';

export interface CoaTaskOutcome {
  task_id: string;
  task_name: string;
  priority: string;
  resource_id: string | null;
  resource_name: string | null;
  start_at: string | null;
  end_at: string | null;
  delay_minutes: number | null;
  change: CoaChange;
  weather_exposure: 'CRITICAL' | 'WARNING' | null;
}

export interface CoaMetrics {
  assigned: number;
  unassigned: number;
  unassigned_critical: number;
  unassigned_high: number;
  total_delay_minutes: number;
  critical_avg_delay_minutes: number | null;
  reassigned: number;
  retimed: number;
  unchanged: number;
  finish_at: string | null;
  weather_exposed_critical: number;
  weather_exposed_warning: number;
  validator_pass: boolean;
  validator_conflicts: number;
}

export interface CourseOfAction {
  key: CoaKey;
  label: string;
  intent: string;
  solver_status: string;
  objective_value: number | null;
  solve_seconds: number;
  metrics: CoaMetrics | null;
  tasks: CoaTaskOutcome[];
  recommended: boolean;
  note: string | null;
  same_as: CoaKey | null;
}

export interface CoaSet {
  coa_set_id: string;
  baseline_version_id: string;
  baseline_version_number: number;
  include_weather: boolean;
  generated_at: string;
  expires_at: string;
  courses: CourseOfAction[];
  recommendation_reason: string | null;
  best_by_metric: Record<string, CoaKey[]>;
}

export interface CoaAdoptResult {
  run_id: string;
  proposed_version_id: string | null;
  proposed_version_number: number | null;
  status: string;
}

// ==========================================
// Live exercise
// ==========================================
export type ExerciseEventStatus = 'PENDING' | 'NO_ACTION' | 'REPLANNING' | 'READY' | 'DECIDED' | 'ERROR';

export interface ExerciseEvent {
  idx: number;
  at_min: number;
  kind: string;
  title: string;
  detail: string;
  status: ExerciseEventStatus;
  effect?: string;
  applied_sim_at?: string;
  applied_wall_at?: string;
  conflicts_after?: number;
  unassigned_after?: number;
  weather_exposed_after?: number;
  coa_set_id?: string;
  replan_from_version?: string;
  suggested_key?: CoaKey | null;
  suggested_label?: string | null;
  recommendation_reason?: string | null;
  replan_seconds?: number;
  error?: string;
  decision?: {
    stage: 'ADOPTED' | 'APPROVED';
    course: CoaKey;
    run_id: string;
    version_number: number | null;
    by?: string;
    approved_by?: string;
    reason?: string;
    decided_wall_at: string;
  };
}

export interface ExerciseSummary {
  events_applied: number;
  replans: number;
  avg_replan_seconds: number | null;
  decisions: number;
  avg_decision_seconds: number | null;
  active_version: number | null;
  active_conflicts: number | null;
  active_unassigned: number | null;
  original_plan_conflicts: number | null;
  original_plan_unassigned: number | null;
  critical_tasks: number;
  critical_covered: number;
}

export interface ExerciseState {
  id: string;
  scenario_id: string;
  script: string;
  title: string;
  status: 'RUNNING' | 'PAUSED' | 'FINISHED';
  speed: number;
  speeds: number[];
  sim_t0: string;
  sim_now: string;
  end_min: number;
  active_version_id: string | null;
  active_version_number: number | null;
  events: ExerciseEvent[];
  summary: ExerciseSummary;
}

// ==========================================
// Planning copilot
// ==========================================
export interface CopilotStep {
  tool: string | null;
  label: string;
  input: Record<string, unknown>;
  error: boolean;
}

export interface CopilotReply {
  conversation_id: string;
  reply: string;
  steps: CopilotStep[];
  stop_reason: string | null;
  model: string | null;
}
