import { request } from './client';
import type {
  AlarmRecord, AppConfig, AuditRecord, DeviceDescription, DeviceStatus, ExperimentDetail, ExperimentSummary,
  Health, KineticsResult, MeasurementPoint, Recipe, RecipeDocument, RecipeStep, RecipeSummary, RunState,
  SampleParams, SettingsResponse, Task,
} from './types';

export const health = () => request<Health>('GET', '/api/health');
export const getSettings = () => request<SettingsResponse>('GET', '/api/settings');
export const putSettings = (updates: Partial<AppConfig>) => request<SettingsResponse>('PUT', '/api/settings', updates);

export const listRecipes = async () => (await request<{ recipes: RecipeSummary[] }>('GET', '/api/recipes')).recipes;
export const getRecipe = async (id: number) => (await request<{ recipe: Recipe }>('GET', `/api/recipes/${id}`)).recipe;
export const createRecipe = async (name: string, steps: Partial<RecipeStep>[]) =>
  (await request<{ recipe: Recipe }>('POST', '/api/recipes', { name, steps })).recipe;
export const updateRecipe = async (id: number, name: string, steps: Partial<RecipeStep>[]) =>
  (await request<{ recipe: Recipe }>('PUT', `/api/recipes/${id}`, { name, steps })).recipe;
export const deleteRecipe = (id: number) => request<{ ok: boolean }>('DELETE', `/api/recipes/${id}`);
export const exportRecipe = async (id: number) => (await request<{ document: RecipeDocument }>('GET', `/api/recipes/${id}/export`)).document;
export const importRecipe = async (document: unknown, name?: string) =>
  (await request<{ recipe: Recipe }>('POST', '/api/recipes/import', { document, name })).recipe;

export const runState = () => request<RunState>('GET', '/api/run');
export const runMeasurements = (since: number) =>
  request<{ seq: number; items: MeasurementPoint[] }>('GET', `/api/run/measurements?since=${since}`);
export const startRun = (recipe_id: number, gas_mode?: 'auto' | 'manual') => request<RunState>('POST', '/api/run/start', { recipe_id, gas_mode });
export const pauseRun = () => request<RunState>('POST', '/api/run/pause', {});
export const resumeRun = () => request<RunState>('POST', '/api/run/resume', {});
export const stopRun = () => request<RunState>('POST', '/api/run/stop', {});
export const ackAlarm = () => request<RunState>('POST', '/api/run/ack-alarm', {});
export const resetInterlock = () => request<RunState>('POST', '/api/run/reset-interlock', { confirm: true });
export const setGasMode = (mode: 'auto' | 'manual', confirm: boolean) => request<RunState>('POST', '/api/run/gas-mode', { mode, confirm });
export const setManualGas = (values: { n2_lpm: number; h2_lpm: number; co_lpm: number }) =>
  request<RunState>('POST', '/api/run/manual-gas', { ...values, confirm: true });

export const describeDevices = () => request<DeviceDescription>('GET', '/api/devices');
export const deviceStatus = () => request<DeviceStatus>('GET', '/api/devices/status');
export const connectDevices = () => request<{ connected: boolean }>('POST', '/api/devices/connect', {});
export const setMfcSetpoints = (setpoints: { address: number; lpm: number }[]) =>
  request<DeviceStatus>('POST', '/api/devices/mfc', { setpoints, confirm: true });
export const setDeviceTemperature = (celsius: number) => request<DeviceStatus>('POST', '/api/devices/temperature', { celsius, confirm: true });
export const tareBalance = () => request<DeviceStatus & { ok: boolean }>('POST', '/api/devices/tare', { confirm: true });

export const listExperiments = async (limit = 200) =>
  (await request<{ experiments: ExperimentSummary[] }>('GET', `/api/experiments?limit=${limit}`)).experiments;
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
export const startReport = async (id: number, params?: SampleParams) =>
  (await request<{ task: Task }>('POST', `/api/experiments/${id}/report`, params ?? {})).task;
export const startExport = async (id: number, kind: 'measurements_csv' | 'measurements_xlsx' | 'summary_csv') =>
  (await request<{ task: Task }>('POST', `/api/experiments/${id}/export`, { kind })).task;

export const listAlarms = async (experimentId?: number, limit = 200) =>
  (await request<{ alarms: AlarmRecord[] }>('GET', `/api/alarms?limit=${limit}${experimentId ? `&experiment_id=${experimentId}` : ''}`)).alarms;
export const listAudit = async (limit = 300) => (await request<{ logs: AuditRecord[] }>('GET', `/api/audit?limit=${limit}`)).logs;
export const listTasks = async (limit = 20) => (await request<{ tasks: Task[] }>('GET', `/api/tasks?limit=${limit}`)).tasks;
export const getTask = async (id: string) => (await request<{ task: Task }>('GET', `/api/tasks/${id}`)).task;
export const cancelTask = async (id: string) => (await request<{ task: Task }>('POST', `/api/tasks/${id}/cancel`, {})).task;
export const backendLog = () => request<{ filename: string; path: string; content: string }>('GET', '/api/log');
