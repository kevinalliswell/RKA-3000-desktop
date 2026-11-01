<script lang="ts">
  import { onMount } from 'svelte';
  import ConfirmDialog from '../../components/ConfirmDialog.svelte';
  import * as api from '../../lib/api/endpoints';
  import type { RecipeStep, RecipeSummary } from '../../lib/api/types';
  import { notifier } from '../../lib/state/notify.svelte';
  import { errorMessage } from '../../lib/api/client';
  import { downloadText, fmtTime } from '../../lib/format';

  let { online, runActive }: { online: boolean; runActive: boolean } = $props();

  type Draft = { name: string; steps: Partial<RecipeStep>[] };
  const blankStep = (): Partial<RecipeStep> => ({ target_temp_c: 900, ramp_rate_cpm: 10, hold_seconds: 600, n2_lpm: 8, h2_lpm: 1, co_lpm: 0.8, notes: '' });

  let recipes: RecipeSummary[] = $state([]);
  let selectedId = $state<number | null>(null);
  let draft: Draft = $state({ name: '', steps: [blankStep()] });
  let loading = $state(false);
  let saving = $state(false);
  let error = $state('');
  let confirmDelete = $state(false);
  let fileInput: HTMLInputElement | undefined = $state();

  async function load(keep?: number | null) {
    loading = true;
    try {
      recipes = await api.listRecipes();
      error = '';
      const target = keep ?? selectedId;
      if (target && recipes.some((r) => r.id === target)) await select(target);
      else if (recipes[0] && !selectedId) await select(recipes[0].id);
      else if (!recipes.length) { selectedId = null; draft = { name: '', steps: [blankStep()] }; }
    } catch (e) { error = errorMessage(e); } finally { loading = false; }
  }

  async function select(id: number) {
    try {
      const recipe = await api.getRecipe(id);
      selectedId = id;
      draft = { name: recipe.name, steps: recipe.steps.map((s) => ({ ...s })) };
      error = '';
    } catch (e) { error = errorMessage(e); }
  }

  function newRecipe() { selectedId = null; draft = { name: '', steps: [blankStep()] }; error = ''; }
  function addStep() { draft.steps = [...draft.steps, { ...(draft.steps.at(-1) ?? blankStep()), notes: '' }]; }
  function removeStep(index: number) { if (draft.steps.length > 1) draft.steps = draft.steps.filter((_, i) => i !== index); }
  function moveStep(index: number, delta: number) {
    const target = index + delta;
    if (target < 0 || target >= draft.steps.length) return;
    const steps = [...draft.steps];
    [steps[index], steps[target]] = [steps[target]!, steps[index]!];
    draft.steps = steps;
  }

  // Immediate feedback only; Python validation is authoritative.
  const localErrors = $derived.by(() => {
    const errors: string[] = [];
    if (!draft.name.trim()) errors.push('请填写配方名称');
    draft.steps.forEach((s, i) => {
      if (s.target_temp_c === undefined || Number(s.target_temp_c) < 0 || Number(s.target_temp_c) > 1600) errors.push(`第 ${i + 1} 步目标温度须在 0–1600 ℃`);
      if (Number(s.hold_seconds) < 0) errors.push(`第 ${i + 1} 步保温时间不能为负`);
    });
    return errors;
  });

  async function save() {
    if (saving) return;
    saving = true;
    try {
      const recipe = selectedId ? await api.updateRecipe(selectedId, draft.name, draft.steps) : await api.createRecipe(draft.name, draft.steps);
      notifier.push('ok', selectedId ? '配方已更新' : '配方已保存', `#${recipe.id} ${recipe.name}`);
      await load(recipe.id);
    } catch (e) { error = errorMessage(e); } finally { saving = false; }
  }

  async function remove() {
    confirmDelete = false;
    if (!selectedId) return;
    try {
      await api.deleteRecipe(selectedId);
      notifier.push('ok', '配方已删除');
      selectedId = null;
      await load(null);
    } catch (e) { error = errorMessage(e); }
  }

  async function exportCurrent() {
    if (!selectedId) return;
    try {
      const document = await api.exportRecipe(selectedId);
      downloadText(`recipe-${selectedId}-${document.name}.json`, JSON.stringify(document, null, 2));
    } catch (e) { error = errorMessage(e); }
  }

  async function importFile(file: File) {
    try {
      const document = JSON.parse(await file.text()) as unknown;
      const recipe = await api.importRecipe(document);
      notifier.push('ok', '配方已导入', `#${recipe.id} ${recipe.name}`);
      await load(recipe.id);
    } catch (e) { error = errorMessage(e); }
  }

  onMount(() => { void load(); });
  $effect(() => { if (online) void load(); });
</script>

<div class="grid sidebar">
  <section class="panel">
    <div class="panel-head"><h2>配方列表</h2><div class="row"><button class="btn sm" type="button" onclick={() => load()} disabled={!online || loading}>刷新</button><button class="btn sm accent" type="button" onclick={newRecipe}>新建</button></div></div>
    <div class="panel-body stack">
      <div class="row">
        <button class="btn sm" type="button" onclick={() => fileInput?.click()} disabled={!online}>导入 JSON</button>
        <button class="btn sm" type="button" onclick={exportCurrent} disabled={!online || !selectedId}>导出 JSON</button>
        <input class="sr-only" type="file" accept=".json,application/json" bind:this={fileInput} onchange={(e) => { const f = e.currentTarget.files?.[0]; if (f) void importFile(f); e.currentTarget.value = ''; }} />
      </div>
      {#if recipes.length}
        <div class="table-wrap"><table><thead><tr><th>#</th><th>名称</th><th>更新时间</th></tr></thead><tbody>
          {#each recipes as recipe}
            <tr class="clickable" aria-selected={recipe.id === selectedId} onclick={() => select(recipe.id)}><td class="mono">{recipe.id}</td><td>{recipe.name}</td><td class="mono small">{fmtTime(recipe.updated_at)}</td></tr>
          {/each}
        </tbody></table></div>
      {:else}<div class="empty"><strong>还没有配方</strong>点击「新建」创建第一个多步骤配方，或导入 JSON 配方文件。</div>{/if}
    </div>
  </section>

  <section class="panel">
    <div class="panel-head"><h2>{selectedId ? `编辑配方 #${selectedId}` : '新建配方'}</h2>
      <div class="row">
        {#if selectedId}<button class="btn sm danger" type="button" onclick={() => (confirmDelete = true)} disabled={!online || runActive}>删除</button>{/if}
        <button class="btn primary" type="button" onclick={save} disabled={!online || saving || localErrors.length > 0 || (runActive && !!selectedId)}>
          {#if saving}<span class="spinner" aria-hidden="true"></span>{/if}{selectedId ? '更新配方' : '保存新配方'}
        </button>
      </div>
    </div>
    <div class="panel-body stack">
      {#if runActive}<div class="notice" data-tone="info">实验运行中：可以查看和新建配方，但正在使用的配方不能修改或删除。</div>{/if}
      {#if error}<div class="notice" data-tone="danger" role="alert"><div><div class="title">操作未完成</div><div>{error}</div></div><button class="close" type="button" aria-label="关闭" onclick={() => (error = '')}>×</button></div>{/if}
      <label class="field"><span>配方名称</span><input bind:value={draft.name} maxlength="100" placeholder="例如：高温还原-标准流程" aria-invalid={!draft.name.trim()} /></label>
      <div class="table-wrap" style="max-height:none"><table>
        <thead><tr><th>步骤</th><th>目标温度 ℃</th><th>升温速率 ℃/min</th><th>保温 s</th><th>N₂ L/min</th><th>H₂ L/min</th><th>CO L/min</th><th>备注</th><th></th></tr></thead>
        <tbody>
          {#each draft.steps as step, i}
            <tr>
              <td class="mono">{i + 1}</td>
              <td><input type="number" min="0" max="1600" step="1" bind:value={step.target_temp_c} aria-label="目标温度" /></td>
              <td><input type="number" min="0" max="100" step="0.1" bind:value={step.ramp_rate_cpm} aria-label="升温速率" /></td>
              <td><input type="number" min="0" step="1" bind:value={step.hold_seconds} aria-label="保温秒" /></td>
              <td><input type="number" min="0" max="50" step="0.01" bind:value={step.n2_lpm} aria-label="N2" /></td>
              <td><input type="number" min="0" max="50" step="0.01" bind:value={step.h2_lpm} aria-label="H2" /></td>
              <td><input type="number" min="0" max="50" step="0.01" bind:value={step.co_lpm} aria-label="CO" /></td>
              <td><input bind:value={step.notes} maxlength="500" aria-label="备注" /></td>
              <td style="white-space:nowrap">
                <button class="btn sm" type="button" title="上移" aria-label="上移" onclick={() => moveStep(i, -1)} disabled={i === 0}>↑</button>
                <button class="btn sm" type="button" title="下移" aria-label="下移" onclick={() => moveStep(i, 1)} disabled={i === draft.steps.length - 1}>↓</button>
                <button class="btn sm" type="button" title="删除步骤" aria-label="删除步骤" onclick={() => removeStep(i)} disabled={draft.steps.length === 1}>×</button>
              </td>
            </tr>
          {/each}
        </tbody>
      </table></div>
      <div class="row"><button class="btn sm" type="button" onclick={addStep}>新增步骤</button>
        <span class="muted small">温度程序模式下，控温仪一次最多接收 4 个步骤（8 段）；更长的配方需在设置中改为逐步设定模式。</span></div>
      {#if localErrors.length}<ul class="small" style="color:var(--danger);margin:0;padding-left:18px">{#each localErrors as item}<li>{item}</li>{/each}</ul>{/if}
    </div>
  </section>
</div>

<ConfirmDialog open={confirmDelete} title="删除配方" message={`删除配方 #${selectedId}「${draft.name}」？历史实验仍保留，但不再关联此配方名称。`} confirmLabel="删除" tone="danger" onconfirm={remove} oncancel={() => (confirmDelete = false)} />
