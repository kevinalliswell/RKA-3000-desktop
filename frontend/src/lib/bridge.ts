import { invoke, isTauri } from '@tauri-apps/api/core'

export interface DeviceValues {
  temperature_c: number
  weight_g: number
  pressure_mpa: number
  n2_lpm: number
  h2_lpm: number
  co_lpm: number
  alarm_word: number
  interlock_word: number
  run_control_word: number
  estop_status: number
}

export interface Snapshot {
  sampled_at: string
  quality: 'simulated'
  values: DeviceValues
}

export interface RecipeSummary {
  id: number
  name: string
  created_at?: string
  updated_at?: string
}

export interface ExperimentSummary {
  id: number
  name: string
  status: string
  recipe_name?: string | null
  started_at: string
  finished_at?: string | null
}

export interface Bootstrap {
  version: string
  mode: 'simulation'
  recipes: RecipeSummary[]
  experiments: ExperimentSummary[]
  snapshot: Snapshot
}

export interface RecipeStep {
  step_no: number
  target_temp_c: number
  ramp_rate_cpm: number
  hold_seconds: number
  n2_lpm: number
  h2_lpm: number
  co_lpm: number
  notes: string | null
}

export interface RecipeDetail {
  item: RecipeSummary
  steps: RecipeStep[]
}

export interface ExperimentDetail {
  item: ExperimentSummary & {
    initial_mass_g?: number | null
    tfe_pct?: number | null
    feo_pct?: number | null
  }
  summary: { sample_count: number; first_sampled_at: string; last_sampled_at: string } | null
  alarms: { id: number; code: string; level: string; message: string; created_at: string }[]
}

export async function callBackend<T>(method: string, params: Record<string, unknown> = {}): Promise<T> {
  if (!isTauri()) {
    throw new Error('请在 RKA-3000 桌面窗口中查看实时仿真状态')
  }
  return invoke<T>('bridge_call', { method, params })
}
