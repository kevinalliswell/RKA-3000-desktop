import { describe, expect, it } from 'vitest';
import { RunSession } from './run.svelte';
import type { RunState } from '../api/types';

function state(status: RunState['status'], extra: Partial<RunState> = {}): RunState {
  return {
    seq: 0, status, pending_terminal: null, engine_state: 'RUNNING', run_id: 'r1', experiment_id: 1, recipe_id: 1,
    recipe_name: 'x', started_at: null, finished_at: null, error: null, current_step_no: 1, total_steps: 1,
    current_step: null, status_text: '', setpoints_text: '', gas_mode: 'auto', temperature_mode: 'program',
    temperature_program: null, manual_gas: null, alarm: { word: 0, text: '正常', active: [] },
    interlock: { word: 0, text: '无联锁', estop: false, resettable: false, active: [] },
    control_feedback: { word: 0, estop_status: 0, consistent: true, message: '' }, pending_alarms: [],
    degraded_devices: [], latest: null, allowed: {
      start: false, pause: true, resume: false, stop: true, ack_alarm: false, reset_interlock: false, set_gas_mode: true, manual_gas: false,
    }, connected: true, messages: [], ...extra,
  };
}

const noTimers = { setTimer: () => 0, clearTimer: () => undefined };

describe('RunSession', () => {
  it('ignores a second command while one is in flight', async () => {
    let current = state('running');
    const session = new RunSession({ runState: async () => current, measurements: async () => ({ seq: 0, items: [] }), ...noTimers });
    let resolve!: (value: RunState) => void;
    const first = session.act('pause', () => new Promise<RunState>((r) => { resolve = r; }));
    const second = await session.act('pause', async () => state('paused'));
    expect(second).toBe(false);
    expect(session.busy).toBe('pause');
    current = state('paused'); // the backend now reports the paused run
    resolve(current);
    expect(await first).toBe(true);
    expect(session.busy).toBeNull();
    expect(session.state?.status).toBe('paused');
  });

  it('keeps stopRequested until the run leaves the active set and surfaces failures', async () => {
    let status: RunState['status'] = 'stopping';
    const session = new RunSession({ runState: async () => state(status), measurements: async () => ({ seq: 0, items: [] }), ...noTimers });
    await session.act('stop', async () => state('stopping'));
    session.stopRequested = true;
    await session.poll();
    expect(session.stopRequested).toBe(true);
    status = 'stopped';
    await session.poll();
    expect(session.stopRequested).toBe(false);
    const failed = await session.act('resume', async () => { throw new Error('当前仍有活动报警'); });
    expect(failed).toBe(false);
    expect(session.error).toContain('活动报警');
  });

  it('accumulates measurements incrementally and resets on a new run', async () => {
    let runId = 'r1';
    let seq = 0;
    const session = new RunSession({
      runState: async () => state('running', { run_id: runId, seq }),
      measurements: async (since) => {
        const items = since < seq ? [{ seq, sampled_at: 't', temperature_c: 1, weight_g: 1, pressure_mpa: 0, n2_lpm: 0, h2_lpm: 0, co_lpm: 0 }] : [];
        return { seq, items };
      },
      ...noTimers,
    });
    seq = 1;
    await session.poll();
    seq = 2;
    await session.poll();
    expect(session.points.map((p) => p.seq)).toEqual([1, 2]);
    runId = 'r2';
    seq = 1;
    await session.poll();
    expect(session.points.map((p) => p.seq)).toEqual([1]);
  });

  it('records poll errors without dropping the last known state', async () => {
    let fail = false;
    const session = new RunSession({
      runState: async () => { if (fail) throw new Error('unreachable'); return state('running'); },
      measurements: async () => ({ seq: 0, items: [] }), ...noTimers,
    });
    await session.poll();
    fail = true;
    await session.poll();
    expect(session.pollError).toBe('unreachable');
    expect(session.state?.status).toBe('running');
  });
});
