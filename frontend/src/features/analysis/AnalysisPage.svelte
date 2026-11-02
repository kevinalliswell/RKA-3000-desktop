<script lang="ts">
  import Badge from '../../components/Badge.svelte';
  import Metric from '../../components/Metric.svelte';
  import LineChart from '../../components/LineChart.svelte';
  import ConfirmDialog from '../../components/ConfirmDialog.svelte';
  import * as api from '../../lib/api/endpoints';
  import { errorMessage } from '../../lib/api/client';
  import type { CompareRow, ExperimentSummary, KineticsResult, ReviewResult, SampleParams } from '../../lib/api/types';
  import { nav } from '../../lib/state/nav.svelte';
  import { prefs } from '../../lib/state/prefs.svelte';
  import { notifier } from '../../lib/state/notify.svelte';
  import { awaitTask } from '../../lib/state/tasks';
  import { categoryLabel, categoryTone, END_REASON, fmt, fmtClock, fmtShort, TYPE_LABEL } from '../../lib/format';

  let { online, onarchived }: { online: boolean; onarchived: () => void } = $props();

  let experiments = $state<ExperimentSummary[]>([]);
  let selectedId = $state<number | null>(nav.experimentId);
  let review = $state<ReviewResult | null>(null);
  let kinetics = $state<KineticsResult | null>(null);
  let kineticsError = $state('');
  let compare = $state<CompareRow[]>([]);
  let params = $state<SampleParams>({ initial_mass_g: null, tfe_pct: null, feo_pct: null });
  let model = $state<string | null>(null);
  let note = $state('');
  let confirmArchive = $state(false);
  let busy = $state(false);
  let error = $state('');

  async function loadList() {
    try {
      const [pending, recent] = await Promise.all([api.listExperiments({ category: 'pending', limit: 50 }), api.listExperiments({ limit: 100 })]);
      const seen = new Set<number>();
      experiments = [...pending.experiments, ...recent.experiments].filter((e) => e.category !== 'running' && !seen.has(e.id) && seen.add(e.id));
      if (selectedId === null) selectedId = experiments[0]?.id ?? null;
    } catch (e) { error = errorMessage(e); }
  }

  async function loadExperiment(id: number) {
    error = '';
    kinetics = null;
    kineticsError = '';
    try {
      review = await api.reviewExperiment(id);
      const exp = review.experiment;
      params = { initial_mass_g: exp.initial_mass_g, tfe_pct: exp.tfe_pct, feo_pct: exp.feo_pct };
      note = exp.archive_note ?? '';
      compare = await api.compareExperiment(id);
      await compute();
    } catch (e) { error = errorMessage(e); }
  }

  async function compute(save = false) {
    if (!selectedId) return;
    try {
      if (save) {
        await api.putSampleParams(selectedId, params);
        notifier.push('ok', '试样参数已保存');
      }
      kinetics = await api.computeKinetics(selectedId);
      model = kinetics.best_fit;
      kineticsError = '';
      if (save) review = await api.reviewExperiment(selectedId);
    } catch (e) { kinetics = null; kineticsError = errorMessage(e); }
  }

  $effect(() => { if (online) void loadList(); });
  $effect(() => { if (selectedId !== null && online) void loadExperiment(selectedId); });

  const exp = $derived(review?.experiment ?? null);
  const archived = $derived(exp?.review_state === 'archived');
  const word = $derived(kinetics?.degree_kind === 'oxidation' ? '氧化' : '还原');
  const fit = $derived(kinetics?.fits.find((f) => f.id === model) ?? null);
  const blocking = $derived(review?.checks.filter((c) => c.severity === 'block') ?? []);
  const noteMissing = $derived(Boolean(review?.note_required) && note.trim().length < 2);

  async function archive() {
    if (!selectedId) return;
    busy = true;
    try {
      review = await api.archiveExperiment(selectedId, note.trim(), prefs.operator || undefined);
      notifier.push('ok', '已归档', '数据与快照只读；使用上限解锁，系统回到待机');
      onarchived();
      await loadList();
    } catch (e) { notifier.push('danger', '归档失败', errorMessage(e)); } finally { busy = false; confirmArchive = false; }
  }

  async function exportCsv() {
    if (!selectedId) return;
    try {
      const task = await awaitTask(await api.startExport(selectedId, 'measurements_csv'));
      notifier.push(task.status === 'completed' ? 'ok' : 'danger', task.status === 'completed' ? '已导出 CSV' : '导出失败', String(task.result?.filename ?? task.error ?? ''));
    } catch (e) { notifier.push('danger', '导出失败', errorMessage(e)); }
  }

  function num(value: string): number | null {
    const n = Number(value);
    return value.trim() === '' || !Number.isFinite(n) ? null : n;
  }
</script>

<div class="page-head">
  <div>
    <h1>分析与归档</h1>
    <p>先看四项指标，再选模型拟合；归档前复核采样完整性、报警与配方快照。归档后数据只读，使用上限解锁，系统回到待机。</p>
  </div>
  <div class="actions">
    <label class="field" style="min-width:300px"><span>实验</span>
      <select value={selectedId ?? ''} onchange={(e) => (selectedId = Number(e.currentTarget.value) || null)}>
        {#each experiments as item}<option value={item.id}>{item.code} · {item.sample_name ?? item.name} · {categoryLabel[item.category]}</option>{/each}
      </select></label>
  </div>
</div>

{#if error}<div class="callout danger">{error}</div>{/if}

{#if !exp}
  <section class="card"><div class="empty"><strong>没有可分析的实验</strong>实验结束后会出现在这里等待复核归档。</div></section>
{:else}
  <section class="card">
    <div class="row between">
      <div>
        <h2>{exp.code} · {exp.sample_name ?? exp.name} · 结果</h2>
        <p class="small soft" style="margin-top:4px">{exp.experiment_type ? TYPE_LABEL[exp.experiment_type] : '—'} · {exp.recipe_name ?? '—'}{exp.recipe_version ? ` v${exp.recipe_version}` : ''} · {END_REASON[exp.end_reason ?? ''] ?? exp.status}{exp.final_temperature_c != null ? ` · 处置后炉温 ${fmt(exp.final_temperature_c, 0)} ℃` : ''}</p>
      </div>
      <div class="row">
        <Badge tone={categoryTone[exp.category]}>{exp.category === 'pending' ? '已结束 · 待核查' : `${categoryLabel[exp.category]} · 只读`}</Badge>
        <Badge tone={review?.stats.complete ? 'good' : 'warn'}>采样 {review?.stats.count ?? 0} 点 · {review?.stats.gaps ?? 0} 缺口</Badge>
        <button class="btn sm" type="button" onclick={exportCsv} disabled={!online || !review?.stats.count}>导出 CSV（原始采样）</button>
        {#if archived}<button class="btn sm" type="button" onclick={() => nav.go('reports')}>生成报告</button>{/if}
      </div>
    </div>
    {#if archived}
      <div class="callout good" style="margin-top:12px"><strong>已归档。</strong> 原始采样、配方快照、操作记录与报警已冻结为只读（{exp.archived_by} · {fmtShort(exp.archived_at)}）。{exp.archive_note ? `备注：${exp.archive_note}` : ''}</div>
    {/if}
  </section>

  <section class="card">
    <div class="card-head"><h2>试样参数</h2><span class="tiny soft">{archived ? '已归档，只读' : '启动时录入；归档前可修正'}</span></div>
    <div class="row" style="align-items:flex-end">
      <label class="field"><span>初始质量 m0 · g</span><input class="mono" value={params.initial_mass_g ?? ''} disabled={archived} oninput={(e) => (params.initial_mass_g = num(e.currentTarget.value))} /></label>
      <label class="field"><span>TFe · %</span><input class="mono" value={params.tfe_pct ?? ''} disabled={archived} oninput={(e) => (params.tfe_pct = num(e.currentTarget.value))} /></label>
      <label class="field"><span>FeO · %</span><input class="mono" value={params.feo_pct ?? ''} disabled={archived} oninput={(e) => (params.feo_pct = num(e.currentTarget.value))} /></label>
      {#if !archived}<button class="btn" type="button" disabled={!online} onclick={() => compute(true)}>保存并重新计算</button>{/if}
    </div>
    {#if kineticsError}<div class="callout warn" style="margin-top:10px">{kineticsError}</div>{/if}
  </section>

  {#if kinetics}
    <section class="grid metrics">
      <Metric label={`40% ${word}速率`} value={fmt(kinetics.rate_at_40_pct, 2)} unit="% / min" hint="α = 0.40 处的 dα/dt（相邻采样差分）" />
      <Metric label="到 40% 时间" value={fmt(kinetics.time_to_40_min, 1)} unit="min" hint={kinetics.window.source === 'reaction' ? '自反应段开始' : '自首个采样（旧实验无反应段记录）'} />
      <Metric label="到 60% 时间" value={fmt(kinetics.time_to_60_min, 1)} unit="min" hint={kinetics.window.source === 'reaction' ? '自反应段开始' : '自首个采样'} />
      <Metric label={`终态${word}度`} value={fmt(kinetics.final_degree_pct, 1)} unit="%" hint={kinetics.window.end ? `至反应段结束 ${fmtClock(kinetics.window.end)}` : '至最后一个采样'} />
    </section>

    <div class="grid main-side">
      <section class="card">
        <div class="card-head"><h2>{word}度 α – 时间{fit ? ` · 叠加 ${fit.name} 拟合` : ''}</h2></div>
        <LineChart label={`${word}度曲线`} height={300} xLabel="min" yLabel="α" yMin={0} series={[
          { name: '实测 α', color: 'var(--c1)', points: kinetics.points.map((p) => [p.t_min, p.reduction_degree_pct / 100]) },
          ...(fit ? [{ name: '模型拟合', color: 'var(--c3)', dashed: true, points: fit.curve.map((c) => [c.t_min, c.alpha] as [number, number]) }] : []),
        ]} />
      </section>
      <section class="card flush">
        <div class="card-head"><div><h2>动力学模型</h2><p>点选切换叠加曲线 · 拟合区间 α = {kinetics.fit_window[0]} – {kinetics.fit_window[1]}</p></div></div>
        {#if kinetics.fits.length}
          <table class="data">
            <thead><tr><th>模型 · g(α) = k·t</th><th class="num">k / min⁻¹</th><th class="num">R²</th></tr></thead>
            <tbody>
              {#each kinetics.fits as item}
                <tr class="pick" aria-selected={item.id === model} onclick={() => (model = item.id)}>
                  <td><strong>{item.name}</strong>{#if item.id === kinetics.best_fit}<Badge tone="good">R² 最高</Badge>{/if}<div class="tiny soft mono">{item.g_expr}</div></td>
                  <td class="num mono">{item.k_per_min.toPrecision(3)}</td><td class="num mono">{item.r2.toFixed(3)}</td>
                </tr>
              {/each}
            </tbody>
          </table>
          <p class="tiny soft" style="padding:10px 14px">R² 统一按预测 α 与实测 α 计算，便于模型间比较。单一温度点不能求活化能；多温度点时再做 Arrhenius 回归。</p>
        {:else}<p class="soft small" style="padding:0 16px 16px">拟合区间内采样点不足 5 个，无法拟合。</p>{/if}
      </section>
    </div>
  {/if}

  <div class="grid halves">
    <section class="card">
      <h2 style="margin-bottom:6px">归档前复核</h2>
      <div class="checks">
        {#each review?.checks ?? [] as check}
          <div class="item"><div><strong>{check.label}</strong><span>{check.detail}</span></div>
            <Badge tone={check.severity === 'ok' ? 'good' : check.severity === 'warn' ? 'warn' : 'danger'}>{check.severity === 'ok' ? '通过' : check.severity === 'warn' ? '需说明' : '阻止归档'}</Badge></div>
        {/each}
      </div>
      {#if !archived}
        <label class="field" style="margin-top:12px"><span>复核备注{review?.note_required ? '（有需说明项，必填）' : '（可选）'}</span>
          <textarea bind:value={note} maxlength="500" placeholder="例如 报警为气瓶切换波动，数据可用"></textarea></label>
        {#if blocking.length}<div class="callout danger" style="margin-top:10px">{blocking.map((c) => c.detail).join('；')}
          {#if blocking.some((c) => c.key === 'alarms')}<div class="actions"><button class="btn sm" type="button" onclick={() => nav.go('alarms')}>去确认报警</button></div>{/if}</div>{/if}
        <p class="tiny soft" style="margin:10px 0">归档后数据与快照只读，使用上限解锁，系统回到待机。无法撤销。</p>
        <button class="btn primary" type="button" disabled={!online || !review?.can_archive || noteMissing || busy} onclick={() => (confirmArchive = true)}>确认归档并回到待机</button>
      {/if}
    </section>
    <section class="card flush">
      <div class="card-head"><h2>与同配方历史对比</h2></div>
      <table class="data">
        <thead><tr><th>实验</th><th>样品</th><th class="num">t₄₀ min</th><th class="num">t₆₀ min</th><th class="num">终态 %</th></tr></thead>
        <tbody>
          {#each compare as row}
            <tr aria-selected={row.current}><td class="mono">{row.current ? '本次 · ' : ''}{row.code}</td><td>{row.sample_name}{row.recipe_version ? ` · v${row.recipe_version}` : ''}</td>
              <td class="num mono">{fmt(row.time_to_40_min, 1)}</td><td class="num mono">{fmt(row.time_to_60_min, 1)}</td><td class="num mono">{fmt(row.final_degree_pct, 1)}</td></tr>
          {:else}<tr><td colspan="5"><div class="empty">没有同配方的已归档实验</div></td></tr>{/each}
        </tbody>
      </table>
      <p class="tiny soft" style="padding:10px 14px">不同配方版本的气氛可能不同，对比时注意版本号。已中止的实验不参与对比。</p>
    </section>
  </div>
{/if}

<ConfirmDialog open={confirmArchive} busy={busy} title={`归档 ${exp?.code ?? ''}？`} confirmLabel="确认归档"
  message="归档后原始采样、配方快照、事件与报警冻结为只读，指标按当前试样参数固化，无法撤销。"
  detail={note.trim() ? `复核备注：${note.trim()}` : ''} onconfirm={archive} oncancel={() => (confirmArchive = false)} />
