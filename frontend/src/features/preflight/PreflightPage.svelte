<script lang="ts">
  import { onMount } from 'svelte';
  import Badge from '../../components/Badge.svelte';
  import Seg from '../../components/Seg.svelte';
  import * as api from '../../lib/api/endpoints';
  import { errorMessage } from '../../lib/api/client';
  import type { ExperimentType, PreflightResult, Recipe, RecipeSummary, SampleInput } from '../../lib/api/types';
  import type { RunSession } from '../../lib/state/run.svelte';
  import { nav } from '../../lib/state/nav.svelte';
  import { prefs } from '../../lib/state/prefs.svelte';
  import { rules } from '../../lib/state/rules.svelte';
  import { notifier } from '../../lib/state/notify.svelte';
  import {
    DASH, DEVICE_LABEL, flowsText, fmtDuration, fmtFlow, fmtMass, fmtTemp, GAS_LABEL, stepFlows, TYPE_LABEL,
  } from '../../lib/format';

  let { run, online }: { run: RunSession; online: boolean } = $props();

  let step = $state(0);
  let type = $state<ExperimentType>('reduction');
  let recipes = $state<RecipeSummary[]>([]);
  let recipeId = $state<number | null>(null);
  let recipe = $state<Recipe | null>(null);
  let sample = $state<SampleInput>({ name: '', initial_mass_g: null, tfe_pct: null, feo_pct: null, operator: '', particle_size: '' });
  let checklist = $state<Record<string, boolean>>({});
  let result = $state<PreflightResult | null>(null);
  let checking = $state(false);
  let loadError = $state('');
  let deviceTimer: ReturnType<typeof setInterval> | undefined;

  const visible = $derived(recipes.filter((r) => r.experiment_type === type));
  const allowedGases = $derived<string[]>(recipe ? [recipe.inert_gas, ...rules.processGases(recipe.experiment_type)] : rules.processGases(type));
  const items = $derived(result?.checklist_items ?? []);
  const checkedCount = $derived(items.filter((item) => checklist[item.key]).length);
  // Sample validity is decided by Python (preflight "sample" check), never re-implemented here.
  const sampleCheck = $derived(result?.checks.find((c) => c.key === 'sample') ?? null);
  const sampleTouched = $derived(Boolean(sample.name || sample.initial_mass_g !== null || sample.tfe_pct !== null || sample.feo_pct !== null));
  const step1Ok = $derived(recipe !== null && recipe.assessment.runnable && sampleCheck?.ok === true);
  let sampleTimer: ReturnType<typeof setTimeout> | undefined;
  $effect(() => {
    void JSON.stringify(sample);
    void recipeId;
    if (step !== 0) return;
    clearTimeout(sampleTimer);
    sampleTimer = setTimeout(() => void check(), 400);
  });
  const blockedByRun = $derived(run.active);
  const estimated = $derived.by(() => {
    if (!recipe) return null;
    let previous = 25;
    let seconds = 0;
    for (const s of recipe.steps) {
      if (s.ramp_rate_cpm > 0) seconds += (Math.abs(s.target_temp_c - previous) / s.ramp_rate_cpm) * 60;
      seconds += s.hold_seconds;
      previous = s.target_temp_c;
    }
    return seconds;
  });

  onMount(() => {
    sample.operator = prefs.operator;
    void rules.load();
    void load();
    return () => { clearInterval(deviceTimer); clearTimeout(sampleTimer); };
  });

  async function load() {
    loadError = '';
    try {
      recipes = await api.listRecipes();
      result = await api.preflight({});
      const first = recipes.find((r) => r.experiment_type === type && r.runnable);
      if (first && recipeId === null) await pick(first.id);
    } catch (error) {
      loadError = errorMessage(error);
    }
  }

  async function pick(id: number) {
    recipeId = id;
    try {
      recipe = await api.getRecipe(id);
    } catch (error) {
      notifier.push('danger', '读取配方失败', errorMessage(error));
    }
  }

  function setType(next: string) {
    type = next as ExperimentType;
    recipe = null;
    recipeId = null;
    const first = recipes.find((r) => r.experiment_type === type && r.runnable);
    if (first) void pick(first.id);
  }

  function payload() {
    return { recipe_id: recipeId ?? undefined, sample: { ...sample }, checklist: { ...checklist } };
  }

  let checkSeq = 0;
  /** Every call is sent; only the newest response is shown (a slower periodic refresh must not overwrite it). */
  async function check() {
    const mine = ++checkSeq;
    checking = true;
    try {
      const next = await api.preflight(payload() as never);
      if (mine === checkSeq) result = next;
    } catch (error) {
      if (mine === checkSeq) notifier.push('danger', '预检失败', errorMessage(error));
    } finally {
      if (mine === checkSeq) checking = false;
    }
  }

  function goto(next: number) {
    step = next;
    clearInterval(deviceTimer);
    if (next >= 1) void check();
    if (next === 1) deviceTimer = setInterval(() => void check(), 3000);
  }

  async function start() {
    if (!recipeId || !result?.ready) return;
    prefs.setOperator(sample.operator);
    const ok = await run.startRun({ recipe_id: recipeId, sample: { ...sample }, checklist: { ...checklist } });
    if (ok) {
      notifier.push('ok', '实验已启动', '配方快照与使用上限已锁定');
      nav.go('current');
    } else {
      notifier.push('danger', '启动未执行', run.error);
      await check();
    }
  }

  function num(value: string): number | null {
    if (value.trim() === '') return null;
    const n = Number(value);
    return Number.isFinite(n) ? n : null;
  }

  const balanceDeviation = $derived(result?.mass_deviation_pct ?? null);
</script>

<div class="page-head">
  <div>
    <h1>实验准备</h1>
    <p>三步预检：样品与配方 → 设备与现场 → 复核与启动。任一启动条件不满足，“确认启动实验”不可用。</p>
  </div>
  <div class="actions">
    {#if result}<Badge tone={result.ready ? 'good' : 'warn'} dot>{result.ready ? '启动条件已满足' : '启动条件未满足'}</Badge>{/if}
  </div>
</div>

{#if blockedByRun}
  <div class="callout warn"><strong>当前有实验在运行或处置中。</strong> 结束并归档后才能开始新的实验准备。
    <div class="actions"><button class="btn sm" type="button" onclick={() => nav.go('current')}>查看当前实验</button></div></div>
{/if}
{#if loadError}<div class="callout danger">{loadError}</div>{/if}

<nav class="steps" aria-label="预检步骤">
  {#each ['样品与配方', '设备与现场', '复核与启动'] as label, index}
    <button type="button" class={step > index ? 'done' : ''} aria-current={step === index ? 'step' : undefined}
      disabled={index > 0 && !step1Ok} onclick={() => goto(index)}><span class="n">{step > index ? '✓' : index + 1}</span>{label}</button>
  {/each}
</nav>

{#if step === 0}
  <div class="grid main-side">
    <div class="stack">
      <section class="card">
        <div class="card-head"><h2>样品信息</h2></div>
        <div class="form-grid three">
          <label class="field"><span>样品名称</span><input bind:value={sample.name} placeholder="例如 球团矿 A-19" /></label>
          <label class="field"><span>初始质量 · g</span><input class="mono" inputmode="decimal" value={sample.initial_mass_g ?? ''} oninput={(e) => (sample.initial_mass_g = num(e.currentTarget.value))} /></label>
          <label class="field"><span>操作者</span><input bind:value={sample.operator} placeholder="姓名" /></label>
          <label class="field"><span>TFe · %</span><input class="mono" inputmode="decimal" value={sample.tfe_pct ?? ''} oninput={(e) => (sample.tfe_pct = num(e.currentTarget.value))} /></label>
          <label class="field"><span>FeO · %</span><input class="mono" inputmode="decimal" value={sample.feo_pct ?? ''} oninput={(e) => (sample.feo_pct = num(e.currentTarget.value))} /></label>
          <label class="field"><span>粒径范围 · mm（可选）</span><input bind:value={sample.particle_size} placeholder="例如 10–12.5" /></label>
        </div>
        {#if sampleTouched && sampleCheck && !sampleCheck.ok}<p class="error tiny" style="margin-top:10px;color:var(--danger)" role="status">{sampleCheck.detail}</p>{/if}
        <p class="tiny soft" style="margin-top:10px">初始质量以启动前天平稳定读数为准；与天平读数偏差 &gt; 0.5% 时，第 3 步会提示复核。</p>
      </section>

      <section class="card">
        <div class="card-head"><h2>实验类型与气源</h2></div>
        <div class="stack">
          <div class="row"><span class="label" style="min-width:64px">实验类型</span>
            <Seg label="实验类型" value={type} onselect={setType} options={[{ id: 'reduction', label: '还原实验' }, { id: 'oxidation', label: '氧化实验' }]} />
          </div>
          <div class="row"><span class="label" style="min-width:64px">本次气体</span>
            {#each allowedGases.filter(Boolean) as gas}
              <Badge tone={gas === recipe?.inert_gas ? 'dark' : ''}>{GAS_LABEL[gas as keyof typeof GAS_LABEL]}{gas === recipe?.inert_gas ? ' · 惰性 / 吹扫' : ''}</Badge>
            {/each}
          </div>
          <p class="tiny soft">实验类型决定允许的工艺气体：还原实验 CO / CO₂ / H₂ / CH₄，氧化实验 CO₂ / O₂。惰性气（N₂ 或 Ar）由配方决定，一次实验只用一种，吹扫与安全处置也用它。</p>
        </div>
      </section>

      <section class="card">
        <div class="card-head"><h2>可执行配方</h2><span class="tiny soft">不可执行的配方不能选择，原因见右侧</span></div>
        <div class="stack tight" role="radiogroup" aria-label="配方">
          {#each visible as item (item.id)}
            <label class="check" class:on={recipeId === item.id} style={item.runnable ? '' : 'opacity:.6'}>
              <input type="radio" name="recipe" checked={recipeId === item.id} disabled={!item.runnable} onchange={() => pick(item.id)} />
              <div><strong>{item.name} <span class="soft mono">v{item.version}</span></strong>
                <span>{item.runnable ? `${item.step_count} 段 · 惰性气 ${GAS_LABEL[item.inert_gas]} · 吹扫 ${fmtFlow(item.purge_lpm)} L/min × ${item.purge_seconds} s` : item.summary}</span></div>
            </label>
          {:else}
            <p class="soft small">没有{TYPE_LABEL[type]}配方。<button class="linkish" type="button" onclick={() => nav.go('recipes')}>去新建</button></p>
          {/each}
        </div>
      </section>
    </div>

    <section class="card flush">
      <div class="card-head">
        <h2>{recipe ? `配方阶段 · ${recipe.name} v${recipe.version}` : '配方阶段'}</h2>
        {#if recipe}<Badge tone={recipe.assessment.runnable ? 'good' : 'danger'}>{recipe.assessment.runnable ? `符合使用上限 v${recipe.limits_version}` : '不可执行'}</Badge>{/if}
      </div>
      {#if recipe}
        <div class="table-wrap">
          <table class="data">
            <thead><tr><th>#</th><th>阶段</th><th class="num">目标 ℃</th><th class="num">℃/min</th><th class="num">保持 s</th><th>气体 L/min</th></tr></thead>
            <tbody>
              {#each recipe.steps as s}
                <tr><td class="mono">{s.step_no}</td><td>{s.name || `第 ${s.step_no} 段`}</td><td class="num mono">{fmtTemp(s.target_temp_c)}</td>
                  <td class="num mono">{s.ramp_rate_cpm}</td><td class="num mono">{s.hold_seconds}</td><td>{flowsText(stepFlows(s))}</td></tr>
              {/each}
            </tbody>
          </table>
        </div>
        <div style="padding:12px 16px 16px" class="stack tight">
          {#if !recipe.assessment.runnable}<div class="callout danger">{recipe.assessment.summary}</div>{/if}
          <p class="tiny soft">预计总时长约 {fmtDuration(estimated)}（不含冷却至安全温度的时间）。启动后配方快照冻结，修改配方不影响本次。</p>
          <button class="btn primary" type="button" disabled={!step1Ok} onclick={() => goto(1)}>下一步：设备与现场</button>
        </div>
      {:else}
        <div class="empty"><strong>请选择配方</strong>选择后在此显示阶段与校验结果。</div>
      {/if}
    </section>
  </div>
{:else if step === 1}
  <div class="grid main-side">
    <section class="card flush">
      <div class="card-head"><h2>设备回读（启动前必须全部新鲜）</h2>
        <button class="btn sm" type="button" disabled={checking} onclick={check}>{checking ? '读取中…' : '重新读取'}</button></div>
      <div class="table-wrap">
        <table class="data">
          <thead><tr><th>设备</th><th>当前读数</th><th>回读</th></tr></thead>
          <tbody>
            <tr><td>温控器</td><td class="mono">{fmtTemp(result?.readings.temperature_c)} ℃</td>
              <td><Badge tone={result?.readings.degraded?.includes('temp') || !result?.readings.connected ? 'danger' : 'good'} dot>{result?.readings.degraded?.includes('temp') ? '无回读' : result?.readings.connected ? '新鲜' : '未连接'}</Badge></td></tr>
            <tr><td>MFC 总线</td><td class="mono">{flowsText(result?.readings.flows)}</td>
              <td><Badge tone={result?.readings.degraded?.includes('mfc') || !result?.readings.connected ? 'danger' : 'good'} dot>{result?.readings.degraded?.includes('mfc') ? '无回读' : result?.readings.connected ? '新鲜' : '未连接'}</Badge></td></tr>
            <tr><td>电子天平</td><td class="mono">{fmtMass(result?.readings.weight_g)} g</td>
              <td><Badge tone={result?.readings.degraded?.includes('balance') || !result?.readings.connected ? 'danger' : 'good'} dot>{result?.readings.degraded?.includes('balance') ? '无回读' : result?.readings.connected ? '新鲜' : '未连接'}</Badge></td></tr>
          </tbody>
        </table>
      </div>
      <div style="padding:12px 16px 16px">
        {#if balanceDeviation !== null}
          <div class={`callout ${balanceDeviation <= 0.5 ? 'good' : 'warn'}`}>
            天平当前读数 {fmtMass(result?.balance_g)} g，与输入的初始质量 {fmtMass(sample.initial_mass_g)} g 偏差 {balanceDeviation.toFixed(3)}%{balanceDeviation <= 0.5 ? '，在允许范围内。' : '，超过 0.5%，请复核样品或重新去皮。'}
          </div>
        {:else}
          <div class="callout warn">没有有效的天平读数，无法核对初始质量。</div>
        {/if}
        <p class="tiny soft" style="margin-top:8px">每 3 秒自动刷新。{result?.readings.degraded?.length ? `无回读：${result.readings.degraded.map((d) => DEVICE_LABEL[d] ?? d).join('、')}` : ''}</p>
      </div>
    </section>

    <section class="card">
      <div class="card-head"><h2>现场检查 · 已勾选 {checkedCount} / {items.length}</h2></div>
      <div class="stack tight">
        {#each items as item}
          <label class="check" class:on={checklist[item.key]}>
            <input type="checkbox" checked={Boolean(checklist[item.key])} onchange={(e) => (checklist = { ...checklist, [item.key]: e.currentTarget.checked })} />
            <div><strong>{item.label}</strong><span>{item.detail}</span></div>
          </label>
        {/each}
      </div>
      <div class="row" style="margin-top:12px">
        <button class="btn" type="button" onclick={() => goto(0)}>上一步</button>
        <button class="btn primary" type="button" onclick={() => goto(2)}>下一步：复核与启动</button>
      </div>
    </section>
  </div>
{:else}
  <div class="grid main-side">
    <section class="card">
      <div class="card-head"><h2>启动前复核</h2></div>
      <dl class="kv">
        <dt>样品</dt><dd>{sample.name} · {fmtMass(sample.initial_mass_g)} g · TFe {sample.tfe_pct ?? DASH}% · FeO {sample.feo_pct ?? DASH}%{sample.particle_size ? ` · ${sample.particle_size} mm` : ''}</dd>
        <dt>操作者</dt><dd>{sample.operator}</dd>
        <dt>实验类型</dt><dd>{recipe ? TYPE_LABEL[recipe.experiment_type] : DASH} · 惰性气 {recipe ? GAS_LABEL[recipe.inert_gas] : DASH}</dd>
        <dt>配方快照</dt><dd>{recipe?.name} v{recipe?.version} · {recipe?.steps.length} 个阶段 · 启动后冻结，修改配方不影响本次</dd>
        <dt>吹扫参数</dt><dd>{recipe ? `${GAS_LABEL[recipe.inert_gas]} ${fmtFlow(recipe.purge_lpm)} L/min · 置换 ${recipe.purge_seconds} s（首尾阶段与安全处置共用）` : DASH}</dd>
        <dt>安全完成</dt><dd>吹扫满时长且炉温 &lt; {result?.safe_temperature_c ?? DASH} ℃</dd>
        <dt>温度控制</dt><dd>{result?.temperature_mode === 'program' ? '温度程序启动时一次性下发到温控器，由仪表执行，过程中不调节' : '按配方逐段下发温度设定'}</dd>
        <dt>使用上限</dt><dd>策略 v{result?.limits_version ?? DASH} · 启动后锁定，直到本次归档</dd>
        <dt>预计总时长</dt><dd class="mono">{fmtDuration(estimated)}</dd>
      </dl>
      {#if result}
        <div class={`callout ${result.ready ? 'good' : 'warn'}`} style="margin-top:14px">
          {#if result.ready}所有启动条件已满足。启动后配方快照与使用上限锁定，首段以纯 {recipe ? GAS_LABEL[recipe.inert_gas] : '惰性气'} 置换。
          {:else}尚有启动条件未满足，“确认启动实验”保持不可用。请按右侧提示处理。{/if}
        </div>
      {/if}
    </section>

    <section class="card">
      <div class="card-head"><h2>启动条件</h2><button class="btn sm" type="button" disabled={checking} onclick={check}>{checking ? '检查中…' : '重新检查'}</button></div>
      <div class="checks">
        {#each result?.checks ?? [] as item}
          <div class="item"><div><strong>{item.label}</strong><span>{item.detail}</span></div>
            <Badge tone={item.ok ? 'good' : item.blocking ? 'danger' : 'warn'}>{item.ok ? '通过' : item.blocking ? '未通过' : '请复核'}</Badge></div>
        {/each}
      </div>
      <p class="tiny soft" style="margin:10px 0">点击后：命令已受理 → 回读验证 → 实验运行。任一环节失败，实验进入惰性处置并记录事件。</p>
      <div class="stack tight">
        <button class="btn primary block" type="button" disabled={!online || !result?.ready || run.busy !== null || blockedByRun} onclick={start}>
          {#if run.busy === 'start'}<span class="spinner" aria-hidden="true"></span>{/if}确认启动实验
        </button>
        <button class="btn block" type="button" onclick={() => goto(1)}>返回修改检查项</button>
      </div>
      {#if run.error && run.busy === null}<p class="error tiny" style="margin-top:8px;color:var(--danger)">{run.error}</p>{/if}
    </section>
  </div>
{/if}
