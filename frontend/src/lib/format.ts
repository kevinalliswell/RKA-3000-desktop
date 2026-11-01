import type { ExperimentCategory, GasKey, RunStatus, TaskStatus } from './api/types';

/** Missing or stale values are always shown as "—", never as an old value or 0. */
export const DASH = '—';

export function fmt(value: number | null | undefined, digits = 2, fallback = DASH): string {
  if (value === null || value === undefined || Number.isNaN(value)) return fallback;
  return value.toFixed(digits);
}
export const fmtFlow = (v: number | null | undefined) => fmt(v, 2);
export const fmtTemp = (v: number | null | undefined) => fmt(v, 1);
export const fmtMass = (v: number | null | undefined) => fmt(v, 3);
export const fmtPct = (v: number | null | undefined) => fmt(v, 1);

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString('zh-CN', { hour12: false });
}

export function fmtShort(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function fmtClock(iso: string | null | undefined): string {
  if (!iso) return DASH;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleTimeString('zh-CN', { hour12: false });
}

/** hh:mm:ss */
export function fmtDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return DASH;
  const s = Math.max(0, Math.round(seconds));
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${pad(Math.floor(s / 3600))}:${pad(Math.floor((s % 3600) / 60))}:${pad(s % 60)}`;
}

/** mm:ss for step timers. */
export function fmtMinSec(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return DASH;
  const s = Math.max(0, Math.round(seconds));
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
}

export function durationBetween(start: string | null | undefined, end: string | null | undefined): string {
  if (!start || !end) return DASH;
  return fmtDuration((new Date(end).getTime() - new Date(start).getTime()) / 1000);
}

export const GAS_LABEL: Record<GasKey, string> = { N2: 'N₂', AR: 'Ar', H2: 'H₂', CO: 'CO', CO2: 'CO₂', CH4: 'CH₄', O2: 'O₂' };
export const GAS_COLUMN: Record<GasKey, string> = {
  N2: 'n2_lpm', AR: 'ar_lpm', H2: 'h2_lpm', CO: 'co_lpm', CO2: 'co2_lpm', CH4: 'ch4_lpm', O2: 'o2_lpm',
};
export const GAS_KEYS: GasKey[] = ['N2', 'AR', 'H2', 'CO', 'CO2', 'CH4', 'O2'];
export const PROCESS_GASES: Record<'reduction' | 'oxidation', GasKey[]> = {
  reduction: ['CO', 'CO2', 'H2', 'CH4'],
  oxidation: ['CO2', 'O2'],
};

export function flowsText(flows: Partial<Record<GasKey, number>> | null | undefined): string {
  if (!flows) return DASH;
  const parts = GAS_KEYS.filter((g) => (flows[g] ?? 0) > 0).map((g) => `${GAS_LABEL[g]} ${fmtFlow(flows[g])}`);
  return parts.length ? parts.join(' / ') : '全部关闭';
}

export function stepFlows(step: object): Partial<Record<GasKey, number>> {
  const out: Partial<Record<GasKey, number>> = {};
  const values = step as Record<string, unknown>;
  for (const gas of GAS_KEYS) out[gas] = Number(values[GAS_COLUMN[gas]] ?? 0);
  return out;
}

export const TYPE_LABEL = { reduction: '还原实验', oxidation: '氧化实验' } as const;
export const TYPE_SHORT = { reduction: '还原', oxidation: '氧化' } as const;
export const TYPE_TONE = { reduction: 'tred', oxidation: 'tox' } as const;

export const runStatusLabel: Record<RunStatus, string> = {
  idle: '待机', starting: '启动中', running: '运行中', paused: '已暂停', interrupted: '联锁中断', purging: '惰性处置',
  stopping: '正在收尾', stopped: '已中止 · 待核查', completed: '完成 · 待核查', faulted: '故障 · 待核查',
};

export const runStatusTone: Record<RunStatus, Tone> = {
  idle: '', starting: 'dark', running: 'dark', paused: 'warn', interrupted: 'danger', purging: 'danger',
  stopping: 'warn', stopped: 'warn', completed: 'good', faulted: 'danger',
};

export type Tone = '' | 'good' | 'warn' | 'danger' | 'dark' | 'tred' | 'tox';

export const categoryLabel: Record<ExperimentCategory, string> = {
  running: '运行中', pending: '待核查', archived: '已归档', aborted: '已中止',
};
export const categoryTone: Record<ExperimentCategory, Tone> = {
  running: 'dark', pending: 'warn', archived: 'good', aborted: 'danger',
};

export const END_REASON: Record<string, string> = {
  completed: '配方最后一段正常完成', operator_stop: '操作者提前结束', emergency: '紧急停气', alarm: '报警自动处置',
  fault: '设备或执行故障', shutdown: '程序关闭时中止', recovered: '程序异常退出后标记中止',
};

export const taskStatusLabel: Record<TaskStatus, string> = {
  queued: '排队中', running: '执行中', cancelling: '取消中', completed: '已完成', failed: '失败', cancelled: '已取消',
};

/** Audit result codes → label and tone, in the order they happen. */
export const RESULT_CODES: Record<string, { label: string; tone: Tone }> = {
  accepted: { label: '已受理', tone: 'good' },
  verified: { label: '回读一致', tone: 'good' },
  verify_na: { label: '回读不适用', tone: '' },
  mismatch: { label: '回读不一致', tone: 'danger' },
  reverted: { label: '已回退', tone: 'warn' },
  applied: { label: '已生效', tone: 'good' },
  failed: { label: '失败', tone: 'danger' },
  recorded: { label: '已记录', tone: '' },
};

export const AUDIT_CATEGORY: Record<string, string> = {
  control: '控制命令', safety: '安全与报警', config: '配置变更', data: '数据与归档', system: '系统',
};

export const ACTION_LABEL: Record<string, string> = {
  EXPERIMENT_START: '启动实验', EXPERIMENT_STOP: '提前结束', EMERGENCY_STOP: '紧急停气', EXPERIMENT_END: '实验结束',
  PURGE_START: '进入惰性处置', ALARM_DISPOSAL: '报警自动处置', FAULT_DISPOSAL: '故障处置', SHUTDOWN_DISPOSAL: '关闭时处置',
  STEP_CHANGE: '阶段切换', GAS_MODE_SWITCH: '切换配气模式', MANUAL_GAS_SET: '手动调气', MANUAL_GAS_FAILED: '手动调气失败',
  TEMPERATURE_PROGRAM_DOWNLOADED: '下发温度程序', TEMPERATURE_PROGRAM_FAILED: '温度程序下发失败', ALARM_RAISED: '报警触发',
  ALARM_ACK: '确认报警', EXPERIMENT_ARCHIVE: '归档', RECIPE_CREATE: '新建配方', RECIPE_UPDATE: '保存配方',
  RECIPE_DELETE: '删除配方', RECIPE_IMPORT: '导入配方', LIMITS_UPDATE: '修改使用上限', SAMPLE_PARAMS_SAVE: '保存试样参数',
  REPORT_EXPORT: '生成报告', EXPORT_CSV: '导出 CSV', EXPORT_EXCEL: '导出 Excel', EXPORT_SUMMARY_CSV: '导出摘要',
  EXPORT_AUDIT_CSV: '导出审计', EXPERIMENT_RENAME: '重命名实验', EXPERIMENT_DELETE: '删除实验', EXPERIMENT_PAUSE: '暂停',
  EXPERIMENT_RESUME: '恢复', EXPERIMENT_INTERRUPTED: '联锁中断', INTERLOCK_RESET: '联锁复位', DEVICE_CONNECT: '连接设备',
  MANUAL_MFC_SET: '设备页设定流量', MANUAL_TEMPERATURE_SET: '设备页设定温度', BALANCE_TARE: '天平去皮',
  ACQUISITION_FAILED: '采集失败', SETPOINT_APPLY_FAILED: '设定下发失败',
};

export const DEVICE_LABEL: Record<string, string> = { temp: '温控器', mfc: 'MFC 总线', balance: '电子天平', plc: 'PLC' };

export function downloadText(name: string, text: string, type = 'application/json'): void {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
