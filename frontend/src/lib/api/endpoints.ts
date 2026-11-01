import { request } from './client';
import type {
  AlarmRecord, AppConfig, AuditRecord, CompareRow, DeviceDescription, DeviceStatus, ExperimentCategory, ExperimentDetail,
  ExperimentList, Flows, Health, KineticsResult, LimitsPreview, LimitsState, MeasurementPoint, Overview, PreflightResult,
  Recipe, RecipeDocument, RecipeMeta, RecipeStep, RecipeSummary, RecipeVersion, ReportItem, ReviewResult, Rules, RunState,
  SampleParams, SettingsResponse, StartRequest, Task,
} from './types';

export const health = () => request<Health>('GET', '/api/health');
export const getSettings = () => request<SettingsResponse>('GET', '/api/settings');
export const putSettings = (updates: Partial<AppConfig>) => request<SettingsResponse>('PUT', '/api/settings', updates);
export const overview = () => request<Overview>('GET', '/api/overview');
export const rules = () => request<Rules>('GET', '/api/rules');

export interface RecipePayload extends Partial<RecipeMeta> {
  name: string;
  steps: Partial<RecipeStep>[];
  reason?: string;
  operator?: string;
}

export const listRecipes = async () => (await request<{ recipes: RecipeSummary[] }>('GET', '/api/recipes')).recipes;
export const getRecipe = async (id: number) => (await request<{ recipe: Recipe }>('GET', `/api/recipes/${id}`)).recipe;
export const createRecipe = async (payload: RecipePayload) =>
  (await request<{ recipe: Recipe }>('POST', '/api/recipes', payload)).recipe;
export const updateRecipe = async (id: number, payload: RecipePayload) =>
  (await request<{ recipe: Recipe }>('PUT', `/api/recipes/${id}`, payload)).recipe;
export const deleteRecipe = (id: number, operator?: string) => request<{ ok: boolean }>('DELETE', `/api/recipes/${id}`, { operator });
export const exportRecipe = async (id: number) => (await request<{ document: RecipeDocument }>('GET', `/api/recipes/${id}/export`)).document;
export const recipeVersions = async (id: number) =>
  (await request<{ versions: (RecipeVersion & { snapshot: unknown })[] }>('GET', `/api/recipes/${id}/versions`)).versions;
export const importRecipe = async (document: unknown, name?: string, operator?: string) =>
  (await request<{ recipe: Recipe }>('POST', '/api/recipes/import', { document, name, operator })).recipe;

export const getLimits = () => request<LimitsState>('GET', '/api/limits');
export const previewLimits = (limits: Flows) => request<LimitsPreview>('POST', '/api/limits/preview', { limits });
export const applyLimits = (limits: Flows, reason: string, operator?: string) =>
  request<LimitsState>('PUT', '/api/limits', { limits, reason, operator });

export const runState = () => request<RunState>('GET', '/api/run');
export const runMeasurements = (since: number) =>
  request<{ seq: number; items: MeasurementPoint[] }>('GET', `/api/run/measurements?since=${since}`);
export const preflight = (payload: Partial<StartRequest>) => request<PreflightResult>('POST', '/api/run/preflight', payload);
export const startRun = (payload: StartRequest) => request<RunState>('POST', '/api/run/start', payload);
export const pauseRun = () => request<RunState>('POST', '/api/run/pause', {});
export const resumeRun = () => request<RunState>('POST', '/api/run/resume', {});
export const stopRun = (reason: string) => request<RunState>('POST', '/api/run/stop', { confirm: true, reason });
export const emergencyStop = () => request<RunState>('POST', '/api/run/emergency', {});
export const ackAlarm = (id: number, note: string, operator?: string) =>
  request<RunState>('POST', `/api/alarms/${id}/ack`, { note, operator });
export const resetInterlock = () => request<RunState>('POST', '/api/run/reset-interlock', { confirm: true });
export const setGasMode = (mode: 'auto' | 'manual', confirm: boolean) => request<RunState>('POST', '/api/run/gas-mode', { mode, confirm });
export const setManualGas = (flows: Flows, reason: string) =>
  request<RunState>('POST', '/api/run/manual-gas', { flows, reason, confirm: true });

export const describeDevices = () => request<DeviceDescription>('GET', '/api/devices');
export const deviceStatus = () => request<DeviceStatus>('GET', '/api/devices/status');
export const connectDevices = () => request<{ connected: boolean }>('POST', '/api/devices/connect', {});
export const setMfcSetpoints = (setpoints: { address: number; lpm: number }[]) =>
  request<DeviceStatus>('POST', '/api/devices/mfc', { setpoints, confirm: true });
export const setDeviceTemperature = (celsius: number) => request<DeviceStatus>('POST', '/api/devices/temperature', { celsius, confirm: true });
export const tareBalance = () => request<DeviceStatus & { ok: boolean }>('POST', '/api/devices/tare', { confirm: true });

export const listExperiments = (options: { limit?: number; category?: ExperimentCategory | null; q?: string } = {}) => {
  const params = new URLSearchParams({ limit: String(options.limit ?? 200) });
  if (options.category) params.set('category', options.category);
  if (options.q) params.set('q', options.q);
  return request<ExperimentList>('GET', `/api/experiments?${params.toString()}`);
};
export const getExperiment = async (id: number) => (await request<{ experiment: ExperimentDetail }>('GET', `/api/experiments/${id}`)).experiment;
export const renameExperiment = async (id: number, name: string) =>
  (await request<{ experiment: ExperimentDetail }>('PATCH', `/api/experiments/${id}`, { name })).experiment;
export const deleteExperiment = (id: number) => request<{ ok: boolean }>('DELETE', `/api/experiments/${id}`, { confirm: true });
export const experimentMeasurements = (id: number, limit: number, offset: number) =>
  request<{ items: MeasurementPoint[]; total: number; limit: number; offset: number }>(
    'GET', `/api/experiments/${id}/measurements?limit=${limit}&offset=${offset}`);
export const getSampleParams = (id: number) => request<SampleParams>('GET', `/api/experiments/${id}/sample-params`);
export const putSampleParams = (id: number, params: SampleParams) => request<SampleParams>('PUT', `/api/experiments/${id}/sample-params`, params);
export const computeKinetics = (id: number, params?: SampleParams) => request<KineticsResult>('POST', `/api/experiments/${id}/kinetics`, params ?? {});
export const reviewExperiment = (id: number) => request<ReviewResult>('GET', `/api/experiments/${id}/review`);
export const archiveExperiment = (id: number, note: string, operator?: string) =>
  request<ReviewResult>('POST', `/api/experiments/${id}/archive`, { confirm: true, note, operator });
export const compareExperiment = async (id: number) => (await request<{ items: CompareRow[] }>('GET', `/api/experiments/${id}/compare`)).items;
export const startReport = async (id: number, operator?: string) =>
  (await request<{ task: Task }>('POST', `/api/experiments/${id}/report`, { operator })).task;
export const listReports = async () => (await request<{ items: ReportItem[] }>('GET', '/api/reports')).items;
export const startExport = async (id: number, kind: 'measurements_csv' | 'measurements_xlsx' | 'summary_csv') =>
  (await request<{ task: Task }>('POST', `/api/experiments/${id}/export`, { kind })).task;

export const listAlarms = async (options: { experimentId?: number; state?: 'pending' | 'acked'; limit?: number } = {}) => {
  const params = new URLSearchParams({ limit: String(options.limit ?? 200) });
  if (options.experimentId) params.set('experiment_id', String(options.experimentId));
  if (options.state) params.set('state', options.state);
  return (await request<{ alarms: AlarmRecord[] }>('GET', `/api/alarms?${params.toString()}`)).alarms;
};
export const listAudit = async (options: { limit?: number; experimentId?: number | null; category?: string | null; actor?: string } = {}) => {
  const params = new URLSearchParams({ limit: String(options.limit ?? 300) });
  if (options.experimentId) params.set('experiment_id', String(options.experimentId));
  if (options.category) params.set('category', options.category);
  if (options.actor) params.set('actor', options.actor);
  return (await request<{ logs: AuditRecord[] }>('GET', `/api/audit?${params.toString()}`)).logs;
};
export const exportAudit = async (experimentId?: number | null, category?: string | null) =>
  (await request<{ task: Task }>('POST', '/api/audit/export', { experiment_id: experimentId ?? null, category: category ?? null })).task;
export const listTasks = async (limit = 20) => (await request<{ tasks: Task[] }>('GET', `/api/tasks?limit=${limit}`)).tasks;
export const getTask = async (id: string) => (await request<{ task: Task }>('GET', `/api/tasks/${id}`)).task;
export const cancelTask = async (id: string) => (await request<{ task: Task }>('POST', `/api/tasks/${id}/cancel`, {})).task;
export const backendLog = () => request<{ filename: string; path: string; content: string }>('GET', '/api/log');
