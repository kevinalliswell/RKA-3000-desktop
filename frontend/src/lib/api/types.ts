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

export interface RecipeStep {
  step_no: number;
  target_temp_c: number;
  ramp_rate_cpm: number;
  hold_seconds: number;
  n2_lpm: number;
  h2_lpm: number;
  co_lpm: number;
  notes: string;
}

export interface RecipeSummary {
  id: number;
  name: string;
  updated_at: string;
}

export interface Recipe extends RecipeSummary {
  created_at?: string;
  steps: RecipeStep[];
}

export interface RecipeDocument {
  format: 'rka3000-recipe';
  version: 1;
  name: string;
  steps: RecipeStep[];
}

export type RunStatus =
  | 'idle' | 'starting' | 'running' | 'paused' | 'interrupted' | 'stopping' | 'stopped' | 'completed' | 'faulted';

export interface RunAllowed {
  start: boolean;
  pause: boolean;
  resume: boolean;
  stop: boolean;
  ack_alarm: boolean;
  reset_interlock: boolean;
  set_gas_mode: boolean;
  manual_gas: boolean;
}

export interface Snapshot {
  temperature_c: number;
  weight_g: number;
  pressure_mpa: number;
  n2_lpm: number;
  h2_lpm: number;
  co_lpm: number;
  alarm_word: number;
  interlock_word: number;
  run_control_word: number;
  estop_status: number;
}

export interface PendingAlarm {
  id: number;
  code: string;
  level: string;
  message: string;
  created_at: string;
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
  error: string | null;
  current_step_no: number | null;
  total_steps: number;
  current_step: RecipeStep | null;
  status_text: string;
  setpoints_text: string;
  gas_mode: 'auto' | 'manual';
  temperature_mode: 'program' | 'setpoint';
  temperature_program: { group: number; segments: number; message: string; remote_start: boolean } | null;
  manual_gas: { n2_lpm: number; h2_lpm: number; co_lpm: number } | null;
  alarm: { word: number; text: string; active: { code: string; level: string; message: string; interlock: boolean }[] };
  interlock: { word: number; text: string; estop: boolean; resettable: boolean; active: { code: string; message: string; resettable: boolean }[] };
  control_feedback: { word: number; estop_status: number; consistent: boolean; message: string };
  pending_alarms: PendingAlarm[];
  degraded_devices: string[];
  latest: Snapshot | null;
  allowed: RunAllowed;
  connected: boolean;
  messages: { at: string; text: string }[];
}

export interface MeasurementPoint {
  seq?: number;
  id?: number;
  sampled_at: string;
  temperature_c: number;
  weight_g: number;
  pressure_mpa: number;
  n2_lpm: number;
  h2_lpm: number;
  co_lpm: number;
}

export interface DeviceDescription {
  backend: string;
  simulation: boolean;
  summary: string;
  devices: { name: string; label: string; port?: string }[];
  mfc_channels: { address: number; gas: string; full_scale_lpm: number; role: string | null }[];
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

export interface ExperimentSummary {
  id: number;
  name: string;
  status: string;
  recipe_id: number | null;
  recipe_name: string | null;
  started_at: string;
  finished_at: string | null;
}

export interface ExperimentDetail extends ExperimentSummary {
  initial_mass_g: number | null;
  tfe_pct: number | null;
  feo_pct: number | null;
  summary: {
    sample_count: number; first_sampled_at: string; last_sampled_at: string;
    min_temperature_c: number; max_temperature_c: number; min_weight_g: number; max_weight_g: number;
  } | null;
  measurement_count: number;
}

export interface SampleParams {
  initial_mass_g: number | null;
  tfe_pct: number | null;
  feo_pct: number | null;
}

export interface KineticsResult {
  experiment_id: number;
  params: { initial_mass_g: number; tfe_pct: number; feo_pct: number };
  points: { t_min: number; reduction_degree_pct: number; rate_pct_per_min: number }[];
  final_degree_pct: number;
  time_to_40_min: number | null;
  time_to_60_min: number | null;
  rate_at_40_pct: number | null;
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

export interface AlarmRecord {
  id: number;
  experiment_id: number | null;
  code: string;
  level: string;
  message: string;
  created_at: string;
  acknowledged_at: string | null;
  acknowledged_by: string | null;
}

export interface AuditRecord {
  id: number;
  actor: string;
  action: string;
  detail: string;
  created_at: string;
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
