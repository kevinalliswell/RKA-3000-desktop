<script lang="ts">
  import Badge from '../../components/Badge.svelte';
  import Seg from '../../components/Seg.svelte';
  import ConfirmDialog from '../../components/ConfirmDialog.svelte';
  import * as api from '../../lib/api/endpoints';
  import { errorMessage, revealExport } from '../../lib/api/client';
  import type { ExperimentCategory, ExperimentDetail, ExperimentList } from '../../lib/api/types';
  import { awaitTask } from '../../lib/state/tasks';
  import { nav } from '../../lib/state/nav.svelte';
  import { notifier } from '../../lib/state/notify.svelte';
  import {
    ACTION_LABEL, categoryLabel, categoryTone, durationBetween, END_REASON, fmt, fmtClock, fmtMass, fmtShort, fmtTime, TYPE_SHORT,
    TYPE_TONE,
  } from '../../lib/format';

  let { online }: { online: boolean } = $props();

  let filter = $state<'all' | ExperimentCategory>('all');
  let query = $state('');
  let list = $state<ExperimentList | null>(null);
  let selectedId = $state<number | null>(nav.experimentId);
  let detail = $state<ExperimentDetail | null>(null);
  let error = $state('');
  let exporting = $state<string | null>(null);
  let confirmDelete = $state(false);

  async function load() {
    try {
      list = await api.listExperiments({ category: filter === 'all' ? null : filter, q: query.trim() || undefined, limit: 300 });
      error = '';
      if (selectedId === null || !list.experiments.some((e) => e.id === selectedId)) selectedId = list.experiments[0]?.id ?? null;
    } catch (e) { error = errorMessage(e); }
  }

  async function loadDetail(id: number | null) {
    if (id === null) { detail = null; return; }
    try { detail = await api.getExperiment(id); } catch (e) { error = errorMessage(e); }
  }

  let searchTimer: ReturnType<typeof setTimeout> | undefined;
  $effect(() => {
    void filter; void query;
    clearTimeout(searchTimer);
    if (online) searchTimer = setTimeout(load, 200);
  });
  $effect(() => { void loadDetail(selectedId); });

  const total = $derived(list ? Object.values(list.counts).reduce((a, b) => a + b, 0) : 0);
  const kpiText = $derived.by(() => {
    const k = detail?.kpi;
    if (!k) return '—';
    const word = k.degree_kind === 'oxidation' ? '氧化度' : '还原度';
    return `终态${word} ${fmt(k.final_degree_pct, 1)}% · t₄₀ ${fmt(k.time_to_40_min, 1)} min · t₆₀ ${fmt(k.time_to_60_min, 1)} min${k.best_fit ? ` · ${k.best_fit.name} R² ${k.best_fit.r2.toFixed(3)}` : ''}`;
  });

  async function exportData(kind: 'measurements_csv' | 'measurements_xlsx') {
    if (!detail) return;
    exporting = kind;
    try {
      const task = await awaitTask(await api.startExport(detail.id, kind));
      if (task.status === 'completed' && task.result?.path) {
        notifier.push('ok', '导出完成', task.result.filename);
        await revealExport(task.result.path).catch(() => undefined);
      } else notifier.push('danger', '导出失败', task.error ?? '');
    } catch (e) { notifier.push('danger', '导出失败', errorMessage(e)); } finally { exporting = null; }
  }

  async function remove() {
    if (!detail) return;
    try {
      await api.deleteExperiment(detail.id);
      notifier.push('ok', '实验已删除', detail.code);
      selectedId = null;
      await load();
    } catch (e) { notifier.push('danger', '删除失败', errorMessage(e)); } finally { confirmDelete = false; }
  }
</script>

<div class="page-head">
  <div>
    <h1>历史实验</h1>
    <p>每次实验归档后只读：原始采样、配方版本快照、事件与报警、操作记录一并保存。待核查的实验需先在分析与归档中完成复核。</p>
  </div>
  <div class="actions">
    {#if list?.counts.pending}<Badge tone="warn">{list.counts.pending} 次待核查</Badge>{/if}
    <Badge>共 {total} 次 · 已归档 {list?.counts.archived ?? 0} · 已中止 {list?.counts.aborted ?? 0}</Badge>
  </div>
</div>
{#if error}<div class="callout danger">{error}</div>{/if}

<section class="card row" style="align-items:flex-end;gap:14px">
  <label class="field" style="flex:1 1 260px"><span>搜索 · 实验编号 / 样品 / 配方</span><input bind:value={query} placeholder="例如 A-19 或 RKA-2026-1101-019" /></label>
  <div class="field"><span>状态</span>
    <Seg label="状态" value={filter} onselect={(id) => (filter = id as typeof filter)} options={[
      { id: 'all', label: '全部' }, { id: 'archived', label: '已归档' }, { id: 'pending', label: '待核查' }, { id: 'aborted', label: '已中止' },
      { id: 'running', label: '运行中' },
    ]} /></div>
</section>

<div class="grid main-side">
  <section class="card flush">
    <div class="table-wrap" style="max-height:68vh">
      <table class="data">
        <thead><tr><th>实验编号</th><th>样品</th><th>配方 · 版本</th><th>类型</th><th>开始</th><th>时长</th><th class="num">t₄₀ min</th><th class="num">终态 %</th><th>状态</th></tr></thead>
        <tbody>
          {#each list?.experiments ?? [] as row (row.id)}
            <tr class="pick" aria-selected={row.id === selectedId} onclick={() => (selectedId = row.id)}>
              <td class="mono nowrap">{row.code}</td>
              <td>{row.sample_name ?? row.name}</td>
              <td>{row.recipe_name ?? '—'}{row.recipe_version ? ` v${row.recipe_version}` : ''}</td>
              <td>{#if row.experiment_type}<Badge tone={TYPE_TONE[row.experiment_type]}>{TYPE_SHORT[row.experiment_type]}</Badge>{:else}—{/if}</td>
              <td class="mono nowrap">{fmtShort(row.started_at)}</td>
              <td class="mono">{durationBetween(row.started_at, row.finished_at)}</td>
              <td class="num mono">{fmt(row.kpi?.time_to_40_min, 1)}</td>
              <td class="num mono">{fmt(row.kpi?.final_degree_pct, 1)}</td>
              <td><Badge tone={categoryTone[row.category]}>{categoryLabel[row.category]}</Badge></td>
            </tr>
          {:else}<tr><td colspan="9"><div class="empty"><strong>没有匹配的实验</strong>调整搜索或状态筛选。</div></td></tr>{/each}
        </tbody>
      </table>
    </div>
    <p class="tiny soft" style="padding:10px 14px;margin:0;border-top:1px solid var(--line-soft)">显示 {list?.experiments.length ?? 0} 条 · 点击行查看详情 · 指标在归档时冻结</p>
  </section>

  <section class="card">
    {#if detail}
      <div class="row between" style="margin-bottom:6px"><h2 class="mono">{detail.code}</h2><Badge tone={categoryTone[detail.category]}>{categoryLabel[detail.category]}</Badge></div>
      <p class="small soft" style="margin-bottom:12px">{detail.sample_name ?? detail.name} · {detail.recipe_name ?? '—'}{detail.recipe_version ? ` v${detail.recipe_version}` : ''} · {detail.experiment_type ? TYPE_SHORT[detail.experiment_type] : '—'}</p>
      <dl class="kv">
        <dt>开始 / 时长</dt><dd>{fmtTime(detail.started_at)} · {durationBetween(detail.started_at, detail.finished_at)}</dd>
        <dt>初始 / 终态质量</dt><dd class="mono">{fmtMass(detail.initial_mass_g)} → {fmtMass(detail.final_mass_g)} g</dd>
        <dt>关键指标</dt><dd>{kpiText}</dd>
        <dt>结束方式</dt><dd>{END_REASON[detail.end_reason ?? ''] ?? detail.status}{detail.end_detail && detail.end_reason !== 'completed' ? `：${detail.end_detail}` : ''}</dd>
        <dt>安全完成</dt><dd>{detail.purge_required_s ? `吹扫 ${Math.round(detail.purge_done_s ?? 0)} / ${Math.round(detail.purge_required_s)} s · 炉温 ${fmt(detail.final_temperature_c, 0)} ℃` : '—'}</dd>
        <dt>数据</dt><dd>{detail.measurement_count} 点 · 报警 {detail.alarms.length} 条</dd>
        <dt>操作者</dt><dd>{detail.operator ?? '—'}{detail.archived_by ? ` · 归档 ${detail.archived_by} ${fmtShort(detail.archived_at)}` : ''}</dd>
      </dl>
      {#if detail.category === 'pending'}
        <div class="callout warn" style="margin-top:12px">尚未归档：使用上限策略仍锁定，不能开始下一次实验。请到分析与归档完成复核。</div>
      {:else if detail.archive_note}
        <div class={`callout ${detail.category === 'aborted' ? 'danger' : 'good'}`} style="margin-top:12px">复核备注：{detail.archive_note}</div>
      {/if}
      <h3 style="margin:14px 0 4px">事件摘要</h3>
      <div class="events" style="max-height:220px">
        {#each detail.events.slice(0, 12) as event}
          <div class="ev"><time>{fmtClock(event.created_at)}</time><strong>{ACTION_LABEL[event.action] ?? event.action}</strong><span>{event.detail}{event.reason ? ` · 原因：${event.reason}` : ''}</span></div>
        {:else}<p class="soft small">没有事件记录（旧版本实验）。</p>{/each}
      </div>
      <div class="stack tight" style="margin-top:12px">
        {#if detail.category === 'pending'}<button class="btn primary" type="button" onclick={() => nav.go('analysis', detail!.id)}>前往分析与归档</button>
        {:else if detail.category !== 'running'}<button class="btn" type="button" onclick={() => nav.go('analysis', detail!.id)}>查看分析（{detail.category === 'archived' || detail.category === 'aborted' ? '只读' : ''}）</button>{/if}
        <div class="row">
          <button class="btn sm" type="button" disabled={!online || exporting !== null || !detail.measurement_count} onclick={() => exportData('measurements_csv')}>{exporting === 'measurements_csv' ? '导出中…' : `导出 CSV${detail.category === 'aborted' ? '（不完整）' : ''}`}</button>
          <button class="btn sm" type="button" disabled={!online || exporting !== null || !detail.measurement_count} onclick={() => exportData('measurements_xlsx')}>{exporting === 'measurements_xlsx' ? '导出中…' : '导出 Excel'}</button>
          {#if detail.review_state === 'archived'}<button class="btn sm" type="button" onclick={() => nav.go('reports')}>生成报告</button>{/if}
          {#if detail.alarms.length}<button class="btn sm" type="button" onclick={() => nav.go('alarms')}>查看报警</button>{/if}
          <span class="fill"></span>
          <button class="btn sm danger-ghost" type="button" disabled={!online || detail.category === 'running'} onclick={() => (confirmDelete = true)}>删除</button>
        </div>
      </div>
    {:else}
      <div class="empty"><strong>选择一条实验</strong>右侧会显示详情、事件摘要与可用操作。</div>
    {/if}
  </section>
</div>

<ConfirmDialog open={confirmDelete} tone="danger" title="删除实验？" confirmLabel="永久删除"
  message={`将删除 ${detail?.code ?? ''} 的原始采样、报警与报告记录，无法撤销。操作审计中的记录保留。`}
  onconfirm={remove} oncancel={() => (confirmDelete = false)} />
