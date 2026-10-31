<script lang="ts">
  import { ws, type Recipe } from '../lib/sim.svelte'
  import Confirm from '../components/Confirm.svelte'
  let name = $state('')
  let sampleName = $state('')
  let mass = $state(1)
  let recipeId = $state(0)
  let checks = $state({ gas: false, exhaust: false, balance: false, operator: false })
  let result = $state<{ok: boolean; reasons: string[]; recipe: Recipe; checked_at: string} | null>(null)
  let confirm = $state(false)
  let step = $state(0)
  let inert = $derived(ws.selectedRecipe?.id === recipeId && ws.selectedRecipe.stages?.some(s => s.flows.ar > 0) ? 'Ar' : 'N₂')
  $effect(() => { name; sampleName; mass; recipeId; checks.gas; checks.exhaust; checks.balance; checks.operator; result = null })
  async function validate() {
    try { result = await ws.request('sim_preflight', { recipe_id: recipeId, sample: { name: sampleName, initial_mass_g: Number(mass) }, checks }); step = 2 } catch { /* shown */ }
  }
  async function start() {
    confirm = false
    try { await ws.request('sim_run_start', { name, recipe_id: recipeId, sample: { name: sampleName, initial_mass_g: Number(mass) }, checks }); ws.notice = '仿真实验已启动，进入惰性置换'; await ws.load(); ws.navigate('current') } catch { /* shown */ }
  }
</script>
<p class="lead">填写样品和配方，完成四项人工确认。预检仅验证仿真流程，不代替现场联锁检查。</p>
<div class="tabs" role="tablist" aria-label="准备步骤">{#each ['样品信息','选择配方','启动检查'] as label, i}<button class:active={step === i} role="tab" aria-selected={step === i} onclick={() => step = i}>{i+1}. {label}</button>{/each}</div>
{#if step === 0}<section class="panel"><div class="panel-header"><h2>样品信息</h2></div><div class="panel-body form-grid"><label>实验名称<input bind:value={name} placeholder="例如：矿样 A 还原实验" /></label><label>样品名称<input bind:value={sampleName} placeholder="样品编号或名称" /></label><label>初始质量 / g<input type="number" min="0.001" step="0.001" bind:value={mass}/></label></div><div class="panel-actions"><button class="button primary" onclick={() => step = 1}>下一步：选择配方</button></div></section>{/if}
{#if step === 1}<section class="panel"><div class="panel-header"><h2>实验配方与气源</h2><button class="text-button" onclick={() => ws.navigate('recipes')}>管理配方</button></div><div class="panel-body"><label>选择版本化配方<select bind:value={recipeId} onchange={() => { if (recipeId) void ws.loadRecipe(recipeId) }}><option value={0}>请选择</option>{#each ws.recipes as recipe}<option value={recipe.id}>{recipe.name} v{recipe.version} · {recipe.kind === 'reduction' ? '还原' : '氧化'}</option>{/each}</select></label>{#if ws.selectedRecipe?.id === recipeId}<div class="detail-grid preflight-recipe"><div><span>实验类型</span><strong>{ws.selectedRecipe.kind === 'reduction' ? '还原' : '氧化'}</strong></div><div><span>惰性气源</span><strong>{inert} · MFC-01</strong></div><div><span>阶段数</span><strong>{ws.selectedRecipe.stages?.length ?? 0}</strong></div></div>{/if}<p class="muted">气源由配方阶段锁定，启动前核对钢瓶标签与 MFC 介质标定。启动后保存不可变配方快照。</p></div><div class="panel-actions"><button class="button secondary" onclick={() => step = 0}>上一步</button><button class="button primary" onclick={() => step = 2}>下一步：启动检查</button></div></section>{/if}
{#if step === 2}<section class="panel"><div class="panel-header"><h2>启动前人工确认</h2></div><div class="panel-body check-list"><label><input type="checkbox" bind:checked={checks.gas}/> 气源和介质标签已核对</label><label><input type="checkbox" bind:checked={checks.exhaust}/> 排风和尾气处理已确认</label><label><input type="checkbox" bind:checked={checks.balance}/> 天平和样品放置已确认</label><label><input type="checkbox" bind:checked={checks.operator}/> 操作人员在场并了解紧急处置</label></div><div class="panel-actions"><button class="button secondary" onclick={() => step = 1}>上一步</button><button class="button secondary" onclick={validate}>运行预检</button><button class="button primary" disabled={!result?.ok} onclick={() => confirm = true}>启动仿真实验</button></div></section>
  {#if result}<div class:danger={!result.ok} class="callout" role="status">{result.ok ? '预检通过，可以启动仿真实验。' : `预检未通过：${result.reasons.join('；')}`}</div>{/if}
{/if}
{#if confirm}<Confirm title="启动仿真实验" detail="将使用当前配方版本建立快照，随后进入惰性置换。请确认样品、气源及排风条件。" confirmText="确认启动" oncancel={() => confirm = false} onconfirm={start}/>{/if}
