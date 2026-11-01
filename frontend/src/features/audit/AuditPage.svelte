<script lang="ts">
  import Badge from '../../components/Badge.svelte';
  import Seg from '../../components/Seg.svelte';
  import * as api from '../../lib/api/endpoints';
  import { errorMessage } from '../../lib/api/client';
  import type { AuditRecord } from '../../lib/api/types';
  import { awaitTask } from '../../lib/state/tasks';
  import { notifier } from '../../lib/state/notify.svelte';
  import { ACTION_LABEL, AUDIT_CATEGORY, fmtShort, RESULT_CODES } from '../../lib/format';

  let { online }: { online: boolean } = $props();

  let rows = $state<AuditRecord[]>([]);
  let category = $state('all');
  let experiment = $state('');
  let actor = $state('');
  let error = $state('');
  let exporting = $state(false);

  const experimentId = $derived(/^\d+$/.test(experiment.trim()) ? Number(experiment.trim()) : null);

  async function load() {
    try {
      rows = await api.listAudit({ limit: 500, experimentId, category: category === 'all' ? null : category, actor: actor.trim() || undefined });
      error = '';
    } catch (e) { error = errorMessage(e); }
  }

  $effect(() => { void category; void experimentId; void actor; if (online) void load(); });

  async function exportCsv() {
    exporting = true;
    try {
      const task = await awaitTask(await api.exportAudit(experimentId, category === 'all' ? null : category));
      if (task.status === 'completed') notifier.push('ok', '审计已导出', String(task.result?.path ?? ''));
      else notifier.push('danger', '导出失败', task.error ?? '');
    } catch (e) { notifier.push('danger', '导出失败', errorMessage(e)); } finally { exporting = false; }
  }

  const codes = (result: string | null) => (result ?? '').split(',').filter(Boolean);
</script>

<div class="page-head">
  <div>
    <h1>操作审计</h1>
    <p>控制类操作记录操作者、对象、原因与结果（受理 → 回读验证 → 生效）。属于实验的记录随实验保存，只读，不会被清理。</p>
  </div>
  <div class="actions"><Badge>只读 · 不可删除 · 随实验归档</Badge>
    <button class="btn" type="button" disabled={!online || exporting || !rows.length} onclick={exportCsv}>{#if exporting}<span class="spinner" aria-hidden="true"></span>{/if}导出审计 CSV</button></div>
</div>

{#if error}<div class="callout danger">{error}</div>{/if}
<section class="card row" style="align-items:flex-end;gap:14px">
  <label class="field" style="flex:1 1 160px"><span>实验 ID</span><input class="mono" bind:value={experiment} placeholder="全部" inputmode="numeric" /></label>
  <label class="field" style="flex:1 1 160px"><span>操作者</span><input bind:value={actor} placeholder="全部" /></label>
  <div class="field"><span>操作类型</span>
    <Seg label="操作类型" value={category} onselect={(id) => (category = id)} options={[
      { id: 'all', label: '全部' }, { id: 'control', label: '控制命令' }, { id: 'safety', label: '安全与报警' },
      { id: 'config', label: '配置变更' }, { id: 'data', label: '数据与归档' },
    ]} /></div>
</section>

<section class="card flush">
  <div class="table-wrap" style="max-height:65vh">
    <table class="data" style="min-width:900px">
      <thead><tr><th>时间</th><th>操作者</th><th>操作</th><th>对象 / 参数</th><th>原因</th><th>结果</th><th>实验</th></tr></thead>
      <tbody>
        {#each rows as row}
          <tr>
            <td class="mono nowrap">{fmtShort(row.created_at)}</td>
            <td class="nowrap">{row.actor === 'system' ? '系统' : row.actor}</td>
            <td class="nowrap"><strong>{ACTION_LABEL[row.action] ?? row.action}</strong><div class="tiny soft">{AUDIT_CATEGORY[row.category ?? ''] ?? ''}</div></td>
            <td>{row.detail}</td>
            <td class="soft">{row.reason ?? '—'}</td>
            <td><div class="row" style="gap:4px">{#each codes(row.result) as code}<Badge tone={RESULT_CODES[code]?.tone ?? ''}>{RESULT_CODES[code]?.label ?? code}</Badge>{:else}<span class="soft">—</span>{/each}</div></td>
            <td class="mono">{row.experiment_id ?? '—'}</td>
          </tr>
        {:else}<tr><td colspan="7"><div class="empty"><strong>没有记录</strong>调整筛选条件试试。</div></td></tr>{/each}
      </tbody>
    </table>
  </div>
  <p class="tiny soft" style="padding:10px 14px;margin:0;border-top:1px solid var(--line-soft)">显示 {rows.length} 条（最多 500）· 系统自动动作以“系统”为操作者 · 操作者为本机填写的姓名，未经账号认证</p>
</section>

<div class="callout">结果说明：<strong>已受理</strong> = 软件校验通过并下发；<strong>回读一致</strong> = MFC 设定回读与命令一致（±2% 或 0.01 L/min）；<strong>已生效</strong> = 进入运行状态并记录事件。回读不一致时命令不生效并回退到配方值；紧急停气不等待回读，失败时记录报警并提示现场处置。</div>
