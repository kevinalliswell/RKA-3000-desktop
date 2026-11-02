/** Run page state: polls the Python run snapshot, guards against double submits, tracks cancelling. */
import * as api from '../api/endpoints';
import type { Flows, MeasurementPoint, RunState, StartRequest } from '../api/types';

export interface RunDeps {
  runState: () => Promise<RunState>;
  measurements: (since: number) => Promise<{ seq: number; items: MeasurementPoint[] }>;
  emergency: () => Promise<RunState>;
  setTimer: (fn: () => void, ms: number) => unknown;
  clearTimer: (handle: unknown) => void;
}

const defaultDeps: RunDeps = {
  runState: api.runState,
  measurements: api.runMeasurements,
  emergency: api.emergencyStop,
  setTimer: (fn, ms) => setTimeout(fn, ms),
  clearTimer: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
};

export const ACTIVE: ReadonlySet<string> = new Set(['starting', 'running', 'paused', 'interrupted', 'purging', 'stopping']);
export const IN_RUN: ReadonlySet<string> = new Set(['running', 'paused', 'interrupted']);
const MAX_POINTS = 3600;

export class RunSession {
  state: RunState | null = $state(null);
  points: MeasurementPoint[] = $state([]);
  busy: string | null = $state(null); // which action is in flight
  stopRequested = $state(false);
  error = $state('');
  pollError = $state('');
  emergencyBusy = $state(false);
  active = $derived(this.state !== null && ACTIVE.has(this.state.status));
  inRun = $derived(this.state !== null && IN_RUN.has(this.state.status));
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

  startRun(payload: StartRequest): Promise<boolean> {
    if (this.active) return Promise.resolve(false);
    return this.act('start', () => api.startRun(payload));
  }

  pause(): Promise<boolean> {
    return this.act('pause', api.pauseRun);
  }

  resume(): Promise<boolean> {
    return this.act('resume', api.resumeRun);
  }

  /** Ending early is a request: the run goes through safe disposal before it becomes terminal. */
  async stop(reason: string): Promise<boolean> {
    if (this.stopRequested) return false;
    this.stopRequested = true;
    const ok = await this.act('stop', () => api.stopRun(reason));
    if (!ok) this.stopRequested = false;
    return ok;
  }

  /**
   * Emergency gas stop bypasses the one-command-at-a-time guard: it must never wait behind a slow
   * command, and repeated clicks are harmless (the backend latches it).
   */
  async emergency(): Promise<boolean> {
    if (this.emergencyBusy) return false;
    this.emergencyBusy = true;
    this.error = '';
    try {
      const next = await this.deps.emergency();
      if (!this.disposed) this.state = next;
      return true;
    } catch (error) {
      if (!this.disposed) this.error = error instanceof Error ? error.message : String(error);
      return false;
    } finally {
      this.emergencyBusy = false;
      void this.poll();
    }
  }

  ackAlarm(id: number, note: string, operator?: string): Promise<boolean> {
    return this.act('ack', () => api.ackAlarm(id, note, operator));
  }

  resetInterlock(): Promise<boolean> {
    return this.act('reset', api.resetInterlock);
  }

  setGasMode(mode: 'auto' | 'manual'): Promise<boolean> {
    return this.act('gas-mode', () => api.setGasMode(mode, true));
  }

  setManualGas(flows: Flows, reason: string): Promise<boolean> {
    return this.act('manual-gas', () => api.setManualGas(flows, reason));
  }
}
