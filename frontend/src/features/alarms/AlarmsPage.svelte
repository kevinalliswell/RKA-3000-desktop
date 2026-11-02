<script lang="ts">
  import { onMount } from 'svelte';
  import Badge from '../../components/Badge.svelte';
  import * as api from '../../lib/api/endpoints';
  import { errorMessage } from '../../lib/api/client';
  import type { AlarmRecord, Rules } from '../../lib/api/types';
  import type { RunSession } from '../../lib/state/run.svelte';
  import { prefs } from '../../lib/state/prefs.svelte';
  import { nav } from '../../lib/state/nav.svelte';
  import { notifier } from '../../lib/state/notify.svelte';
  import { fmtShort } from '../../lib/format';

  let { run, online }: { run: RunSession; online: boolean } = $props();

  let tab = $state<'pending' | 'acked' | 'rules'>('pending');
  let pending = $state<AlarmRecord[]>([]);
  let acked = $state<AlarmRecord[]>([]);
  let rules = $state<Rules | null>(null);
  let selected = $state<AlarmRecord | null>(null);
  let note = $state('');
  let error = $state('');
  let busy = $state(false);

  const level = (a: AlarmRecord) => (a.level === 'ALARM' || a.level === 'CRITICAL' ? '报警' : a.level === 'WARNING' ? '警告' : a.level);
  const tone = (a: AlarmRecord) => (a.level === 'ALARM' || a.level === 'CRITICAL' ? 'danger' : 'warn') as 'danger' | 'warn';

  async function load() {
    error = '';
    try {
      [pending, acked, rules] = await Promise.all([
        api.listAlarms({ state: 'pending' }), api.listAlarms({ state: 'acked', limit: 100 }), api.rules(),
      ]);
      if (!selected || !pending.some((a) => a.id === selected!.id)) selected = pending[0] ?? null;
    } catch (e) {
      error = errorMessage(e);
    }
  }

  onMount(() => { void load(); });
  $effect(() => { void run.state?.pending_alarms.length; if (online) void load(); });

  async function acknowledge() {
    if (!selected || note.trim().length < 2) return;
    busy = true;
    const ok = await run.ackAlarm(selected.id, note.trim(), prefs.operator || undefined);
    busy = false;
    if (ok) {
      notifier.push('ok', '报警已确认', '确认记录已写入操作审计');
      note = '';
      await load();
      if (!pending.length) tab = 'acked';
    } else {
      notifier.push('danger', '确认失败', run.error);
    }
  }
</script>

<div class="page-head">
  <div>
    <h1>报警事件</h1>
    <p>报警分两级：警告只提示，报警会自动进入惰性处置。无论哪一级，未确认前都禁止启动新实验与手动调气。</p>
  </div>
  <div class="actions"><Badge tone={pending.length ? 'warn' : 'good'} dot>{pending.length ? `${pending.length} 条待确认 · 调气与启动已禁用` : '无待确认报警'}</Badge></div>
</div>

{#if error}<div class="callout danger">{error}</div>{/if}
{#if pending.length}
  <div class="callout warn"><strong>存在 {pending.length} 条待确认报警。</strong> {run.active ? '当前实验继续运行（报警级会自动进入处置），但“手动调气”和“确认启动”已禁用' : '“确认启动”已禁用'}，直到确认并填写处理说明。</div>
{:else}
  <div class="callout good"><strong>无待确认报警。</strong> 手动调气与启动权限不受报警限制。确认记录已写入操作审计。</div>
{/if}

<div class="tabs" role="tablist">
  <button type="button" role="tab" aria-selected={tab === 'pending'} onclick={() => (tab = 'pending')}>待确认 · {pending.length}</button>
  <button type="button" role="tab" aria-selected={tab === 'acked'} onclick={() => (tab = 'acked')}>已确认 · {acked.length}</button>
  <button type="button" role="tab" aria-selected={tab === 'rules'} onclick={() => (tab = 'rules')}>报警规则与阈值</button>
</div>

{#if tab === 'pending'}
  <div class="grid main-side">
    <section class="card">
      {#each pending as alarm}
        <button type="button" class="check" style="width:100%;text-align:left;margin-bottom:8px;grid-template-columns:auto minmax(0,1fr)"
          class:on={selected?.id === alarm.id} onclick={() => (selected = alarm)}>
          <Badge tone={tone(alarm)}>{level(alarm)}</Badge>
          <div><strong>{alarm.message}</strong><span class="mono">{fmtShort(alarm.created_at)} · {alarm.code}{alarm.experiment_id ? ` · 实验 #${alarm.experiment_id}` : ''}</span></div>
        </button>
      {:else}
        <div class="empty"><strong>当前没有待确认报警</strong>新的报警会出现在这里，并在导航栏显示数量。</div>
      {/each}
    </section>
    <section class="card">
      <h2>确认报警</h2>
      <p class="small soft" style="margin:6px 0 12px">确认表示操作者已知晓并处理。必须填写处理说明，记录到操作审计并随实验归档。</p>
      {#if selected}
        <div class="callout" style="margin-bottom:12px"><strong>{selected.message}</strong><div class="mono tiny">{fmtShort(selected.created_at)} · {level(selected)} · {selected.code}</div></div>
        <label class="field"><span>处理说明（必填）</span>
          <textarea bind:value={note} placeholder="例如 H₂ 气瓶切换瞬时波动，已核对减压阀" maxlength="300"></textarea></label>
        <div class="row" style="margin-top:12px">
          <button class="btn primary" type="button" disabled={!online || busy || note.trim().length < 2} onclick={acknowledge}>
            {#if busy}<span class="spinner" aria-hidden="true"></span>{/if}确认并记录</button>
          {#if run.active}<button class="btn" type="button" onclick={() => nav.go('current')}>返回当前实验</button>{/if}
        </div>
      {:else}
        <p class="soft small">没有需要确认的报警。</p>
      {/if}
    </section>
  </div>
{:else if tab === 'acked'}
  <section class="card flush">
    <div class="table-wrap">
      <table class="data">
        <thead><tr><th>时间</th><th>级别</th><th>内容</th><th>实验</th><th>确认</th><th>处理说明</th></tr></thead>
        <tbody>
          {#each acked as alarm}
            <tr><td class="mono nowrap">{fmtShort(alarm.created_at)}</td><td><Badge tone={tone(alarm)}>{level(alarm)}</Badge></td>
              <td>{alarm.message}<div class="tiny soft mono">{alarm.code}</div></td><td class="mono">{alarm.experiment_id ?? '—'}</td>
              <td class="nowrap">{alarm.acknowledged_by}<div class="tiny soft mono">{fmtShort(alarm.acknowledged_at)}</div></td><td>{alarm.ack_note || '—'}</td></tr>
          {:else}<tr><td colspan="6"><div class="empty">暂无已确认报警</div></td></tr>{/each}
        </tbody>
      </table>
    </div>
  </section>
{:else}
  <section class="card flush">
    <div class="table-wrap">
      <table class="data">
        <thead><tr><th>规则</th><th>触发条件</th><th>级别</th><th>系统自动动作</th></tr></thead>
        <tbody>
          {#each rules?.alarm_rules ?? [] as rule}
            <tr><td><strong>{rule.name}</strong><div class="tiny soft mono">{rule.code}</div></td><td>{rule.condition}</td>
              <td><Badge tone={rule.level === 'alarm' ? 'danger' : 'warn'}>{rule.level === 'alarm' ? '报警' : rule.level === 'warning' ? '警告' : '警告→报警'}</Badge></td>
              <td>{rule.action}</td></tr>
          {/each}
        </tbody>
      </table>
    </div>
    <p class="tiny soft" style="padding:10px 14px">阈值为系统固定值，不在界面修改。回读过期报警延时为 {rules?.stale_warning_seconds ?? '—'} s（设置项）。可燃气、超压、急停等硬件报警由 PLC 报警字给出（PLC 通路）；多设备通路未接入气体探头。</p>
  </section>
{/if}
