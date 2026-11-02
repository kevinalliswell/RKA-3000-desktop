// Types mirror docs/api.md. Business rules live in Python; these are shapes only.

export interface ApiErrorBody {
  code: string;
  message: string;
  detail?: unknown;
}

export interface Health {
  ok: boolean;
  service: string;
  version: string;
  api_version: number;
  simulation_mode: boolean;
  device_backend: 'multi_device' | 'plc_modbus';
  run_active: boolean;
  data_dir: string;
  export_dir: string;
  database: string;
  log_path: string;
  restart_required: boolean;
  notes: string[];
}

export type GasKey = 'N2' | 'AR' | 'H2' | 'CO' | 'CO2' | 'CH4' | 'O2';
export type ExperimentType = 'reduction' | 'oxidation';
export type Flows = Partial<Record<GasKey, number>>;

export interface RecipeStep {
  step_no: number;
  name: string;
  target_temp_c: number;
  ramp_rate_cpm: number;
  hold_seconds: number;
  n2_lpm: number;
  ar_lpm: number;
  h2_lpm: number;
  co_lpm: number;
  co2_lpm: number;
  ch4_lpm: number;
  o2_lpm: number;
  notes: string;
}

export interface RuleCheck {
  key: string;
  label: string;
  ok: boolean;
  detail: string;
  step_issues: Record<string, string>;
}

export interface RecipeAssessment {
  runnable: boolean;
  summary: string;
  checks: RuleCheck[];
  step_issues: Record<string, string[]>;
}

export interface RecipeMeta {
  experiment_type: ExperimentType;
  inert_gas: 'N2' | 'AR';
  purge_lpm: number;
  purge_seconds: number;
  description: string;
}

export interface RecipeSummary extends RecipeMeta {
  id: number;
  name: string;
  version: number;
  created_at: string;
  updated_at: string;
  runnable: boolean;
  summary: string;
  step_count: number;
  experiment_count: number;
  limits_version: number;
}

export interface RecipeVersion {
  version: number;
  reason: string;
  actor: string;
  created_at: string;
}

export interface Recipe extends RecipeMeta {
  id: number;
  name: string;
  version: number;
  created_at: string;
  updated_at: string;
  steps: RecipeStep[];
  assessment: RecipeAssessment;
  versions: RecipeVersion[];
  experiment_count: number;
  limits_version: number;
  running: boolean;
}

export interface RecipeDocument {
  format: 'rka3000-recipe';
  version: number;
  name: string;
  steps: RecipeStep[];
}

export type RunStatus =
  | 'idle' | 'starting' | 'running' | 'paused' | 'interrupted' | 'purging' | 'stopping' | 'stopped' | 'completed' | 'faulted';

export interface RunAllowed {
  start: boolean;
  pause: boolean;
  resume: boolean;
  stop: boolean;
  emergency: boolean;
  ack_alarm: boolean;
  reset_interlock: boolean;
  set_gas_mode: boolean;
  manual_gas: boolean;
}

export interface Snapshot {
  temperature_c: number | null;
  weight_g: number | null;
  pressure_mpa: number;
  flows: Flows | null;
  alarm_word: number;
  interlock_word: number;
  run_control_word: number;
  estop_status: number;
}

export interface PendingAlarm {
  id: number;
  experiment_id: number | null;
  code: string;
  level: string;
  message: string;
  created_at: string;
}

export interface RunExperiment {
  id: number;
  code: string;
  sample_name: string;
  operator: string;
  initial_mass_g: number;
  tfe_pct: number;
  feo_pct: number;
  experiment_type: ExperimentType;
  inert_gas: 'N2' | 'AR';
  recipe_id: number;
  recipe_name: string;
  recipe_version: number;
  limits_version: number;
  started_at: string;
  purge_lpm: number;
  purge_seconds: number;
}

export interface RunStep extends RecipeStep {
  display_name: string;
  flows: Record<GasKey, number>;
  state: 'done' | 'active' | 'pending' | 'skipped' | 'interrupted';
  kind: 'inert' | 'reaction';
  started_at: string | null;
  ended_at: string | null;
}

export interface Purge {
  required_s: number;
  elapsed_s: number;
  flows: Record<GasKey, number>;
  summary: string;
  safe_temperature_c: number;
  temperature_ok: boolean;
  heating: string;
  heating_text: string;
  started_at: string;
  apply_error: string | null;
  inert_gas: string;
}

export interface GasCard {
  gas: GasKey;
  label: string;
  hazard: string;
  inert: boolean;
  allowed: boolean;
  device_limit: number;
  usage_limit: number | null;
  pv: number | null;
  readback: number | null;
  commanded: number;
  recipe: number | null;
  state: 'flowing' | 'closed' | 'purging' | 'disabled';
}

export interface Live {
  temperature_c: number | null;
  target_temp_c: number | null;
  weight_g: number | null;
  reference_weight_g: number | null;
  delta_m_g: number | null;
  degree_pct: number | null;
  degree_kind: ExperimentType;
  total_flow_lpm: number | null;
  flow_summary: string;
  reaction_started_at: string | null;
  sample_age_s: number | null;
}

export interface CommandStep {
  code: string;
  ok: boolean;
  label: string;
  at: string;
}

export interface Command {
  id: number;
  kind: string;
  target: Flows;
  summary: string;
  state: 'accepted' | 'applied' | 'failed';
  steps: CommandStep[];
  message: string;
}

export interface RunEvent {
  at: string;
  kind: 'stage' | 'command' | 'alarm' | 'safety' | 'system';
  title: string;
  detail: string;
  actor: string;
}

export interface RunState {
  seq: number;
  status: RunStatus;
  pending_terminal: string | null;
  engine_state: string;
  run_id: string | null;
  experiment_id: number | null;
  recipe_id: number | null;
  recipe_name: string | null;
  started_at: string | null;
  finished_at: string | null;
  elapsed_s: number | null;
  error: string | null;
  current_step_no: number | null;
  total_steps: number;
  current_step: RecipeStep | null;
  status_text: string;
  setpoints_text: string;
  gas_mode: 'auto' | 'manual';
  temperature_mode: 'program' | 'setpoint';
  temperature_program: { group: number; segments: number; message: string; remote_start: boolean } | null;
  manual_gas: Flows | null;
  experiment: RunExperiment | null;
  steps: RunStep[];
  step_progress: { step_no: number; target_reached: boolean; hold_elapsed_s: number; hold_s: number } | null;
  purge: Purge | null;
  end_reason: string | null;
  end_reason_text: string | null;
  end_detail: string | null;
  emergency: boolean;
  gases: GasCard[];
  live: Live | null;
  last_command: Command | null;
  alarm: { word: number; text: string; active: { code: string; level: string; message: string; interlock: boolean }[] };
  interlock: { word: number; text: string; estop: boolean; resettable: boolean; active: { code: string; message: string; resettable: boolean }[] };
  control_feedback: { word: number; estop_status: number; consistent: boolean; message: string };
  pending_alarms: PendingAlarm[];
  degraded_devices: string[];
  stale_devices: string[];
  latest: Snapshot | null;
  allowed: RunAllowed;
  blocked: Record<string, string | null>;
  connected: boolean;
  events: RunEvent[];
}

export interface MeasurementPoint {
  seq?: number;
  id?: number;
  sampled_at: string;
  phase?: 'run' | 'purge';
  temperature_c: number | null;
  weight_g: number | null;
  pressure_mpa: number;
  flows?: Flows | null;
  n2_lpm: number;
  h2_lpm: number;
  co_lpm: number;
}

export interface PreflightCheck {
  key: string;
  label: string;
  ok: boolean;
  detail: string;
  blocking: boolean;
}

export interface SampleInput {
  name: string;
  initial_mass_g: number | null;
  tfe_pct: number | null;
  feo_pct: number | null;
  operator: string;
  particle_size: string;
}

export interface PreflightResult {
  ready: boolean;
  checks: PreflightCheck[];
  recipe: (RecipeMeta & { id: number; name: string; version: number; steps: RecipeStep[] }) | null;
  assessment: RecipeAssessment | null;
  readings: { connected: boolean; temperature_c?: number | null; weight_g?: number | null; flows?: Flows | null; degraded?: string[] };
  balance_g: number | null;
  mass_deviation_pct: number | null;
  limits_version: number;
  usage_limits: Flows;
  checklist_items: { key: string; label: string; detail: string }[];
  temperature_mode: 'program' | 'setpoint';
  safe_temperature_c: number;
}

export interface StartRequest {
  recipe_id: number;
  sample: SampleInput;
  checklist: Record<string, boolean>;
  gas_mode?: 'auto' | 'manual';
}

export interface DeviceDescription {
  backend: string;
  simulation: boolean;
  summary: string;
  devices: { name: string; label: string; port?: string; slave_id?: number; protocol?: string }[];
  mfc_channels: { address: number; gas: string; full_scale_lpm: number; role: string | null; label?: string }[];
  capabilities?: Record<string, boolean>;
  temperature_program?: { group: number; time_unit: string; max_steps: number };
}

export interface DeviceStatus {
  supported: boolean;
  connected?: boolean;
  temperature_c?: number;
  mfc?: { address: number; flow_lpm: number; setpoint_lpm: number }[];
  weight_g?: number;
  degraded_devices?: string[];
  description: DeviceDescription;
}

export type ExperimentCategory = 'running' | 'pending' | 'archived' | 'aborted';

export interface Kpi {
  degree_kind: ExperimentType;
  final_degree_pct: number;
  time_to_40_min: number | null;
  time_to_60_min: number | null;
  rate_at_40_pct: number | null;
  best_fit: { id: string; name: string; k_per_min: number; r2: number; n: number | null } | null;
}

export interface ExperimentSummary {
  id: number;
  code: string;
  name: string;
  status: string;
  category: ExperimentCategory;
  recipe_id: number | null;
  recipe_name: string | null;
  recipe_version: number | null;
  started_at: string;
  finished_at: string | null;
  experiment_type: ExperimentType | null;
  inert_gas: string | null;
  sample_name: string | null;
  operator: string | null;
  review_state: 'pending' | 'archived' | null;
  end_reason: string | null;
  archived_at: string | null;
  kpi: Kpi | null;
  initial_mass_g: number | null;
  final_mass_g: number | null;
}

export interface AuditRecord {
  id: number;
  actor: string;
  action: string;
  detail: string;
  created_at: string;
  experiment_id: number | null;
  category: string | null;
  reason: string | null;
  result: string | null;
}

export interface AlarmRecord {
  id: number;
  experiment_id: number | null;
  code: string;
  level: string;
  message: string;
  created_at: string;
  acknowledged_at: string | null;
  acknowledged_by: string | null;
  ack_note: string | null;
}

export interface ExperimentDetail extends ExperimentSummary {
  tfe_pct: number | null;
  feo_pct: number | null;
  particle_size: string | null;
  balance_mass_g: number | null;
  recipe_snapshot: (RecipeMeta & { name: string; version: number; steps: RecipeStep[] }) | null;
  limits_version: number | null;
  checklist: Record<string, boolean> | null;
  end_detail: string | null;
  reaction_started_at: string | null;
  reaction_ended_at: string | null;
  purge_required_s: number | null;
  purge_done_s: number | null;
  final_temperature_c: number | null;
  archive_note: string | null;
  archived_by: string | null;
  summary: {
    sample_count: number; first_sampled_at: string; last_sampled_at: string;
    min_temperature_c: number; max_temperature_c: number; min_weight_g: number; max_weight_g: number;
  } | null;
  measurement_count: number;
  events: AuditRecord[];
  alarms: AlarmRecord[];
}

export interface ExperimentList {
  experiments: ExperimentSummary[];
  counts: Record<ExperimentCategory, number>;
}

export interface SampleParams {
  initial_mass_g: number | null;
  tfe_pct: number | null;
  feo_pct: number | null;
  locked?: boolean;
}

export interface ModelFit {
  id: string;
  name: string;
  g_expr: string;
  k_per_min: number;
  r2: number;
  n: number | null;
  curve: { t_min: number; alpha: number }[];
}

export interface KineticsResult {
  experiment_id: number;
  params: { initial_mass_g: number; tfe_pct: number; feo_pct: number };
  degree_kind: ExperimentType;
  window: { source: 'reaction' | 'all'; start: string | null; end: string | null };
  points: { t_min: number; reduction_degree_pct: number; rate_pct_per_min: number }[];
  final_degree_pct: number;
  time_to_40_min: number | null;
  time_to_60_min: number | null;
  rate_at_40_pct: number | null;
  fit_window: [number, number];
  fits: ModelFit[];
  best_fit: string | null;
}

export interface ReviewCheck {
  key: string;
  label: string;
  severity: 'ok' | 'warn' | 'block';
  detail: string;
}

export interface ReviewResult {
  experiment: ExperimentDetail;
  stats: { count: number; gaps: number; gap_seconds: number; reversals: number; duration_seconds: number; complete: boolean };
  alarms: AlarmRecord[];
  checks: ReviewCheck[];
  can_archive: boolean;
  note_required: boolean;
}

export interface CompareRow {
  id: number;
  code: string;
  sample_name: string;
  recipe_version: number | null;
  time_to_40_min: number | null;
  time_to_60_min: number | null;
  final_degree_pct: number | null;
  current: boolean;
}

export interface ReportRecord {
  id: number;
  experiment_id: number;
  version: number;
  path: string;
  actor: string;
  created_at: string;
}

export interface ReportItem extends ExperimentSummary {
  reports: ReportRecord[];
  latest_report: ReportRecord | null;
  can_generate: boolean;
}

export interface LimitGas {
  gas: GasKey;
  label: string;
  hazard: string;
  inert: boolean;
  device_limit: number | null;
  usage_limit: number | null;
  policy_value: number | null;
  available: boolean;
}

export interface LimitsState {
  policy: { version: number; limits: Flows; reason: string; actor: string; created_at: string };
  gases: LimitGas[];
  locked: string | null;
  history: { version: number; limits: Flows; reason: string; actor: string; created_at: string }[];
  applied?: { version: number; affected: LimitAffected[] };
}

export interface LimitAffected {
  recipe_id: number;
  name: string;
  version: number;
  summary: string;
}

export interface LimitsPreview {
  changes: { gas: GasKey; label: string; before: number; after: number }[];
  affected: LimitAffected[];
  next_version: number;
  locked: string | null;
}

export interface Overview {
  run: Pick<RunState, 'status' | 'experiment' | 'status_text' | 'current_step_no' | 'total_steps' | 'elapsed_s' | 'live'
    | 'purge' | 'end_reason' | 'end_reason_text' | 'steps' | 'stale_devices' | 'emergency'>;
  events: RunEvent[];
  pending_review: ExperimentSummary[];
  pending_alarms: PendingAlarm[];
  blocked_recipes: { id: number; name: string; version: number; summary: string }[];
  recipe_count: number;
  limits_version: number;
  counts: Record<ExperimentCategory, number>;
  recent: ExperimentSummary[];
  simulation_mode: boolean;
}

export interface Rules {
  alarm_rules: { code: string; name: string; condition: string; level: string; action: string }[];
  process_gases: Record<ExperimentType, GasKey[]>;
  inert_gases: GasKey[];
  checklist: { key: string; label: string; detail: string }[];
  safe_temperature_c: number;
  stale_warning_seconds: number;
  poll_interval_ms: number;
}

export type TaskStatus = 'queued' | 'running' | 'cancelling' | 'completed' | 'failed' | 'cancelled';

export interface Task {
  id: string;
  kind: string;
  status: TaskStatus;
  phase: string;
  progress: number;
  input: Record<string, unknown>;
  result: { path?: string; filename?: string; [key: string]: unknown } | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface AppConfig {
  app_name: string;
  db_path: string;
  simulation_mode: boolean;
  device_backend: 'multi_device' | 'plc_modbus';
  mapping_profile: string;
  temperature_mode: 'program' | 'setpoint';
  default_gas_mode: 'auto' | 'manual';
  poll_interval_ms: number;
  acquisition_batch_size: number;
  step_heatup_grace_seconds: number;
  step_total_grace_seconds: number;
  degraded_fault_seconds: number;
  purge_exit_temperature_c: number;
  plc_serial_port: string;
  plc_baudrate: number;
  plc_unit_id: number;
  temp_port: string;
  temp_slave_id: number;
  temp_baudrate: number;
  temp_program_group: number;
  temp_segment_time_unit: 'min' | 's';
  mfc_port: string;
  mfc_baudrate: number;
  mfc_channels: { address: number; gas: string; full_scale_lpm: number }[];
  balance_port: string;
  balance_protocol: 'gs_cpa' | 'longteng';
  balance_baudrate: number;
  audit_log_limit: number;
  log_max_bytes: number;
  log_backup_count: number;
}

export interface SettingsResponse {
  config: AppConfig;
  restart_required: boolean;
  restart_required_keys?: string[];
  changed?: string[];
}
