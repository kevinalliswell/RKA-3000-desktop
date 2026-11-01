<script lang="ts">
  import Badge from '../../components/Badge.svelte';
  import Seg from '../../components/Seg.svelte';
  import ConfirmDialog from '../../components/ConfirmDialog.svelte';
  import * as api from '../../lib/api/endpoints';
  import type { ExperimentType, GasKey, Recipe, RecipeStep, RecipeSummary } from '../../lib/api/types';
  import { notifier } from '../../lib/state/notify.svelte';
  import { prefs } from '../../lib/state/prefs.svelte';
  import { nav } from '../../lib/state/nav.svelte';
  import { errorMessage } from '../../lib/api/client';
  import {
    downloadText, flowsText, fmtFlow, fmtShort, fmtTemp, GAS_COLUMN, GAS_KEYS, GAS_LABEL, PROCESS_GASES, stepFlows, TYPE_LABEL,
    TYPE_SHORT, TYPE_TONE,
  } from '../../lib/format';

  let { online, runActive }: { online: boolean; runActive: boolean } = $props();

  interface Draft {
    id: number | null;
    name: string;
    experiment_type: ExperimentType;
    inert_gas: 'N2' | 'AR';
    purge_lpm: number;
    purge_seconds: number;
    description: string;
    steps: RecipeStep[];
  }

  let recipes = $state<RecipeSummary[]>([]);
  let selectedId = $state<number | null>(null);
  let recipe = $state<Recipe | null>(null);
  let draft = $state<Draft | null>(null);
  let saving = $state(false);
  let error = $state('');
  let confirmSave = $state(false);
  let confirmDelete = $state(false);
  let fileInput: HTMLInputElement | undefined = $state();

  async function load() {
    try {
      recipes = await api.listRecipes();
      if (selectedId === null || !recipes.some((r) => r.id === selectedId)) selectedId = recipes[0]?.id ?? null;
      error = '';
    } catch (e) { error = errorMessage(e); }
  }
  $effect(() => { if (online) void load(); });
  $effect(() => {
    const id = selectedId;
    if (id === null) { recipe = null; return; }
    api.getRecipe(id).then((r) => { if (selectedId === id) recipe = r; }).catch((e) => (error = errorMessage(e)));
  });

  function blankStep(n: number, inert: GasKey, flow = 4): RecipeStep {
    const step = { step_no: n, name: '', target_temp_c: 150, ramp_rate_cpm: 10, hold_seconds: 600, notes: '',
      n2_lpm: 0, ar_lpm: 0, h2_lpm: 0, co_lpm: 0, co2_lpm: 0, ch4_lpm: 0, o2_lpm: 0 } as RecipeStep;
    (step as unknown as Record<string, number>)[GAS_COLUMN[inert]] = flow;
    return step;
  }

  function newDraft() {
    draft = {
      id: null, name: '', experiment_type: 'reduction', inert_gas: 'N2', purge_lpm: 4, purge_seconds: 600, description: '',
      steps: [
        { ...blankStep(1, 'N2'), name: '惰性置换' },
        { ...blankStep(2, 'N2', 3), name: '等温反应', target_temp_c: 900, hold_seconds: 3600 },
        { ...blankStep(3, 'N2'), name: '惰性处置', target_temp_c: 200, ramp_rate_cpm: 0, hold_seconds: 900 },
      ],
    };
  }

  function editDraft(copy = false) {
    if (!recipe) return;
    draft = {
      id: copy ? null : recipe.id, name: copy ? `${recipe.name} 副本` : recipe.name, experiment_type: recipe.experiment_type,
      inert_gas: recipe.inert_gas, purge_lpm: recipe.purge_lpm, purge_seconds: recipe.purge_seconds, description: recipe.description,
      steps: recipe.steps.map((s) => ({ ...s })),
    };
  }

  const draftGases = $derived(draft ? [draft.inert_gas as GasKey, ...PROCESS_GASES[draft.experiment_type]] : []);
  const hiddenNonZero = $derived(draft ? draft.steps.some((s) => GAS_KEYS.some((g) => !draftGases.includes(g) && Number((s as unknown as Record<string, number>)[GAS_COLUMN[g]]) > 0)) : false);

  function setInert(gas: 'N2' | 'AR') {
    if (!draft) return;
    const from = GAS_COLUMN[draft.inert_gas];
    const to = GAS_COLUMN[gas];
    // Move the inert flow to the newly chosen inert gas so the steps stay pure-inert where they were.
    draft.steps = draft.steps.map((s) => {
      const copy = { ...s } as unknown as Record<string, number>;
      copy[to] = copy[from] ?? 0;
      copy[from] = 0;
      return copy as unknown as RecipeStep;
    });
    draft.inert_gas = gas;
  }

  function addStep(index: number) {
    if (!draft) return;
    const steps = [...draft.steps];
    steps.splice(index + 1, 0, blankStep(index + 2, draft.inert_gas));
    draft.steps = steps.map((s, i) => ({ ...s, step_no: i + 1 }));
  }
  function removeStep(index: number) {
    if (!draft || draft.steps.length <= 1) return;
    draft.steps = draft.steps.filter((_, i) => i !== index).map((s, i) => ({ ...s, step_no: i + 1 }));
  }
  function moveStep(index: number, delta: number) {
    if (!draft) return;
    const steps = [...draft.steps];
    const target = index + delta;
    if (target < 0 || target >= steps.length) return;
    [steps[index], steps[target]] = [steps[target]!, steps[index]!];
    draft.steps = steps.map((s, i) => ({ ...s, step_no: i + 1 }));
  }
  function setFlow(index: number, gas: GasKey, value: string) {
    if (!draft) return;
    const steps = [...draft.steps];
    steps[index] = { ...steps[index]!, [GAS_COLUMN[gas]]: Number(value) || 0 } as RecipeStep;
    draft.steps = steps;
  }

  async function save(reason: string) {
    if (!draft) return;
    saving = true;
    try {
      const payload = { name: draft.name, experiment_type: draft.experiment_type, inert_gas: draft.inert_gas, purge_lpm: Number(draft.purge_lpm),
        purge_seconds: Number(draft.purge_seconds), description: draft.description, steps: draft.steps, reason, operator: prefs.operator || undefined };
      const saved = draft.id ? await api.updateRecipe(draft.id, payload) : await api.createRecipe(payload);
      notifier.push(saved.assessment.runnable ? 'ok' : 'warn', `已保存 ${saved.name} v${saved.version}`, saved.assessment.runnable ? '校验全部通过，可用于实验准备' : `暂不可执行：${saved.assessment.summary}`);
      draft = null;
      selectedId = saved.id;
      recipe = saved;
      await load();
    } catch (e) { error = errorMessage(e); } finally { saving = false; confirmSave = false; }
  }

  async function remove() {
    if (!recipe) return;
    try {
      await api.deleteRecipe(recipe.id, prefs.operator || undefined);
      notifier.push('ok', '配方已删除');
      selectedId = null;
      await load();
    } catch (e) { error = errorMessage(e); } finally { confirmDelete = false; }
  }

  async function exportCurrent() {
    if (!recipe) return;
    try { downloadText(`${recipe.name}.rka-recipe.json`, JSON.stringify(await api.exportRecipe(recipe.id), null, 2)); }
    catch (e) { error = errorMessage(e); }
  }
  async function importFile(file: File) {
    try {
      const created = await api.importRecipe(JSON.parse(await file.text()) as unknown, undefined, prefs.operator || undefined);
      notifier.push('ok', '配方已导入', created.assessment.runnable ? created.name : `${created.name}：${created.assessment.summary}`);
      selectedId = created.id;
      await load();
    } catch (e) { error = errorMessage(e); }
  }

  const issues = $derived(recipe?.assessment.step_issues ?? {});
</script>

<div class="page-head">
  <div>
    <h1>实验配方</h1>
    <p>配方是实验的输入模板。保存时校验参数范围并评估能否启动；每次保存生成新版本，实验启动时冻结快照，之后修改不影响已启动或已归档的实验。</p>
  </div>
  <div class="actions">
    <button class="btn" type="button" onclick={() => fileInput?.click()} disabled={!online}>导入</button>
    <input class="sr-only" type="file" accept=".json,application/json" bind:this={fileInput} onchange={(e) => { const f = e.currentTarget.files?.[0]; if (f) void importFile(f); e.currentTarget.value = ''; }} />
    <button class="btn" type="button" disabled={!recipe || draft !== null} onclick={() => editDraft(true)}>复制所选为新配方</button>
    <button class="btn primary" type="button" disabled={!online || draft !== null} onclick={newDraft}>新建配方</button>
  </div>
</div>
{#if error}<div class="callout danger" role="alert">{error} <button class="linkish" type="button" onclick={() => (error = '')}>关闭</button></div>{/if}

<div class="grid list-detail">
  <section class="card flush">
    <div class="card-head"><h2>配方列表 · {recipes.length}</h2></div>
    <div class="stack tight" style="padding:0 12px 12px">
      {#each recipes as item (item.id)}
        <button type="button" class="check" class:on={item.id === selectedId} style="width:100%;text-align:left;grid-template-columns:minmax(0,1fr)"
          onclick={() => { if (!draft) selectedId = item.id; }} disabled={draft !== null && item.id !== selectedId}>
          <div>
            <div class="row between"><strong>{item.name}</strong><Badge tone={item.runnable ? 'good' : 'danger'}>{item.runnable ? '可执行' : '不可执行'}</Badge></div>
            <span><Badge tone={TYPE_TONE[item.experiment_type]}>{TYPE_SHORT[item.experiment_type]}</Badge> {GAS_LABEL[item.inert_gas]} · v{item.version} · {fmtShort(item.updated_at)}</span>
          </div>
        </button>
      {:else}<div class="empty"><strong>还没有配方</strong>点击“新建配方”开始。</div>{/each}
    </div>
  </section>

  {#if draft}
    <section class="card">
      <div class="card-head"><h2>{draft.id ? `编辑 ${draft.name}（保存为 v${(recipe?.version ?? 0) + 1}）` : '新建配方'}</h2>
        <div class="row"><button class="btn" type="button" onclick={() => (draft = null)}>取消</button>
          <button class="btn primary" type="button" disabled={!online || saving || !draft.name.trim()} onclick={() => (confirmSave = true)}>保存</button></div></div>
      <div class="stack">
        <div class="form-grid three">
          <label class="field"><span>配方名称</span><input bind:value={draft.name} maxlength="100" placeholder="例如 900℃ 等温还原 · CO/H₂" /></label>
          <div class="field"><span>实验类型</span><Seg label="实验类型" value={draft.experiment_type} onselect={(id) => (draft!.experiment_type = id as ExperimentType)} options={[{ id: 'reduction', label: '还原' }, { id: 'oxidation', label: '氧化' }]} /></div>
          <div class="field"><span>惰性气（置换、吹扫、处置共用）</span><Seg label="惰性气" value={draft.inert_gas} onselect={(id) => setInert(id as 'N2' | 'AR')} options={[{ id: 'N2', label: 'N₂' }, { id: 'AR', label: 'Ar' }]} /></div>
          <label class="field"><span>吹扫流量 · L/min</span><input class="mono" type="number" min="0" step="0.01" bind:value={draft.purge_lpm} /></label>
          <label class="field"><span>置换时长 · s</span><input class="mono" type="number" min="0" step="1" bind:value={draft.purge_seconds} /><span class="hint">首尾纯惰性段须不短于此值</span></label>
          <label class="field"><span>说明（可选）</span><input bind:value={draft.description} maxlength="500" /></label>
        </div>
        {#if hiddenNonZero}<div class="callout warn">部分阶段含有本类型不允许的气体流量，保存后将判为不可执行。切回对应实验类型可查看与修改。</div>{/if}
        <div class="table-wrap">
          <table class="data" style="min-width:1040px">
            <thead><tr><th>#</th><th>阶段名称</th><th>目标 ℃</th><th>℃/min</th><th>保持 s</th>
              {#each draftGases as gas}<th>{GAS_LABEL[gas]}{gas === draft.inert_gas ? '（惰性）' : ''}</th>{/each}<th></th></tr></thead>
            <tbody>
              {#each draft.steps as step, i}
                <tr>
                  <td class="mono">{step.step_no}</td>
                  <td><input bind:value={step.name} maxlength="40" placeholder={i === 0 ? '惰性置换' : i === draft.steps.length - 1 ? '惰性处置' : '反应段'} style="font-family:var(--font-ui)" aria-label="阶段名称" /></td>
                  <td><input type="number" min="0" max="1600" bind:value={step.target_temp_c} aria-label="目标温度" /></td>
                  <td><input type="number" min="0" max="100" step="0.1" bind:value={step.ramp_rate_cpm} aria-label="升温速率" /></td>
                  <td><input type="number" min="0" step="1" bind:value={step.hold_seconds} aria-label="保持时间" /></td>
                  {#each draftGases as gas}
                    <td><input type="number" min="0" step="0.01" value={(step as unknown as Record<string, number>)[GAS_COLUMN[gas]] ?? 0}
                      oninput={(e) => setFlow(i, gas, e.currentTarget.value)} aria-label={`${GAS_LABEL[gas]} 流量`} /></td>
                  {/each}
                  <td class="nowrap" style="width:1%">
                    <button class="btn sm" type="button" aria-label="上移" disabled={i === 0} onclick={() => moveStep(i, -1)}>↑</button>
                    <button class="btn sm" type="button" aria-label="下移" disabled={i === draft.steps.length - 1} onclick={() => moveStep(i, 1)}>↓</button>
                    <button class="btn sm" type="button" aria-label="在下方插入阶段" onclick={() => addStep(i)}>＋</button>
                    <button class="btn sm" type="button" aria-label="删除阶段" disabled={draft.steps.length <= 1} onclick={() => removeStep(i)}>×</button>
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
        <p class="tiny soft">可执行规则：至少 3 段（惰性置换 · 反应 · 惰性收尾）；首尾段只开惰性气且不短于置换时长；每段 ≤ 使用上限；气体符合实验类型；温度程序模式下最多 4 段。不满足也可保存，但在实验准备中不可选。</p>
      </div>
    </section>
  {:else if recipe}
    <div class="stack">
      <section class="card flush">
        <div class="card-head">
          <div><h2>{recipe.name}</h2>
            <p>{TYPE_LABEL[recipe.experiment_type]} · 惰性气 {GAS_LABEL[recipe.inert_gas]} · 吹扫 {fmtFlow(recipe.purge_lpm)} L/min × {recipe.purge_seconds} s · v{recipe.version} · 更新 {fmtShort(recipe.updated_at)}</p></div>
          <Badge tone={recipe.assessment.runnable ? 'good' : 'danger'}>{recipe.assessment.runnable ? '可执行' : '不可执行'}</Badge>
        </div>
        <div class="table-wrap">
          <table class="data">
            <thead><tr><th>#</th><th>阶段</th><th class="num">目标 ℃</th><th class="num">℃/min</th><th class="num">保持 s</th><th>气体 L/min</th><th>校验</th></tr></thead>
            <tbody>
              {#each recipe.steps as step}
                <tr><td class="mono">{step.step_no}</td><td>{step.name || `第 ${step.step_no} 段`}</td><td class="num mono">{fmtTemp(step.target_temp_c)}</td>
                  <td class="num mono">{step.ramp_rate_cpm}</td><td class="num mono">{step.hold_seconds}</td><td>{flowsText(stepFlows(step))}</td>
                  <td>{#if issues[String(step.step_no)]}<Badge tone="danger">{issues[String(step.step_no)]!.join('；')}</Badge>{:else}<Badge tone="good">通过</Badge>{/if}</td></tr>
              {/each}
            </tbody>
          </table>
        </div>
        <div style="padding:12px 16px 16px" class="stack tight">
          <div class={`callout ${recipe.assessment.runnable ? 'good' : 'danger'}`}>
            {recipe.assessment.runnable ? '校验全部通过。' : recipe.assessment.summary}
            {#if recipe.experiment_count}该配方已被 {recipe.experiment_count} 次实验引用；再次保存会生成 v{recipe.version + 1}，不影响这些实验的快照。{/if}
          </div>
          <div class="row">
            <button class="btn" type="button" disabled={!online || runActive && recipe.running} onclick={() => editDraft(false)}>编辑阶段</button>
            <button class="btn" type="button" onclick={exportCurrent}>导出</button>
            <button class="btn primary" type="button" disabled={!recipe.assessment.runnable} onclick={() => nav.go('preflight')}>用于实验准备</button>
            <span class="fill"></span>
            <button class="btn sm danger-ghost" type="button" disabled={!online || recipe.running} onclick={() => (confirmDelete = true)}>删除</button>
          </div>
          {#if recipe.running}<p class="tiny soft">该配方正在被运行中的实验使用，不能修改或删除。</p>{/if}
        </div>
      </section>
      <div class="grid halves">
        <section class="card">
          <h2 style="margin-bottom:6px">保存时的校验规则</h2>
          <div class="checks">
            {#each recipe.assessment.checks as check}
              <div class="item"><div><strong>{check.label}</strong><span>{check.detail}</span></div><Badge tone={check.ok ? 'good' : 'danger'}>{check.ok ? '通过' : '未通过'}</Badge></div>
            {/each}
          </div>
          <p class="tiny soft" style="margin-top:8px">按使用上限策略 v{recipe.limits_version} 评估。</p>
        </section>
        <section class="card">
          <h2 style="margin-bottom:6px">版本历史</h2>
          {#each recipe.versions as version}
            <div class="ev"><time>v{version.version}</time><strong>{version.reason || '—'}</strong><span>{version.actor || '—'} · {fmtShort(version.created_at)}</span></div>
          {/each}
          <p class="tiny soft" style="margin-top:8px">历史实验引用的是版本快照，可在历史实验中查看该次实验使用的具体版本。</p>
        </section>
      </div>
    </div>
  {:else}
    <section class="card"><div class="empty"><strong>选择或新建一个配方</strong></div></section>
  {/if}
</div>

<ConfirmDialog open={confirmSave} busy={saving} title={draft?.id ? `保存为 v${(recipe?.version ?? 0) + 1}？` : '新建配方？'} confirmLabel="保存"
  message="保存后立即重新评估可执行性。运行中实验的配方快照不受影响。"
  input={draft?.id ? { label: '修改原因（必填，记入版本历史）', minLength: 2, placeholder: '例如 等温段 H₂ 0.80 → 1.00' } : { label: '说明（可选）' }}
  onconfirm={save} oncancel={() => (confirmSave = false)} />
<ConfirmDialog open={confirmDelete} tone="danger" title="删除配方？" confirmLabel="删除"
  message={`将删除 ${recipe?.name ?? ''} 及其版本历史。已运行实验保存了自己的配方快照，不受影响。`}
  onconfirm={remove} oncancel={() => (confirmDelete = false)} />
