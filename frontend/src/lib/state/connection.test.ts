import { describe, expect, it } from 'vitest';
import { ApiError } from '../api/client';
import { Connection } from './connection.svelte';
import type { Health } from '../api/types';

const HEALTH: Health = {
  ok: true, service: 'rka3000-backend', version: '0.8.0', api_version: 1, simulation_mode: true,
  device_backend: 'multi_device', run_active: false, data_dir: '', export_dir: '', database: '', log_path: '',
  restart_required: false, notes: [],
};

function timers() {
  const scheduled: { fn: () => void; ms: number }[] = [];
  return {
    scheduled,
    setTimer: (fn: () => void, ms: number) => { scheduled.push({ fn, ms }); return scheduled.length; },
    clearTimer: () => undefined,
  };
}

describe('Connection', () => {
  it('goes online and schedules a heartbeat', async () => {
    const t = timers();
    const connection = new Connection({ health: async () => HEALTH, status: async () => null, ...t });
    await connection.start();
    expect(connection.phase).toBe('online');
    expect(connection.health?.version).toBe('0.8.0');
    expect(t.scheduled.at(-1)?.ms).toBe(5000);
  });

  it('stops retrying once the backend process has exited', async () => {
    const t = timers();
    const connection = new Connection({
      health: async () => { throw new ApiError({ code: 'backend_exited', message: 'gone' }); },
      status: async () => ({ exited: true, available: true, error: null }),
      ...t,
    });
    await connection.start();
    expect(connection.phase).toBe('exited');
    expect(t.scheduled).toHaveLength(0);
    expect(connection.error).toContain('重新启动');
  });

  it('retries with backoff a bounded number of times then goes offline', async () => {
    const t = timers();
    const connection = new Connection({
      health: async () => { throw new ApiError({ code: 'unreachable', message: 'refused' }); },
      status: async () => null,
      ...t,
    });
    await connection.start();
    expect(connection.phase).toBe('retrying');
    expect(t.scheduled[0]?.ms).toBe(1000);
    for (let i = 0; i < 20 && connection.phase === 'retrying'; i += 1) {
      await connection.probe();
    }
    expect(connection.phase).toBe('offline');
    expect(connection.attempts).toBe(connection.maxAttempts);
    expect(Math.max(...t.scheduled.map((s) => s.ms))).toBeLessThanOrEqual(8000);
  });

  it('reports a startup failure from the shell without retrying', async () => {
    const t = timers();
    const connection = new Connection({
      health: async () => { throw new ApiError({ code: 'backend_unavailable', message: 'no sidecar' }); },
      status: async () => ({ exited: false, available: false, error: '缺少 rka3000-backend.exe' }),
      ...t,
    });
    await connection.start();
    expect(connection.phase).toBe('offline');
    expect(connection.error).toContain('rka3000-backend');
    expect(t.scheduled).toHaveLength(0);
  });
});
