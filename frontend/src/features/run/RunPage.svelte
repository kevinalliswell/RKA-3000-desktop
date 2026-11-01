<script lang="ts">
  import { onMount } from 'svelte';
  import ConfirmDialog from '../../components/ConfirmDialog.svelte';
  import LineChart from '../../components/LineChart.svelte';
  import Metric from '../../components/Metric.svelte';
  import Badge from '../../components/Badge.svelte';
  import * as api from '../../lib/api/endpoints';
  import type { RecipeSummary } from '../../lib/api/types';
  import type { RunSession } from '../../lib/state/run.svelte';
  import { notifier } from '../../lib/state/notify.svelte';
  import { errorMessage } from '../../lib/api/client';
  import { fmt, fmtClock, hex, runStatusLabel, runStatusTone } from '../../lib/format';

  let { run, online }: { run: RunSession; online: boolean } = $props();

  let recipes: RecipeSummary[] = $state([]);
  let selectedRecipe: number = $state(0);
  let recipesError = $state('');
  type Pending = { kind: 'start' | 'stop' | 'gas-mode' | 'manual-gas' | 'reset' | 'ack'; mode?: 'auto' | 'manual' } | null;
  let pending = $state<Pending>(null);
  let manual = $state({ n2_lpm: 0, h2_lpm: 0, co_lpm: 0 });

  const s = $derived(run.state);
  const latest = $derived(run.state?.latest ?? null);
  const stepProgress = $derived(s && s.total_steps ? `${s.current_step_no ?? '--'} / ${s.total_steps}` : '--');
  const chartT = $derived(run.points.map((p, i) => [i, p.temperature_c] as [number, number]));
  const chartW = $derived(run.points.map((p, i) => [i, p.weight_g] as [number, number]));
  const chartGas = $derived({
    n2: run.points.map((p, i) => [i, p.n2_lpm] as [number, number]),
    h2: run.points.map((p, i) => [i, p.h2_lpm] as [number, number]),
    co: run.points.map((p, i) => [i, p.co_lpm] as [number, number]),
  });
  const showStopping = $derived(s?.status === 'stopping' || run.stopRequested);

  async function loadRecipes() {
    try {
      recipes = await api.listRecipes();
      recipesError = '';
      if (!recipes.some((r) => r.id === selectedRecipe)) selectedRecipe = recipes[0]?.id ?? 0;
    } catch (error) { recipesError = errorMessage(error); }
  }

  onMount(() => { void loadRecipes(); });
  $effect(() => { if (online) void loadRecipes(); });
  $effect(() => {
    if (s?.manual_gas) manual = { ...s.manual_gas };
    else if (s?.current_step && s.gas_mode === 'manual') manual = { n2_lpm: s.current_step.n2_lpm, h2_lpm: s.current_step.h2_lpm, co_lpm: s.current_step.co_lpm };
  });

  async function confirmPending() {
    const action = pending;
    pending = null;
    if (!action) return;
    let ok = false;
    if (action.kind === 'start') ok = await run.startRun(selectedRecipe);
    else if (action.kind === 'stop') ok = await run.stop();
    else if (action.kind === 'gas-mode' && action.mode) ok = await run.setGasMode(action.mode);
    else if (action.kind === 'manual-gas') ok = await run.setManualGas({ n2_lpm: Number(manual.n2_lpm), h2_lpm: Number(manual.h2_lpm), co_lpm: Number(manual.co_lpm) });
    else if (action.kind === 'reset') ok = await run.resetInterlock();
    else if (action.kind === 'ack') ok = await run.ackAlarm();
    if (ok) {
      const label = { start: '实验已启动', stop: '已请求停止，正在收尾', 'gas-mode': '配气模式已切换', 'manual-gas': '手动配气已下发', reset: '已下发联锁复位', ack: '报警已确认' }[action.kind];
      notifier.push('ok', label);
    } else if (run.error) {
      notifier.push('danger', '操作未完成', run.error);
    }
  }

  const dialogText = $derived.by(() => {
    switch (pending?.kind) {
      case 'start': return { title: '确认启动实验', message: `按配方「${recipes.find((r) => r.id === selectedRecipe)?.name ?? ''}」开始实验？启动后将按步骤自动配气；温度程序将${s?.temperature_mode === 'setpoint' ? '逐步下发设定值' : '一次性下发到控温仪并由仪表自动执行'}。`, tone: 'primary' as const, label: '启动' };
      case 'stop': return { title: '确认停止实验', message: '停止后不能恢复，已记录的数据会保留。停止请求下发后需等待数据写入完成。', tone: 'danger' as const, label: '停止实验' };
      case 'gas-mode': return { title: pending.mode === 'manual' ? '切换到手动配气' : '切换回自动配气', message: pending.mode === 'manual' ? '切换后软件不再按配方下发气体设定，气体流量由您在本页手动下发。此操作在实验运行中进行，请再次确认。' : '切换后立即按当前步骤的配方重新下发气体设定，并在后续步骤自动配气。请再次确认。', tone: 'warn' as const, label: '确认切换' };
      case 'manual-gas': return { title: '下发手动气体设定', message: `将向 MFC 下发 N2 ${manual.n2_lpm} / H2 ${manual.h2_lpm} / CO ${manual.co_lpm} L/min。`, tone: 'warn' as const, label: '下发' };
      case 'reset': return { title: '确认联锁复位', message: '将向设备下发联锁复位命令。请确认报警原因已排除。', tone: 'warn' as const, label: '复位' };
      case 'ack': return { title: '确认报警', message: '将当前待处理报警标记为已确认。', tone: 'primary' as const, label: '确认' };
      default: return { title: '', message: '', tone: 'primary' as const, label: '确认' };
    }
  });
</script>

<div class="stack">
  <section class="panel">
    <div class="panel-head">
      <div class="row">
        <h2>实验运行</h2>
        {#if s}<Badge tone={runStatusTone[s.status]}>{runStatusLabel[s.status]}</Badge>{/if}
        {#if s?.experiment_id}<span class="muted small">实验 #{s.experiment_id} · {s.recipe_name}</span>{/if}
      </div>
      <div class="row">
        {#if s?.gas_mode}<Badge tone={s.gas_mode === 'manual' ? 'warn' : 'info'}>{s.gas_mode === 'manual' ? '手动配气' : '自动配气'}</Badge>{/if}
        {#if s?.temperature_mode}<Badge tone="neutral">{s.temperature_mode === 'program' ? '温度程序：仪表执行' : '温度：逐步设定'}</Badge>{/if}
      </div>
    </div>
    <div class="panel-body stack">
      <div class="row">
        <label class="field" style="min-width:300px"><span>实验配方</span>
          <select bind:value={selectedRecipe} disabled={!online || run.active || !recipes.length}>
            {#if !recipes.length}<option value={0}>暂无配方，请先在「配方」页创建</option>{/if}
            {#each recipes as recipe}<option value={recipe.id}>#{recipe.id} {recipe.name}</option>{/each}
          </select>
        </label>
        <button class="btn sm" type="button" onclick={loadRecipes} disabled={!online}>刷新</button>
        <span class="spacer"></span>
        <button class="btn primary" type="button" disabled={!online || !s?.allowed.start || !selectedRecipe || run.busy !== null} onclick={() => (pending = { kind: 'start' })}>
          {#if run.busy === 'start'}<span class="spinner" aria-hidden="true"></span>{/if}开始实验
        </button>
        <button class="btn" type="button" disabled={!online || !s?.allowed.pause || run.busy !== null} onclick={() => run.pause()}>暂停</button>
        <button class="btn" type="button" disabled={!online || !s?.allowed.resume || run.busy !== null} onclick={() => run.resume()}>恢复</button>
        <button class="btn danger" type="button" disabled={!online || !s?.allowed.stop || showStopping || run.busy !== null} onclick={() => (pending = { kind: 'stop' })}>
          {#if showStopping}<span class="spinner" aria-hidden="true"></span>停止中…{:else}停止{/if}
        </button>
      </div>
      {#if recipesError}<div class="notice" data-tone="warn">配方列表加载失败：{recipesError}</div>{/if}
      {#if run.error}<div class="notice" data-tone="danger" role="alert"><div><div class="title">操作未完成</div><div>{run.error}</div></div><button class="close" type="button" aria-label="关闭" onclick={() => (run.error = '')}>×</button></div>{/if}
      {#if run.pollError}<div class="notice" data-tone="warn" role="status">状态刷新失败，显示的是最后一次成功读取的数据：{run.pollError}</div>{/if}
      {#if s?.status === 'faulted' && s.error}<div class="notice" data-tone="danger" role="alert"><div><div class="title">实验故障停止</div><div>{s.error}</div></div></div>{/if}
      {#if s?.temperature_program?.message && run.active}<div class="notice" data-tone="info"><div><div class="title">温度程序</div><div>{s.temperature_program.message}</div></div></div>{/if}
      {#if s?.degraded_devices.length}<div class="notice" data-tone="warn" role="alert"><div><div class="title">设备通讯异常：{s.degraded_devices.join('、')}</div><div class="small">显示保持上次有效值；持续无响应将导致实验故障停止。</div></div></div>{/if}
      <div class="grid metrics">
        <Metric label="炉温" value={fmt(latest?.temperature_c, 1)} unit="℃" tone="accent" />
        <Metric label="重量" value={fmt(latest?.weight_g, 3)} unit="g" />
        <Metric label="N₂" value={fmt(latest?.n2_lpm)} unit="L/min" />
        <Metric label="H₂" value={fmt(latest?.h2_lpm)} unit="L/min" />
        <Metric label="CO" value={fmt(latest?.co_lpm)} unit="L/min" />
        <Metric label="步骤" value={stepProgress} />
      </div>
      <dl class="kv">
        <dt>执行状态</dt><dd>{s?.status_text ?? '--'}</dd>
        <dt>当前设定</dt><dd>{s?.setpoints_text ?? '--'}</dd>
        <dt>报警</dt><dd><Badge tone={s?.alarm.word ? 'danger' : 'ok'}>{s?.alarm.text ?? '--'}</Badge></dd>
        <dt>联锁</dt><dd><Badge tone={s?.interlock.word || s?.interlock.estop ? 'danger' : 'ok'}>{s?.interlock.text ?? '--'}</Badge></dd>
        {#if s && s.control_feedback.message !== '控制反馈: 不适用'}
          <dt>控制反馈</dt><dd><Badge tone={s.control_feedback.consistent ? 'ok' : 'danger'}>{s.control_feedback.message}</Badge> <span class="mono muted">{hex(s.control_feedback.word)}</span></dd>
        {/if}
      </dl>
    </div>
  </section>

  <div class="grid two">
    <section class="panel">
      <div class="panel-head"><h3>温度 / 重量</h3><span class="muted small">{run.points.length} 点</span></div>
      <div class="panel-body">
        <LineChart series={[{ name: '炉温 ℃', color: 'var(--chart-2)', points: chartT }, { name: '重量 g', color: 'var(--chart-1)', points: chartW, axis: 'right' }]} xLabel="采样序号" yLabel="℃" y2Label="g" />
      </div>
    </section>
    <section class="panel">
      <div class="panel-head"><h3>气体流量</h3></div>
      <div class="panel-body">
        <LineChart series={[{ name: 'N₂', color: 'var(--chart-3)', points: chartGas.n2 }, { name: 'H₂', color: 'var(--chart-1)', points: chartGas.h2 }, { name: 'CO', color: 'var(--chart-4)', points: chartGas.co }]} xLabel="采样序号" yLabel="L/min" />
      </div>
    </section>
  </div>

  <div class="grid two">
    <section class="panel">
      <div class="panel-head"><h3>配气控制</h3>
        <div class="row">
          <button class="btn sm" type="button" disabled={!online || !s?.allowed.set_gas_mode || s?.gas_mode === 'auto' || run.busy !== null} onclick={() => (pending = { kind: 'gas-mode', mode: 'auto' })}>自动（按配方）</button>
          <button class="btn sm warn" type="button" disabled={!online || !s?.allowed.set_gas_mode || s?.gas_mode === 'manual' || run.busy !== null} onclick={() => (pending = { kind: 'gas-mode', mode: 'manual' })}>手动</button>
        </div>
      </div>
      <div class="panel-body stack">
        {#if s?.gas_mode === 'manual' && run.active}
          <div class="form-grid">
            <label class="field"><span>N₂ (L/min)</span><input type="number" min="0" max="50" step="0.01" bind:value={manual.n2_lpm} /></label>
            <label class="field"><span>H₂ (L/min)</span><input type="number" min="0" max="50" step="0.01" bind:value={manual.h2_lpm} /></label>
            <label class="field"><span>CO (L/min)</span><input type="number" min="0" max="50" step="0.01" bind:value={manual.co_lpm} /></label>
          </div>
          <div class="row"><button class="btn warn" type="button" disabled={!online || !s.allowed.manual_gas || run.busy !== null} onclick={() => (pending = { kind: 'manual-gas' })}>下发手动气体设定</button>
            <span class="muted small">手动模式下步骤切换不会改变气体设定；切回自动将立即按配方下发。</span></div>
        {:else}
          <p class="muted small">{run.active ? '当前按配方自动配气，每次步骤切换时下发该步骤的 N₂/H₂/CO 设定。运行中切换到手动需要二次确认。' : '实验未运行。启动实验后可在此切换配气模式；空闲时的手动设备控制请使用「设备」页。'}</p>
        {/if}
      </div>
    </section>
    <section class="panel">
      <div class="panel-head"><h3>报警与联锁</h3>
        <div class="row">
          <button class="btn sm" type="button" disabled={!online || !s?.allowed.ack_alarm || run.busy !== null} onclick={() => (pending = { kind: 'ack' })}>确认报警</button>
          <button class="btn sm warn" type="button" disabled={!online || !s?.allowed.reset_interlock || run.busy !== null} onclick={() => (pending = { kind: 'reset' })}>联锁复位</button>
        </div>
      </div>
      <div class="panel-body stack">
        {#if s?.pending_alarms.length}
          <div class="table-wrap" style="max-height:180px"><table><thead><tr><th>时间</th><th>代码</th><th>级别</th><th>内容</th></tr></thead><tbody>
            {#each s.pending_alarms as alarm}<tr><td class="mono">{fmtClock(alarm.created_at)}</td><td class="mono">{alarm.code}</td><td><Badge tone={alarm.level === 'CRITICAL' ? 'danger' : 'warn'}>{alarm.level}</Badge></td><td>{alarm.message}</td></tr>{/each}
          </tbody></table></div>
        {:else}<p class="muted small">没有待确认报警。</p>{/if}
        {#if s?.interlock.active.length}<div class="row">{#each s.interlock.active as item}<Badge tone="danger">{item.message}{item.resettable ? '' : '（需硬件解除）'}</Badge>{/each}</div>{/if}
        <details class="diagnostics"><summary>运行消息（{s?.messages.length ?? 0}）</summary>
          <div class="messages">{#each s?.messages ?? [] as m}<div><span class="mono muted">{fmtClock(m.at)}</span><span>{m.text}</span></div>{/each}</div>
        </details>
      </div>
    </section>
  </div>
</div>

<ConfirmDialog open={pending !== null} title={dialogText.title} message={dialogText.message} confirmLabel={dialogText.label} tone={dialogText.tone} busy={run.busy !== null} onconfirm={confirmPending} oncancel={() => (pending = null)} />
