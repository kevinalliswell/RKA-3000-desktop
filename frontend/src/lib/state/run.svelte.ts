/** Run page state: polls the Python run snapshot, guards against double submits, tracks cancelling. */
import * as api from '../api/endpoints';
import type { MeasurementPoint, RunState } from '../api/types';

export interface RunDeps {
  runState: () => Promise<RunState>;
  measurements: (since: number) => Promise<{ seq: number; items: MeasurementPoint[] }>;
  setTimer: (fn: () => void, ms: number) => unknown;
  clearTimer: (handle: unknown) => void;
}

const defaultDeps: RunDeps = {
  runState: api.runState,
  measurements: api.runMeasurements,
  setTimer: (fn, ms) => setTimeout(fn, ms),
  clearTimer: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
};

export const ACTIVE: ReadonlySet<string> = new Set(['starting', 'running', 'paused', 'interrupted', 'stopping']);
const MAX_POINTS = 1800;

export class RunSession {
  state: RunState | null = $state(null);
  points: MeasurementPoint[] = $state([]);
  busy: string | null = $state(null); // which action is in flight
  stopRequested = $state(false);
  error = $state('');
  pollError = $state('');
  active = $derived(this.state !== null && ACTIVE.has(this.state.status));
  private seq = 0;
  private timer: unknown;
  private disposed = false;
  private polling = false;
  private deps: RunDeps;

  constructor(deps: Partial<RunDeps> = {}) {
    this.deps = { ...defaultDeps, ...deps };
  }

  start(): void {
    this.disposed = false;
    void this.poll();
  }

  dispose(): void {
    this.disposed = true;
    this.deps.clearTimer(this.timer);
  }

  async poll(): Promise<void> {
    if (this.disposed || this.polling) return;
    this.polling = true;
    try {
      const next = await this.deps.runState();
      if (this.disposed) return;
      const previousRun = this.state?.run_id;
      this.state = next;
      this.pollError = '';
      if (next.run_id !== previousRun) {
        this.points = [];
        this.seq = 0;
      }
      if (next.status !== 'stopping' && this.stopRequested && !ACTIVE.has(next.status)) this.stopRequested = false;
      if (ACTIVE.has(next.status) || next.seq > this.seq) {
        const batch = await this.deps.measurements(this.seq);
        if (this.disposed) return;
        if (batch.items.length) {
          this.points = [...this.points, ...batch.items].slice(-MAX_POINTS);
        }
        this.seq = batch.seq;
      }
    } catch (error) {
      if (!this.disposed) this.pollError = error instanceof Error ? error.message : String(error);
    } finally {
      this.polling = false;
      if (!this.disposed) {
        const interval = this.state && ACTIVE.has(this.state.status) ? 700 : 2500;
        this.deps.clearTimer(this.timer);
        this.timer = this.deps.setTimer(() => void this.poll(), interval);
      }
    }
  }

  /** Runs one command at a time; repeated clicks while busy are ignored. */
  async act(name: string, command: () => Promise<RunState>): Promise<boolean> {
    if (this.busy) return false;
    this.busy = name;
    this.error = '';
    try {
      const next = await command();
      if (!this.disposed) this.state = next;
      return true;
    } catch (error) {
      if (!this.disposed) this.error = error instanceof Error ? error.message : String(error);
      return false;
    } finally {
      if (!this.disposed) this.busy = null;
      void this.poll();
    }
  }

  startRun(recipeId: number, gasMode?: 'auto' | 'manual'): Promise<boolean> {
    if (this.active) return Promise.resolve(false);
    return this.act('start', () => api.startRun(recipeId, gasMode));
  }

  pause(): Promise<boolean> {
    return this.act('pause', api.pauseRun);
  }

  resume(): Promise<boolean> {
    return this.act('resume', api.resumeRun);
  }

  /** Stop is a request: the run shows "stopping" until buffered data is flushed. */
  async stop(): Promise<boolean> {
    if (this.stopRequested) return false;
    this.stopRequested = true;
    const ok = await this.act('stop', api.stopRun);
    if (!ok) this.stopRequested = false;
    return ok;
  }

  ackAlarm(): Promise<boolean> {
    return this.act('ack', api.ackAlarm);
  }

  resetInterlock(): Promise<boolean> {
    return this.act('reset', api.resetInterlock);
  }

  setGasMode(mode: 'auto' | 'manual'): Promise<boolean> {
    return this.act('gas-mode', () => api.setGasMode(mode, true));
  }

  setManualGas(values: { n2_lpm: number; h2_lpm: number; co_lpm: number }): Promise<boolean> {
    return this.act('manual-gas', () => api.setManualGas(values));
  }
}
