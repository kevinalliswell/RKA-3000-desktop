import { callBackend } from './bridge'

export type Page = 'overview' | 'preflight' | 'current' | 'recipes' | 'history' | 'alarms' | 'devices' | 'audit' | 'analysis' | 'reports' | 'settings' | 'help'
export type Gas = 'n2' | 'ar' | 'co' | 'co2' | 'h2' | 'ch4' | 'o2'
export const gases: Gas[] = ['n2', 'ar', 'co', 'co2', 'h2', 'ch4', 'o2']
export const gasLabels: Record<Gas, string> = { n2: 'N₂', ar: 'Ar', co: 'CO', co2: 'CO₂', h2: 'H₂', ch4: 'CH₄', o2: 'O₂' }
export const gasChannels: Record<Gas, string> = { n2: 'MFC-01', ar: 'MFC-01', co: 'MFC-02', co2: 'MFC-03', h2: 'MFC-04', ch4: 'MFC-05', o2: 'MFC-06' }
export const stateLabels: Record<string, string> = { PURGE: '惰性置换', REACTION: '反应测定', COOLING: '吹扫冷却', PAUSED: '已暂停', REVIEW: '待复核', REVIEWED: '已复核', ARCHIVED: '已归档', EMERGENCY: '紧急处置', RECOVERY_REQUIRED: '重启待复核' }
export type Stage = { name: string; duration_s: number; temperature_c: number; flows: Record<Gas, number> }
export type Recipe = { id: number; name: string; kind: 'reduction' | 'oxidation'; version: number; stages?: Stage[]; created_at?: string }
export type Run = { id: number; name: string; state: string; sample: { name: string; initial_mass_g: number }; recipe_snapshot: Recipe; stage_index: number; stage_elapsed: number; started_at: string; finished_at: string | null; review_note: string; source: string }
export type Sample = { id: number; sampled_at: string; elapsed_s: number; temperature_c: number | null; weight_g: number | null; flows: Record<Gas, number>; quality: string; reason: string }
export type Snapshot = { mode: 'simulation'; state: 'simulated' | 'offline' | 'stale' | 'unknown'; reason: string; sampled_at: string | null; values: { temperature_c: number; weight_g: number; flows: Record<Gas, number> } | null; run: Run | null }
export type Alarm = { id: number; run_id: number | null; code: string; severity: string; message: string; appeared_at: string; acknowledged_at: string | null; acknowledged_by: string | null; cleared_at: string | null }
export type Audit = { id: number; run_id: number | null; actor: string; action: string; detail: string; created_at: string }
export type LegacyRun = { id: number; name: string; status: string; started_at?: string; finished_at?: string; source_hash: string; sample_count: number; alarms: Record<string, unknown>[] }
export type LegacyRecipe = { id: number; name: string; source_hash: string; steps: Record<string, unknown>[] }
export type LegacyAudit = { id: number; actor: string; action: string; detail?: string; created_at: string; source_hash: string }
export type Settings = { limits: Record<Gas, number>; role: string; scenario: string; mode: string; hardware_writes: boolean }

export const fmt = (value: string | null | undefined) => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'
export const num = (value: number | null | undefined, digits = 2) => typeof value === 'number' ? value.toFixed(digits) : '—'

class Workspace {
  page = $state<Page>('overview')
  tab = $state(0)
  busy = $state(false)
  error = $state('')
  notice = $state('')
  now = $state(Date.now())
  version = $state('0.7.0')
  settings = $state<Settings | null>(null)
  recipes = $state<Recipe[]>([])
  history = $state<Run[]>([])
  historyTotal = $state(0)
  snapshot = $state<Snapshot | null>(null)
  alarms = $state<Alarm[]>([])
  audit = $state<Audit[]>([])
  devices = $state<{checked_at:string;recheck_seconds:number;devices:{id:string;protocol:string;mode:string;real_state:string;last_valid_at:string|null;reason:string}[]} | null>(null)
  legacyRuns = $state<LegacyRun[]>([])
  legacyRecipes = $state<LegacyRecipe[]>([])
  legacyAudit = $state<LegacyAudit[]>([])
  selectedRun = $state<Run | null>(null)
  selectedEvents = $state<{alarms:Alarm[];audit:Audit[]}>({alarms:[],audit:[]})
  selectedRecipe = $state<Recipe | null>(null)
  samples = $state<Sample[]>([])
  chartSamples = $state<Sample[]>([])
  sampleTotal = $state(0)
  sampleOffset = $state(0)
  sampleStride = $state(1)

  get fresh() {
    return this.snapshot?.state === 'simulated' && !!this.snapshot.values && !!this.snapshot.sampled_at &&
      this.now - Date.parse(this.snapshot.sampled_at) < 8000
  }
  get run() { return this.snapshot?.run ?? null }

  navigate(page: Page, tab = 0) {
    this.page = page
    this.tab = tab
    window.location.hash = page
  }

  async request<T>(method: string, params: Record<string, unknown> = {}): Promise<T> {
    this.busy = true
    try {
      const result = await callBackend<T>(method, params)
      this.error = ''
      return result
    } catch (cause) {
      this.error = cause instanceof Error ? cause.message : String(cause)
      throw cause
    } finally {
      this.busy = false
    }
  }

  async load() {
    try {
      const previousRunId = this.snapshot?.run?.id
      const data = await this.request<{version: string; settings: Settings; recipes: Recipe[]; history: {items: Run[]; total: number}; snapshot: Snapshot; alarms: Alarm[]; audit: Audit[]}>('sim_bootstrap')
      this.version = data.version
      this.settings = data.settings
      this.recipes = data.recipes
      this.history = data.history.items
      this.historyTotal = data.history.total
      this.snapshot = data.snapshot
      if (previousRunId !== data.snapshot.run?.id) { this.samples = []; this.sampleTotal = 0 }
      this.alarms = data.alarms
      this.audit = data.audit
      this.now = Date.now()
    } catch { /* visible error is set by request */ }
  }

  async poll() {
    if (this.busy) return
    try {
      this.snapshot = await callBackend<Snapshot>('sim_snapshot')
      this.now = Date.now()
      if ((this.page === 'current' || this.page === 'overview') && this.run) await this.loadRecentSamples(this.run.id)
    } catch (cause) {
      this.now = Date.now()
      this.error = cause instanceof Error ? cause.message : String(cause)
    }
  }

  async loadRecipe(id: number) {
    try { this.selectedRecipe = await this.request<Recipe>('sim_recipe', { id }) } catch { /* shown */ }
  }

  async loadLegacy() {
    try {
      this.legacyRuns = (await this.request<{items:LegacyRun[]}>('sim_legacy_runs')).items
      this.legacyRecipes = (await this.request<{items:LegacyRecipe[]}>('sim_legacy_recipes')).items
      this.legacyAudit = (await this.request<{items:LegacyAudit[]}>('sim_legacy_audit')).items
    } catch { /* shown */ }
  }

  async loadRun(id: number) {
    try {
      this.chartSamples = []
      this.selectedRun = await this.request<Run>('sim_run', { id })
      this.selectedEvents = await this.request('sim_run_events', { id })
      await this.loadSamples(id)
      if (this.sampleTotal > 300) {
        this.chartSamples = (await callBackend<{items:Sample[]}>('sim_samples', { id, limit: 300, stride: Math.ceil(this.sampleTotal / 300) })).items
      } else {
        this.chartSamples = this.samples
      }
    } catch { /* shown */ }
  }

  async loadSamples(id: number, reset = true) {
    if (reset) this.sampleOffset = 0
    try {
      const result = await callBackend<{items: Sample[]; total: number}>('sim_samples', { id, limit: 300, offset: this.sampleOffset, stride: this.sampleStride })
      this.samples = result.items
      this.sampleTotal = result.total
    } catch (cause) { this.error = cause instanceof Error ? cause.message : String(cause) }
  }

  async loadRecentSamples(id: number) {
    try {
      const result = await callBackend<{items: Sample[]; total: number}>('sim_samples', { id, limit: 300, tail: true })
      this.samples = result.items
      this.sampleTotal = result.total
    } catch (cause) { this.error = cause instanceof Error ? cause.message : String(cause) }
  }

  async loadDevices() {
    try { this.devices = await callBackend('sim_devices_status') } catch (cause) { this.error = cause instanceof Error ? cause.message : String(cause) }
  }

  async action(id: number, action: string, note = '') {
    try {
      await this.request<Run>('sim_run_action', { id, action, note })
      this.notice = `操作已记录：${action}`
      await this.load()
      if (this.selectedRun?.id === id) await this.loadRun(id)
    } catch { /* shown */ }
  }
}

export const ws = new Workspace()
