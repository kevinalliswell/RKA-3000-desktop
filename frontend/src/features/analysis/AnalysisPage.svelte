<script lang="ts">
  import { onMount } from 'svelte';
  import LineChart from '../../components/LineChart.svelte';
  import Metric from '../../components/Metric.svelte';
  import * as api from '../../lib/api/endpoints';
  import type { ExperimentSummary, KineticsResult, Task } from '../../lib/api/types';
  import { awaitTask } from '../../lib/state/tasks';
  import { notifier } from '../../lib/state/notify.svelte';
  import { errorMessage, revealExport } from '../../lib/api/client';
  import { experimentStatusLabel, fmt, taskStatusLabel } from '../../lib/format';

  let { online }: { online: boolean } = $props();

  let experiments: ExperimentSummary[] = $state([]);
  let selected: number = $state(0);
  let params = $state({ initial_mass_g: 0, tfe_pct: 0, feo_pct: 0 });
  let result = $state<KineticsResult | null>(null);
  let error = $state('');
  let busy = $state<'compute' | 'save' | 'report' | null>(null);
  let reportTask = $state<Task | null>(null);

  async function load() {
    try {
      experiments = await api.listExperiments(200);
      error = '';
      if (!experiments.some((e) => e.id === selected)) { selected = experiments[0]?.id ?? 0; await loadParams(); }
    } catch (e) { error = errorMessage(e); }
  }

  async function loadParams() {
    result = null;
    reportTask = null;
    if (!selected) return;
    try {
      const stored = await api.getSampleParams(selected);
      params = { initial_mass_g: stored.initial_mass_g ?? 0, tfe_pct: stored.tfe_pct ?? 0, feo_pct: stored.feo_pct ?? 0 };
    } catch (e) { error = errorMessage(e); }
  }

  function numericParams() {
    return { initial_mass_g: Number(params.initial_mass_g), tfe_pct: Number(params.tfe_pct), feo_pct: Number(params.feo_pct) };
  }

  async function save() {
    if (busy) return;
    busy = 'save';
    try { await api.putSampleParams(selected, numericParams()); notifier.push('ok', `已保存实验 #${selected} 的试样参数`); error = ''; }
    catch (e) { error = errorMessage(e); } finally { busy = null; }
  }

  async function compute() {
    if (busy) return;
    busy = 'compute';
    try { result = await api.computeKinetics(selected, numericParams()); error = ''; }
    catch (e) { error = errorMessage(e); result = null; } finally { busy = null; }
  }

  async function report() {
    if (busy) return;
    busy = 'report';
    try {
      const task = await api.startReport(selected, numericParams());
      reportTask = await awaitTask(task, (t) => (reportTask = t));
      if (reportTask.status === 'completed') notifier.push('ok', '报告已生成', reportTask.result?.filename as string);
      else notifier.push('danger', '报告未生成', reportTask.error ?? taskStatusLabel[reportTask.status]);
    } catch (e) { error = errorMessage(e); } finally { busy = null; }
  }

  async function cancelReport() { if (reportTask) reportTask = await api.cancelTask(reportTask.id); }

  const degree = $derived(result?.points.map((p) => [p.t_min, p.reduction_degree_pct] as [number, number]) ?? []);
  const rate = $derived(result?.points.map((p) => [p.t_min, p.rate_pct_per_min] as [number, number]) ?? []);

  onMount(() => { void load(); });
  $effect(() => { if (online) void load(); });
</script>

<div class="stack">
  <section class="panel">
    <div class="panel-head"><h2>数据分析 · 失重法还原动力学</h2>
      <div class="row">
        <button class="btn sm" type="button" onclick={load} disabled={!online}>刷新实验</button>
        <button class="btn" type="button" onclick={save} disabled={!online || !selected || busy !== null}>保存参数</button>
        <button class="btn primary" type="button" onclick={compute} disabled={!online || !selected || busy !== null}>{#if busy === 'compute'}<span class="spinner" aria-hidden="true"></span>{/if}计算还原度</button>
        <button class="btn accent" type="button" onclick={report} disabled={!online || !selected || !result || busy !== null}>{#if busy === 'report'}<span class="spinner" aria-hidden="true"></span>{/if}生成 Excel 报告</button>
      </div>
    </div>
    <div class="panel-body stack">
      {#if error}<div class="notice" data-tone="danger" role="alert"><div><div class="title">分析未完成</div><div>{error}</div></div><button class="close" type="button" aria-label="关闭" onclick={() => (error = '')}>×</button></div>{/if}
      <div class="form-grid">
        <label class="field" style="grid-column: span 2"><span>实验</span>
          <select bind:value={selected} onchange={loadParams} disabled={!online || !experiments.length}>
            {#if !experiments.length}<option value={0}>暂无实验</option>{/if}
            {#each experiments as exp}<option value={exp.id}>#{exp.id} {exp.name} [{experimentStatusLabel[exp.status] ?? exp.status}]</option>{/each}
          </select>
        </label>
        <label class="field"><span>初始质量 m₀ (g)</span><input type="number" min="0" step="0.001" bind:value={params.initial_mass_g} /></label>
        <label class="field"><span>全铁 TFe (%)</span><input type="number" min="0" max="100" step="0.01" bind:value={params.tfe_pct} /></label>
        <label class="field"><span>FeO (%)</span><input type="number" min="0" max="100" step="0.01" bind:value={params.feo_pct} /></label>
      </div>
      {#if reportTask}
        <div class="notice" data-tone={reportTask.status === 'completed' ? 'ok' : reportTask.status === 'failed' ? 'danger' : 'info'} role="status">
          <div style="flex:1">
            <div class="title">报告任务：{taskStatusLabel[reportTask.status]}{reportTask.phase ? ` · ${reportTask.phase}` : ''}</div>
            {#if reportTask.status === 'running' || reportTask.status === 'queued' || reportTask.status === 'cancelling'}<div class="progress" style="margin-top:6px"><div style={`width:${Math.round(reportTask.progress * 100)}%`}></div></div>{/if}
            {#if reportTask.result?.path}<div class="mono small" style="margin-top:6px">{reportTask.result.path} <button class="btn sm" type="button" onclick={() => revealExport(reportTask!.result!.path as string).then((ok) => { if (!ok) notifier.push('info', '文件已保存', reportTask!.result!.path as string); })}>打开所在目录</button></div>{/if}
            {#if reportTask.error}<div>{reportTask.error}</div>{/if}
          </div>
          {#if reportTask.status === 'running' || reportTask.status === 'queued'}<button class="btn sm" type="button" onclick={cancelReport}>取消</button>{/if}
        </div>
      {/if}
      <div class="grid metrics">
        <Metric label="终态还原度" value={fmt(result?.final_degree_pct)} unit="%" tone="accent" />
        <Metric label="到 40% 时间" value={fmt(result?.time_to_40_min)} unit="min" />
        <Metric label="到 60% 时间" value={fmt(result?.time_to_60_min)} unit="min" />
        <Metric label="40% 还原速率" value={fmt(result?.rate_at_40_pct, 3)} unit="%/min" />
        <Metric label="采样点" value={result ? String(result.points.length) : '--'} />
      </div>
    </div>
  </section>
  <div class="grid two">
    <section class="panel"><div class="panel-head"><h3>还原度曲线 R(t)</h3></div><div class="panel-body"><LineChart series={[{ name: 'R(t) %', color: 'var(--chart-1)', points: degree }]} xLabel="min" yLabel="%" /></div></section>
    <section class="panel"><div class="panel-head"><h3>还原速率 dR/dt</h3></div><div class="panel-body"><LineChart series={[{ name: 'dR/dt %/min', color: 'var(--chart-3)', points: rate }]} xLabel="min" yLabel="%/min" /></div></section>
  </div>
</div>
