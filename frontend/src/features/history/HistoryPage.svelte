<script lang="ts">
  import { onMount } from 'svelte';
  import ConfirmDialog from '../../components/ConfirmDialog.svelte';
  import Badge from '../../components/Badge.svelte';
  import * as api from '../../lib/api/endpoints';
  import type { ExperimentDetail, ExperimentSummary, MeasurementPoint, Task } from '../../lib/api/types';
  import { awaitTask } from '../../lib/state/tasks';
  import { notifier } from '../../lib/state/notify.svelte';
  import { errorMessage, revealExport } from '../../lib/api/client';
  import { experimentStatusLabel, fmt, fmtTime, taskStatusLabel } from '../../lib/format';

  let { online, activeExperimentId }: { online: boolean; activeExperimentId: number | null } = $props();

  const PAGE = 200;
  let experiments: ExperimentSummary[] = $state([]);
  let selected = $state<ExperimentDetail | null>(null);
  let rows: MeasurementPoint[] = $state([]);
  let total = $state(0);
  let offset = $state(0);
  let error = $state('');
  let busy = $state<string | null>(null);
  let renaming = $state(false);
  let newName = $state('');
  let confirmDelete = $state(false);
  let lastTask = $state<Task | null>(null);

  const statusTone = (status: string) => status === 'COMPLETED' ? 'ok' : status === 'FAULTED' ? 'danger' : status === 'RUNNING' || status === 'PAUSED' || status === 'INTERRUPTED' ? 'busy' : 'neutral';

  async function load() {
    try { experiments = await api.listExperiments(500); error = ''; const current = selected; if (current && !experiments.some((e) => e.id === current.id)) { selected = null; rows = []; } }
    catch (e) { error = errorMessage(e); }
  }

  async function select(id: number, page = 0) {
    try {
      selected = await api.getExperiment(id);
      offset = page * PAGE;
      const result = await api.experimentMeasurements(id, PAGE, offset);
      rows = result.items; total = result.total; error = '';
    } catch (e) { error = errorMessage(e); }
  }

  async function exportKind(kind: 'measurements_csv' | 'measurements_xlsx' | 'summary_csv') {
    if (!selected || busy) return;
    busy = kind;
    try {
      lastTask = await awaitTask(await api.startExport(selected.id, kind), (t) => (lastTask = t));
      if (lastTask.status === 'completed') notifier.push('ok', '导出完成', lastTask.result?.filename as string);
      else notifier.push('danger', '导出未完成', lastTask.error ?? taskStatusLabel[lastTask.status]);
    } catch (e) { error = errorMessage(e); } finally { busy = null; }
  }

  async function rename() {
    if (!selected) return;
    try { selected = await api.renameExperiment(selected.id, newName); renaming = false; notifier.push('ok', '实验已重命名'); await load(); }
    catch (e) { error = errorMessage(e); }
  }

  async function remove() {
    confirmDelete = false;
    if (!selected) return;
    try { await api.deleteExperiment(selected.id); notifier.push('ok', '实验已删除'); selected = null; rows = []; await load(); }
    catch (e) { error = errorMessage(e); }
  }

  onMount(() => { void load(); });
  $effect(() => { if (online) void load(); });
  const pages = $derived(Math.max(1, Math.ceil(total / PAGE)));
  const currentPage = $derived(Math.floor(offset / PAGE));
</script>

<div class="grid sidebar">
  <section class="panel">
    <div class="panel-head"><h2>历史实验</h2><button class="btn sm" type="button" onclick={load} disabled={!online}>刷新</button></div>
    <div class="panel-body">
      {#if experiments.length}
        <div class="table-wrap" style="max-height:70vh"><table><thead><tr><th>#</th><th>名称</th><th>状态</th><th>开始</th></tr></thead><tbody>
          {#each experiments as exp}
            <tr class="clickable" aria-selected={exp.id === selected?.id} onclick={() => select(exp.id)}>
              <td class="mono">{exp.id}</td><td>{exp.name}</td><td><Badge tone={statusTone(exp.status)}>{experimentStatusLabel[exp.status] ?? exp.status}</Badge></td><td class="mono small">{fmtTime(exp.started_at)}</td>
            </tr>
          {/each}
        </tbody></table></div>
      {:else}<div class="empty"><strong>暂无历史实验</strong>完成一次实验后会在此列出。</div>{/if}
    </div>
  </section>

  <section class="panel">
    <div class="panel-head">
      <div class="row"><h2>{selected ? `实验 #${selected.id} ${selected.name}` : '实验详情'}</h2>{#if selected}<Badge tone={statusTone(selected.status)}>{experimentStatusLabel[selected.status] ?? selected.status}</Badge>{/if}</div>
      {#if selected}
        <div class="row">
          <button class="btn sm" type="button" onclick={() => { newName = selected!.name; renaming = true; }} disabled={!online}>重命名</button>
          <button class="btn sm danger" type="button" onclick={() => (confirmDelete = true)} disabled={!online || selected.id === activeExperimentId}>删除</button>
          <button class="btn sm" type="button" onclick={() => exportKind('measurements_csv')} disabled={!online || busy !== null}>导出 CSV</button>
          <button class="btn sm" type="button" onclick={() => exportKind('measurements_xlsx')} disabled={!online || busy !== null}>导出 Excel</button>
          <button class="btn sm" type="button" onclick={() => exportKind('summary_csv')} disabled={!online || busy !== null}>导出摘要</button>
        </div>
      {/if}
    </div>
    <div class="panel-body stack">
      {#if error}<div class="notice" data-tone="danger" role="alert"><div><div class="title">操作未完成</div><div>{error}</div></div><button class="close" type="button" aria-label="关闭" onclick={() => (error = '')}>×</button></div>{/if}
      {#if renaming}
        <div class="row"><input class="input" style="max-width:360px" bind:value={newName} maxlength="100" aria-label="新的实验名称" /><button class="btn primary sm" type="button" onclick={rename} disabled={!newName.trim()}>保存</button><button class="btn sm" type="button" onclick={() => (renaming = false)}>取消</button></div>
      {/if}
      {#if lastTask}
        <div class="notice" data-tone={lastTask.status === 'completed' ? 'ok' : lastTask.status === 'failed' ? 'danger' : 'info'} role="status">
          <div style="flex:1"><div class="title">导出任务：{taskStatusLabel[lastTask.status]}</div>
            {#if lastTask.result?.path}<div class="mono small" style="margin-top:4px">{lastTask.result.path} <button class="btn sm" type="button" onclick={() => revealExport(lastTask!.result!.path as string).then((ok) => { if (!ok) notifier.push('info', '文件已保存', lastTask!.result!.path as string); })}>打开所在目录</button></div>{/if}
            {#if lastTask.error}<div>{lastTask.error}</div>{/if}</div>
        </div>
      {/if}
      {#if selected}
        <dl class="kv">
          <dt>配方</dt><dd>{selected.recipe_name ?? '--'}</dd>
          <dt>开始 / 结束</dt><dd>{fmtTime(selected.started_at)} → {fmtTime(selected.finished_at)}</dd>
          <dt>样本数</dt><dd>{selected.measurement_count}</dd>
          {#if selected.summary}
            <dt>温度范围</dt><dd>{fmt(selected.summary.min_temperature_c, 1)} ~ {fmt(selected.summary.max_temperature_c, 1)} ℃</dd>
            <dt>重量范围</dt><dd>{fmt(selected.summary.min_weight_g, 3)} ~ {fmt(selected.summary.max_weight_g, 3)} g</dd>
          {/if}
          <dt>试样参数</dt><dd>m₀ {fmt(selected.initial_mass_g, 3)} g · TFe {fmt(selected.tfe_pct)} % · FeO {fmt(selected.feo_pct)} %</dd>
        </dl>
        <div class="row between"><h3>测量数据</h3>
          <div class="row small"><button class="btn sm" type="button" onclick={() => select(selected!.id, currentPage - 1)} disabled={currentPage === 0}>上一页</button><span>第 {currentPage + 1} / {pages} 页 · 共 {total} 条</span><button class="btn sm" type="button" onclick={() => select(selected!.id, currentPage + 1)} disabled={currentPage + 1 >= pages}>下一页</button></div>
        </div>
        {#if rows.length}
          <div class="table-wrap"><table><thead><tr><th>时间</th><th class="num">温度 ℃</th><th class="num">重量 g</th><th class="num">N₂</th><th class="num">H₂</th><th class="num">CO</th></tr></thead><tbody>
            {#each rows as row}<tr><td class="mono">{fmtTime(row.sampled_at)}</td><td class="num">{fmt(row.temperature_c, 1)}</td><td class="num">{fmt(row.weight_g, 3)}</td><td class="num">{fmt(row.n2_lpm)}</td><td class="num">{fmt(row.h2_lpm)}</td><td class="num">{fmt(row.co_lpm)}</td></tr>{/each}
          </tbody></table></div>
        {:else}<div class="empty">该实验没有测量数据。</div>{/if}
      {:else}<div class="empty"><strong>请选择实验</strong>在左侧列表选择一个实验查看详情、导出数据或管理记录。</div>{/if}
    </div>
  </section>
</div>

<ConfirmDialog open={confirmDelete} title="删除实验" message={`删除实验 #${selected?.id} 及其全部测量与报警数据？此操作不可撤销。`} confirmLabel="删除" tone="danger" onconfirm={remove} oncancel={() => (confirmDelete = false)} />
