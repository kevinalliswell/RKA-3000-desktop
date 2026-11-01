<script lang="ts">
  import Metric from '../../components/Metric.svelte';
  import Badge from '../../components/Badge.svelte';
  import type { RunSession } from '../../lib/state/run.svelte';
  import type { Overview } from '../../lib/api/types';
  import { nav } from '../../lib/state/nav.svelte';
  import {
    DASH, END_REASON, fmtClock, fmtDuration, fmtFlow, fmtMass, fmtMinSec, fmtPct, fmtShort, fmtTemp, runStatusLabel, runStatusTone,
    TYPE_LABEL,
  } from '../../lib/format';

  let { run, summary, online }: { run: RunSession; summary: Overview | null; online: boolean } = $props();

  const rs = $derived(run.state);
  const exp = $derived(rs?.experiment ?? null);
  const live = $derived(rs?.live ?? null);
  const active = $derived(run.active);
  const pendingReview = $derived(summary?.pending_review ?? []);
  const alarms = $derived(rs?.pending_alarms ?? summary?.pending_alarms ?? []);
  const canPrepare = $derived(online && !active && pendingReview.length === 0);
  const prepareHint = $derived(active ? '有实验在运行时不能开始新实验' : pendingReview.length ? '上一次实验未归档，请先完成复核' : '');
  const currentStep = $derived(rs?.steps.find((s) => s.state === 'active') ?? null);
  const nextStep = $derived(rs && currentStep ? rs.steps[rs.steps.indexOf(currentStep) + 1] ?? null : null);
  const lastStep = $derived(rs?.steps.at(-1) ?? null);
  const holdLeft = $derived(rs?.step_progress ? Math.max(0, rs.step_progress.hold_s - rs.step_progress.hold_elapsed_s) : null);
  const events = $derived(active ? (rs?.events ?? []).slice(0, 6) : (summary?.events ?? []));
  const degreeName = $derived(live?.degree_kind === 'oxidation' ? '氧化度' : '还原度');
</script>

<div class="page-head">
  <div>
    <h1>实时总览</h1>
    <p>有实验在运行就显示它；没有就引导去实验准备。四个指标与当前实验页一致。</p>
  </div>
  <div class="actions">
    <button class="btn" type="button" disabled={!canPrepare} title={prepareHint} onclick={() => nav.go('preflight')}>
      {canPrepare ? '开始实验准备' : `实验准备（${active ? '运行中' : '待归档'}不可用）`}
    </button>
  </div>
</div>

{#if active && rs && exp}
  <section class="hero" aria-label="当前实验">
    <div class="main-part">
      <p class="eyebrow">CURRENT EXPERIMENT</p>
      <h2>{exp.code} · {exp.sample_name}</h2>
      <p>
        {TYPE_LABEL[exp.experiment_type]} · 配方 {exp.recipe_name} v{exp.recipe_version} 快照 ·
        {#if rs.status === 'purging'}惰性处置中，{rs.status_text}{:else}当前第 {rs.current_step_no} / {rs.total_steps} 段 {currentStep?.display_name ?? ''}{#if holdLeft !== null && rs.step_progress?.target_reached}，本段剩余约 {fmtMinSec(holdLeft)}{/if}{/if}。原始采样与操作事件持续记录。
      </p>
      <div class="row" style="margin-top:6px">
        <button class="btn light" type="button" onclick={() => nav.go('current')}>查看当前实验 →</button>
        {#if alarms.length}<button class="btn ghost" type="button" onclick={() => nav.go('alarms')}>处理待确认报警</button>{/if}
      </div>
    </div>
    <div class="side">
      <div><span>运行阶段</span><br /><strong style="font-size:15px">{rs.status === 'purging' ? '惰性处置' : `${currentStep?.display_name ?? DASH} · 第 ${rs.current_step_no} / ${rs.total_steps} 段`}</strong></div>
      <div><span>运行时长</span><br /><strong class="mono" style="font-size:20px">{fmtDuration(rs.elapsed_s)}</strong></div>
      <div><span>数据完整性</span><br /><strong>{rs.stale_devices.length ? '回读过期，该段不入库' : `正常 · 最新采样 ${live?.sample_age_s != null ? live.sample_age_s.toFixed(1) : DASH} s 前`}</strong></div>
    </div>
  </section>
{:else if pendingReview.length}
  <section class="hero" aria-label="待核查实验">
    <div class="main-part">
      <p class="eyebrow">AWAITING REVIEW</p>
      <h2>{pendingReview[0]!.code} · {pendingReview[0]!.sample_name ?? pendingReview[0]!.name}</h2>
      <p>实验已结束（{END_REASON[pendingReview[0]!.end_reason ?? ''] ?? '已结束'}），等待复核归档。归档前不能开始下一次实验，气体使用上限保持锁定。</p>
      <div class="row" style="margin-top:6px">
        <button class="btn light" type="button" onclick={() => nav.go('analysis', pendingReview[0]!.id)}>去分析与归档 →</button>
      </div>
    </div>
    <div class="side">
      <div><span>结束时间</span><br /><strong>{fmtShort(pendingReview[0]!.finished_at)}</strong></div>
      <div><span>待核查实验</span><br /><strong class="mono" style="font-size:20px">{pendingReview.length}</strong></div>
    </div>
  </section>
{:else}
  <section class="hero" aria-label="待机">
    <div class="main-part">
      <p class="eyebrow">STANDBY</p>
      <h2>待机 · 无运行中实验</h2>
      <p>上一次实验已归档。开始新实验前，在实验准备中依次完成：样品与配方 → 设备与现场 → 复核与启动。</p>
      <div class="row" style="margin-top:6px">
        <button class="btn light" type="button" disabled={!canPrepare} onclick={() => nav.go('preflight')}>开始实验准备 →</button>
        <button class="btn ghost" type="button" onclick={() => nav.go('recipes')}>查看实验配方</button>
      </div>
    </div>
    <div class="side">
      <div><span>可执行配方</span><br /><strong class="mono" style="font-size:20px">{summary ? summary.recipe_count - summary.blocked_recipes.length : DASH} / {summary?.recipe_count ?? DASH}</strong></div>
      <div><span>使用上限策略</span><br /><strong>v{summary?.limits_version ?? DASH} · 待机可配置</strong></div>
    </div>
  </section>
{/if}

<section class="grid metrics" aria-label="关键指标">
  <Metric label="炉温 PV / SP" value={`${fmtTemp(live?.temperature_c)} / ${fmtTemp(live?.target_temp_c)}`} unit="℃"
    hint={active ? (live?.temperature_c == null ? '回读过期 · 等待有效读数' : '最近采样') : '无运行中实验'} />
  <Metric label="样品重量" value={fmtMass(live?.weight_g)} unit="g"
    hint={live?.delta_m_g != null ? `Δm ${live.delta_m_g >= 0 ? '+' : ''}${fmtMass(live.delta_m_g)} g · ${degreeName} ${fmtPct(live.degree_pct)}%` : '测定计时开始后计算'} />
  <Metric label="总供气流量" value={fmtFlow(live?.total_flow_lpm)} unit="L/min" hint={live?.flow_summary ?? DASH} />
  <Metric label="待确认报警" value={String(alarms.length)} unit="条" tone={alarms.length ? 'warn' : ''}
    hint={alarms[0]?.message ?? '无待确认报警'} />
</section>

<div class="grid thirds">
  <section class="card">
    <h2 style="margin-bottom:8px">接下来会发生什么</h2>
    <ol class="small" style="margin:0;padding-left:18px;line-height:1.7">
      {#if active && rs}
        {#if rs.status === 'purging' && rs.purge}
          <li>惰性处置：{rs.purge.summary}，吹扫 {Math.round(rs.purge.elapsed_s)} / {Math.round(rs.purge.required_s)} s</li>
          <li>吹扫满时长且炉温 &lt; {rs.purge.safe_temperature_c} ℃ → 状态变为“待核查”</li>
          <li>操作者到 <button class="linkish" type="button" onclick={() => nav.go('analysis', rs.experiment_id)}>分析与归档</button> 复核并归档</li>
        {:else}
          {#if currentStep}<li><strong>第 {currentStep.step_no} 段 {currentStep.display_name}</strong>：{rs.step_progress?.target_reached ? `保温剩余约 ${fmtMinSec(holdLeft)}` : `升温至 ${fmtTemp(currentStep.target_temp_c)} ℃ 后开始计时`}</li>{/if}
          {#if nextStep && nextStep !== lastStep}<li>进入第 {nextStep.step_no} 段 {nextStep.display_name}（{fmtTemp(nextStep.target_temp_c)} ℃）</li>{/if}
          {#if lastStep}<li>第 {lastStep.step_no} 段 {lastStep.display_name}：纯惰性吹扫满时长且炉温 &lt; 安全温度 → “完成 · 待核查”，指标自动计算</li>{/if}
          <li>到分析与归档复核并归档；归档后使用上限解锁，可开始下一次</li>
        {/if}
      {:else if pendingReview.length}
        <li>到分析与归档复核 {pendingReview[0]!.code}：采样完整性、报警确认、配方快照、安全完成依据</li>
        <li>填写备注（如有需说明项）并归档；归档后数据只读</li>
        <li>归档后使用上限解锁，可开始下一次实验准备</li>
      {:else}
        <li>实验准备第 1 步：填写样品，选择实验类型与可执行配方</li>
        <li>第 2 步：确认三台设备回读新鲜，逐项勾选现场检查</li>
        <li>第 3 步：复核启动条件后确认启动；配方快照与使用上限随即锁定</li>
      {/if}
    </ol>
    <p class="tiny soft" style="margin-top:10px;line-height:1.6">期间若触发报警或按下紧急停气，直接进入惰性处置，不再执行剩余阶段。</p>
  </section>

  <section class="card">
    <h2 style="margin-bottom:4px">最近事件</h2>
    {#each events as event}
      <div class={`ev ${event.kind}`}><time>{fmtClock(event.at)}</time><strong>{event.title}</strong><span>{event.detail}{event.actor && event.actor !== '系统' ? ` · ${event.actor}` : ''}</span></div>
    {:else}
      <p class="soft small" style="padding:10px 0">暂无事件。实验启动后，阶段切换、命令和报警会显示在这里。</p>
    {/each}
  </section>

  <section class="card">
    <h2 style="margin-bottom:4px">待办</h2>
    {#if alarms.length}
      <div class="todo"><div><strong>确认 {alarms.length} 条报警</strong><span>未确认前禁止启动与手动调气</span></div><button class="linkish" type="button" onclick={() => nav.go('alarms')}>去处理</button></div>
    {/if}
    {#each pendingReview as item}
      <div class="todo"><div><strong>复核归档 · {item.code}</strong><span>未归档前不能开始下一次实验</span></div><button class="linkish" type="button" onclick={() => nav.go('analysis', item.id)}>去归档</button></div>
    {/each}
    {#each (summary?.blocked_recipes ?? []).slice(0, 3) as recipe}
      <div class="todo"><div><strong>配方 {recipe.name} 不可执行</strong><span>{recipe.summary}</span></div><button class="linkish" type="button" onclick={() => nav.go('recipes')}>查看</button></div>
    {/each}
    {#if !alarms.length && !pendingReview.length && !(summary?.blocked_recipes.length)}
      <p class="soft small" style="padding:10px 0">没有待办事项。</p>
    {/if}
  </section>
</div>

{#if summary?.recent.length}
  <section class="card flush">
    <div class="card-head"><h2>最近实验</h2><button class="btn sm" type="button" onclick={() => nav.go('history')}>全部历史</button></div>
    <div class="table-wrap">
      <table class="data">
        <thead><tr><th>实验编号</th><th>样品</th><th>配方</th><th>开始</th><th>状态</th></tr></thead>
        <tbody>
          {#each summary.recent as item}
            <tr class="pick" onclick={() => nav.go(item.category === 'pending' ? 'analysis' : 'history', item.id)}>
              <td class="mono">{item.code}</td><td>{item.sample_name ?? item.name}</td>
              <td>{item.recipe_name ?? DASH}{item.recipe_version ? ` v${item.recipe_version}` : ''}</td>
              <td class="mono">{fmtShort(item.started_at)}</td>
              <td><Badge tone={item.category === 'running' ? runStatusTone.running : item.category === 'pending' ? 'warn' : item.category === 'aborted' ? 'danger' : 'good'}>
                {item.category === 'running' ? runStatusLabel.running : item.category === 'pending' ? '待核查' : item.category === 'aborted' ? '已中止' : '已归档'}</Badge></td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  </section>
{/if}
