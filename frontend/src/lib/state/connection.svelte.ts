/** Backend connection state: bounded retries, explicit "backend exited" state, no retry loops. */
import * as api from '../api/endpoints';
import { ApiError, backendStatus } from '../api/client';
import type { Health } from '../api/types';

export type Phase = 'connecting' | 'online' | 'retrying' | 'offline' | 'exited';

export interface ConnectionDeps {
  health: () => Promise<Health>;
  status: () => Promise<{ exited: boolean; available: boolean; error: string | null } | null>;
  setTimer: (fn: () => void, ms: number) => unknown;
  clearTimer: (handle: unknown) => void;
}

const defaultDeps: ConnectionDeps = {
  health: api.health,
  status: backendStatus,
  setTimer: (fn, ms) => setTimeout(fn, ms),
  clearTimer: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
};

export class Connection {
  phase: Phase = $state('connecting');
  health: Health | null = $state(null);
  error = $state('');
  attempts = $state(0);
  online = $derived(this.phase === 'online');
  readonly maxAttempts = 10;
  private timer: unknown;
  private disposed = false;
  private deps: ConnectionDeps;

  constructor(deps: Partial<ConnectionDeps> = {}) {
    this.deps = { ...defaultDeps, ...deps };
  }

  async start(): Promise<void> {
    await this.probe();
  }

  dispose(): void {
    this.disposed = true;
    this.deps.clearTimer(this.timer);
  }

  /** Manual retry after the automatic attempts are exhausted. */
  retry(): Promise<void> {
    this.attempts = 0;
    this.phase = 'connecting';
    return this.probe();
  }

  private schedule(ms: number): void {
    this.deps.clearTimer(this.timer);
    if (!this.disposed) this.timer = this.deps.setTimer(() => void this.probe(), ms);
  }

  async probe(): Promise<void> {
    if (this.disposed) return;
    try {
      const health = await this.deps.health();
      if (this.disposed) return;
      this.health = health;
      this.error = '';
      this.attempts = 0;
      this.phase = 'online';
      this.schedule(5000);
    } catch (error) {
      if (this.disposed) return;
      const status = await this.deps.status();
      const detail = error instanceof Error ? error.message : String(error);
      if (status?.exited || (error instanceof ApiError && error.code === 'backend_exited')) {
        this.phase = 'exited';
        this.error = '业务服务已退出。请关闭并重新启动程序；诊断见日志目录中的 backend.log 与 desktop.log。';
        return; // no retry: the process is gone
      }
      if (status && !status.available) {
        this.phase = 'offline';
        this.error = status.error ?? detail;
        return; // startup failed; the shell reported why
      }
      this.attempts += 1;
      this.error = detail;
      if (this.attempts >= this.maxAttempts) {
        this.phase = 'offline';
        return;
      }
      this.phase = 'retrying';
      this.schedule(Math.min(1000 * 2 ** (this.attempts - 1), 8000));
    }
  }
}
