<script lang="ts">
  import { onMount } from 'svelte'
  import { invoke } from '@tauri-apps/api/core'
  import { save } from '@tauri-apps/plugin-dialog'
  import { ws } from '../lib/sim.svelte'
  let tab = $state(0)
  let selected = $state(0)
  let reportHtml = $state('')
  onMount(() => { if (ws.selectedRun) selected = ws.selectedRun.id })
  async function generate() {
    try { reportHtml = (await ws.request<{html:string}>('sim_report', { id: selected })).html; tab = 1 } catch { /* shown */ }
  }
  async function exportHtml() {
    if (!reportHtml) return
    try {
      const path = await save({ defaultPath: `RKA-3000-${selected}.html`, filters: [{ name: 'HTML 技术记录', extensions: ['html'] }] })
      if (path) { await invoke('write_report_html', { path, html: reportHtml }); ws.notice = `技术记录已导出：${path}` }
    } catch (cause) { ws.error = cause instanceof Error ? cause.message : String(cause) }
  }
  async function printPdf() {
    if (!reportHtml) return
    try {
      localStorage.setItem('rka-report-print', reportHtml)
      await invoke('open_report_window')
      ws.notice = '已打开独立报告窗口，请使用其中的“打印 / 保存 PDF”按钮'
    } catch (cause) { ws.error = cause instanceof Error ? cause.message : String(cause) }
  }
</script>
<p class="lead">Python 生成技术记录 HTML；PDF 通过系统打印对话框保存。仿真方法限制与待复核状态写入报告。</p>
<div class="tabs">{#each ['报告列表','报告预览','字段与审签'] as label,i}<button class:active={tab === i} onclick={() => tab = i}>{label}</button>{/each}</div>
{#if tab === 0}<section class="panel"><div class="panel-header"><h2>选择实验</h2></div><div class="panel-body"><div class="action-row"><select aria-label="选择报告实验" bind:value={selected}><option value={0}>选择实验</option>{#if ws.selectedRun && !ws.history.some(run => run.id === ws.selectedRun?.id)}<option value={ws.selectedRun.id}>#{ws.selectedRun.id} · {ws.selectedRun.name} · {ws.selectedRun.state}</option>{/if}{#each ws.history as run}<option value={run.id}>#{run.id} · {run.name} · {run.state}</option>{/each}</select><button class="button primary" disabled={!selected} onclick={generate}>生成技术记录</button></div><p class="muted">列表显示最近 50 条；更早的实验可从历史详情进入。非归档实验会明确标记为待复核，生成报告不更改实验状态。</p></div></section>{/if}
{#if tab === 1}<section class="panel"><div class="panel-header"><h2>技术记录预览</h2><div class="action-row"><button class="button secondary" disabled={!reportHtml} onclick={exportHtml}>导出 HTML</button><button class="button primary" disabled={!reportHtml} onclick={printPdf}>打印 / 保存 PDF</button></div></div>{#if reportHtml}<iframe class="report-preview" title="技术记录预览" srcdoc={reportHtml}></iframe>{:else}<div class="empty-state"><h3>尚未生成报告</h3><button class="button secondary" onclick={() => tab = 0}>选择实验</button></div>{/if}</section>{/if}
{#if tab === 2}<section class="panel"><div class="panel-header"><h2>字段与审签</h2></div><div class="panel-body"><p>技术记录包含实验编号、样品、配方版本快照、开始和结束时间、有效采样数量、首末质量变化、复核结论、来源及生成时间。</p><p>人工审签在导出后的正式技术记录流程中完成。未归档数据会标注“待复核”；仿真计算只用于界面与业务验证。</p></div></section>{/if}
