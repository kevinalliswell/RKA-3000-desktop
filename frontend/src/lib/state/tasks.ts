import * as api from '../api/endpoints';
import type { Task } from '../api/types';

const TERMINAL = new Set(['completed', 'failed', 'cancelled']);

/** Poll a task until terminal; the callback receives every snapshot (for progress UI). */
export async function awaitTask(task: Task, onUpdate?: (task: Task) => void, intervalMs = 300, timeoutMs = 120000): Promise<Task> {
  const deadline = Date.now() + timeoutMs;
  let current = task;
  onUpdate?.(current);
  while (!TERMINAL.has(current.status)) {
    if (Date.now() > deadline) throw new Error('任务等待超时，可在日志页查看任务状态');
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
    current = await api.getTask(current.id);
    onUpdate?.(current);
  }
  return current;
}
