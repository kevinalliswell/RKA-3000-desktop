<script lang="ts">
  import { onMount } from 'svelte'
  import { ws, num } from '../lib/sim.svelte'
  let tab = $state(0)
  let selected = $state(0)
  let result = $state<Record<string, unknown> | null>(null)
  onMount(() => { if (ws.selectedRun) selected = ws.selectedRun.id })
  async function calculate() { try { result = await ws.request('sim_analysis', { id: selected }) } catch { /* shown */ } }
</script>
<p class="lead">分析仅纳入质量标记有效的仿真采样。计算依据和方法限制随结果显示。</p>
<div class="tabs"><button class:active={tab === 0} onclick={() => tab = 0}>指标工作台</button><button class:active={tab === 1} onclick={() => tab = 1}>计算依据</button></div>
{#if tab === 0}<section class="panel"><div class="panel-header"><h2>选择实验</h2></div><div class="panel-body"><div class="action-row"><select aria-label="选择分析实验" bind:value={selected}><option value={0}>选择实验</option>{#each ws.history as run}<option value={run.id}>#{run.id} · {run.name}</option>{/each}</select><button class="button primary" disabled={!selected} onclick={calculate}>计算有效数据指标</button></div>{#if result}{#if result.valid}<div class="metric-grid"><div class="metric"><div class="metric-label">有效采样</div><div class="metric-value">{result.sample_count as number}</div></div><div class="metric"><div class="metric-label">末次质量</div><div class="metric-value">{num(result.final_weight_g as number,3)} <em>g</em></div></div><div class="metric"><div class="metric-label">质量变化</div><div class="metric-value">{num(result.weight_change_pct as number,2)} <em>%</em></div></div><div class="metric"><div class="metric-label">最高温度</div><div class="metric-value">{num(result.max_temperature_c as number,1)} <em>℃</em></div></div></div><div class="callout warn">{result.method as string}{result.review_required ? ' · 当前结果待人工复核' : ''}</div>{:else}<div class="callout warn">无法计算：{result.reason as string}</div>{/if}{/if}</div></section>{/if}
{#if tab === 1}<section class="panel"><div class="panel-header"><h2>方法与质量边界</h2></div><div class="panel-body"><p>对同一实验按采样顺序筛选质量标记为“有效仿真”的记录，计算首末质量差与相对变化率；温度取有效采样最大值。</p><p>过期、离线和不稳定数据不参与计算。该指标仅用于仿真流程与趋势验证，不能当作化学计量还原度、氧化率或正式试验结论。</p><p>报告会附带采样数量、数据来源和复核状态。</p></div></section>{/if}
