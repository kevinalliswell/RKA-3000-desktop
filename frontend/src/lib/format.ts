import type { RunStatus, TaskStatus } from './api/types';

export const runStatusLabel: Record<RunStatus, string> = {
  idle: '未启动', starting: '启动中', running: '运行中', paused: '已暂停', interrupted: '联锁中断',
  stopping: '正在收尾', stopped: '已停止', completed: '已完成', faulted: '故障停止',
};

export const runStatusTone: Record<RunStatus, 'neutral' | 'ok' | 'warn' | 'danger' | 'busy' | 'info'> = {
  idle: 'neutral', starting: 'busy', running: 'busy', paused: 'warn', interrupted: 'danger',
  stopping: 'busy', stopped: 'neutral', completed: 'ok', faulted: 'danger',
};

export const taskStatusLabel: Record<TaskStatus, string> = {
  queued: '排队中', running: '执行中', cancelling: '取消中', completed: '已完成', failed: '失败', cancelled: '已取消',
};

export const experimentStatusLabel: Record<string, string> = {
  RUNNING: '运行中', PAUSED: '已暂停', INTERRUPTED: '联锁中断', STOPPED: '已停止', COMPLETED: '已完成',
  FAULTED: '故障停止', FINISHED: '已结束',
};

export function fmt(value: number | null | undefined, digits = 2, fallback = '--'): string {
  if (value === null || value === undefined || Number.isNaN(value)) return fallback;
  return value.toFixed(digits);
}

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return '--';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString('zh-CN', { hour12: false });
}

export function fmtClock(iso: string | null | undefined): string {
  if (!iso) return '--';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleTimeString('zh-CN', { hour12: false });
}

export function fmtDuration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  return h > 0 ? `${h}h ${m}m ${r}s` : m > 0 ? `${m}m ${r}s` : `${r}s`;
}

export function hex(word: number): string {
  return `0x${word.toString(16).toUpperCase().padStart(4, '0')}`;
}

export function downloadText(name: string, text: string, type = 'application/json'): void {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
