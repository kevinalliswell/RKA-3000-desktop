<script lang="ts">
  import Badge from '../../components/Badge.svelte';
  import * as api from '../../lib/api/endpoints';
  import { errorMessage, revealExport } from '../../lib/api/client';
  import type { ReportItem } from '../../lib/api/types';
  import { awaitTask } from '../../lib/state/tasks';
  import { notifier } from '../../lib/state/notify.svelte';
  import { prefs } from '../../lib/state/prefs.svelte';
  import { nav } from '../../lib/state/nav.svelte';
  import { categoryLabel, categoryTone, fmtPct, fmtShort, TYPE_SHORT, TYPE_TONE } from '../../lib/format';

  let { online }: { online: boolean } = $props();
  let items = $state<ReportItem[]>([]);
  let busy = $state<number | null>(null);
  let error = $state('');

  async function load() {
    try { items = await api.listReports(); error = ''; } catch (e) { error = errorMessage(e); }
  }
  $effect(() => { if (online) void load(); });

  async function generate(item: ReportItem) {
    busy = item.id;
    try {
      const task = await awaitTask(await api.startReport(item.id, prefs.operator || undefined));
      if (task.status === 'completed') notifier.push('ok', `报告 v${task.result?.version} 已生成`, String(task.result?.filename ?? ''));
      else notifier.push('danger', '报告生成失败', task.error ?? '');
      await load();
    } catch (e) { notifier.push('danger', '报告生成失败', errorMessage(e)); } finally { busy = null; }
  }

  async function open(path: string) {
    try { if (!(await revealExport(path))) notifier.push('info', '文件位置', path); } catch (e) { notifier.push('danger', '无法打开位置', errorMessage(e)); }
  }
  const pendingCount = $derived(items.filter((i) => i.can_generate && !i.latest_report).length);
</script>

<div class="page-head">
  <div>
    <h1>报告中心</h1>
    <p>只有已归档的实验能生成报告。报告引用归档时冻结的数据与配方快照；重新生成会产生新版本，旧版本保留。</p>
  </div>
  <div class="actions"><Badge tone={pendingCount ? 'warn' : 'good'}>{pendingCount ? `${pendingCount} 份待生成` : '无待生成报告'}</Badge></div>
</div>
{#if error}<div class="callout danger">{error}</div>{/if}

<div class="grid main-side">
  <section class="card flush">
    <div class="card-head"><h2>最近实验</h2><span class="tiny soft">运行中与待核查不可生成</span></div>
    <div class="table-wrap">
      <table class="data">
        <thead><tr><th>实验编号</th><th>样品 · 配方 · 结果</th><th>状态</th><th>报告版本</th><th>操作</th></tr></thead>
        <tbody>
          {#each items as item}
            <tr>
              <td class="mono nowrap">{item.code}</td>
              <td>{#if item.experiment_type}<Badge tone={TYPE_TONE[item.experiment_type]}>{TYPE_SHORT[item.experiment_type]}</Badge>{/if}
                {item.sample_name ?? item.name} · {item.recipe_name ?? '—'}{item.recipe_version ? ` v${item.recipe_version}` : ''}
                {#if item.kpi}<span class="soft"> · 终态 {fmtPct(item.kpi.final_degree_pct)}%</span>{/if}
                <div class="tiny soft">{item.archived_at ? `归档 ${fmtShort(item.archived_at)}` : `开始 ${fmtShort(item.started_at)}`}</div></td>
              <td><Badge tone={categoryTone[item.category]}>{categoryLabel[item.category]}</Badge></td>
              <td class="mono nowrap">{item.latest_report ? `v${item.latest_report.version} · ${fmtShort(item.latest_report.created_at)}` : '—'}</td>
              <td class="nowrap">
                {#if item.category === 'pending'}<button class="btn sm" type="button" onclick={() => nav.go('analysis', item.id)}>去归档</button>
                {:else if item.can_generate}
                  <button class="btn sm" type="button" disabled={busy !== null} onclick={() => generate(item)}>{#if busy === item.id}<span class="spinner" aria-hidden="true"></span>生成中…{:else}{item.latest_report ? '重新生成' : '生成报告'}{/if}</button>
                  {#if item.latest_report}<button class="btn sm" type="button" onclick={() => open(item.latest_report!.path)}>打开位置</button>{/if}
                {:else}<span class="tiny soft">{item.category === 'running' ? '归档后可生成' : '缺少试样参数'}</span>{/if}
              </td>
            </tr>
          {:else}<tr><td colspan="5"><div class="empty">暂无实验</div></td></tr>{/each}
        </tbody>
      </table>
    </div>
  </section>
  <section class="card">
    <h2 style="margin-bottom:8px">报告内容 · Excel</h2>
    <dl class="kv">
      <dt>报告</dt><dd>编号、样品、操作者、配方与版本、起止时间、结束方式、试样参数、测定区间、关键指标、复核备注与归档人</dd>
      <dt>数据</dt><dd>还原度 / 氧化度–时间与速率，含曲线</dd>
      <dt>模型拟合</dt><dd>界面反应、产物层扩散、Avrami 的 k、n 与 R²</dd>
      <dt>报警与事件</dt><dd>全部报警及确认说明</dd>
      <dt>操作记录</dt><dd>该实验的审计记录，含结果</dd>
    </dl>
    <p class="tiny soft" style="margin-top:10px">文件保存在导出目录，名称形如 RKA-YYYY-MMDD-NNN_report_v2.xlsx。</p>
  </section>
</div>
