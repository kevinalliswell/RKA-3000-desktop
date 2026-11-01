<script lang="ts">
  import Badge from '../../components/Badge.svelte';
  import Metric from '../../components/Metric.svelte';
  import Seg from '../../components/Seg.svelte';
  import LineChart from '../../components/LineChart.svelte';
  import ConfirmDialog from '../../components/ConfirmDialog.svelte';
  import CommandStates from '../../components/CommandStates.svelte';
  import type { RunSession } from '../../lib/state/run.svelte';
  import type { Flows, GasKey } from '../../lib/api/types';
  import { nav } from '../../lib/state/nav.svelte';
  import { notifier } from '../../lib/state/notify.svelte';
  import {
    DASH, fmtClock, fmtDuration, fmtFlow, fmtMass, fmtMinSec, fmtPct, fmtTemp, flowsText, GAS_LABEL, runStatusLabel,
    runStatusTone, TYPE_LABEL,
  } from '../../lib/format';

  let { run, online }: { run: RunSession; online: boolean } = $props();

  type Dialog = 'stop' | 'manual' | 'auto' | 'submit' | 'reset' | null;
  let dialog = $state<Dialog>(null);
  let draft = $state<Flows>({});
  let reason = $state('');

  const rs = $derived(run.state);
  const exp = $derived(rs?.experiment ?? null);
  const live = $derived(rs?.live ?? null);
  const purging = $derived(rs?.status === 'purging');
  const terminal = $derived(rs ? ['stopped', 'completed', 'faulted'].includes(rs.status) : false);
  const allowed = $derived(rs?.allowed);
  const manual = $derived(rs?.gas_mode === 'manual' && run.inRun);
  const editableGases = $derived((rs?.gases ?? []).filter((g) => g.allowed));
  const degreeName = $derived(live?.degree_kind === 'oxidation' ? '氧化度' : '还原度');

  const t0 = $derived(run.points.length ? new Date(run.points[0]!.sampled_at).getTime() : 0);
  const toMin = (iso: string) => (new Date(iso).getTime() - t0) / 60000;
  const weightSeries = $derived(run.points.map((p) => [toMin(p.sampled_at), p.weight_g] as [number, number | null]));
  const tempSeries = $derived(run.points.map((p) => [toMin(p.sampled_at), p.temperature_c] as [number, number | null]));
  const bands = $derived.by(() => {
    const active = rs?.steps.find((s) => s.state === 'active' || s.state === 'interrupted');
    if (!active?.started_at || !t0) return [];
    const end = active.ended_at ? toMin(active.ended_at) : (weightSeries.at(-1)?.[0] ?? 0);
    return [{ x0: toMin(active.started_at), x1: end, label: `第 ${active.step_no} 段` }];
  });
  const purgePct = $derived(rs?.purge ? Math.min(100, (rs.purge.elapsed_s / Math.max(1, rs.purge.required_s)) * 100) : 0);

  function openManual() {
    const values: Flows = {};
    for (const gas of editableGases) values[gas.gas] = Number((gas.commanded ?? 0).toFixed(2));
    draft = values;
    reason = '';
  }

  // Opening the page while manual mode is already active: start from the current set-points.
  $effect(() => {
    if (manual && Object.keys(draft).length === 0 && editableGases.length) openManual();
  });

  function draftValid(): string | null {
    for (const gas of editableGases) {
      const value = draft[gas.gas];
      if (value === undefined || value === null || Number.isNaN(value) || value < 0) return `${gas.label} 请输入非负数字`;
      if (gas.usage_limit !== null && value > gas.usage_limit) return `${gas.label} 超出使用上限 ${fmtFlow(gas.usage_limit)}`;
    }
    return null;
  }

  async function confirm(text: string) {
    const which = dialog;
    if (which === 'stop') {
      const ok = await run.stop(text || '操作者提前结束');
      notifier.push(ok ? 'warn' : 'danger', ok ? '已进入惰性处置' : '提前结束未执行', ok ? '吹扫满时长且炉温低于安全温度后进入待核查' : run.error);
    } else if (which === 'manual' || which === 'auto') {
      const ok = await run.setGasMode(which);
      if (ok && which === 'manual') openManual();
      if (!ok) notifier.push('danger', '切换配气模式失败', run.error);
    } else if (which === 'submit') {
      const ok = await run.setManualGas({ ...draft }, text);
      const command = run.state?.last_command;
      if (!ok) notifier.push('danger', '手动设定未执行', run.error);
      else if (command?.state === 'failed') notifier.push('danger', '手动设定未生效', command.message);
      else notifier.push('ok', '手动设定已生效', command?.summary ?? '');
    } else if (which === 'reset') {
      const ok = await run.resetInterlock();
      if (!ok) notifier.push('danger', '联锁复位失败', run.error);
    }
    dialog = null;
  }

  async function emergency() {
    const ok = await run.emergency();
    if (ok) notifier.push('danger', '紧急停气已执行', '工艺气体归零，惰性吹扫中');
    else notifier.push('danger', '紧急停气请求失败', `${run.error} 请立即在现场手动关闭工艺气并停止加热。`);
  }

  async function togglePause() {
    const ok = rs?.status === 'paused' ? await run.resume() : await run.pause();
    if (!ok) notifier.push('danger', '操作未执行', run.error);
  }
</script>

{#if !rs || rs.status === 'idle' || !exp}
  <div class="page-head"><div><h1>当前实验</h1><p>没有运行中的实验。</p></div></div>
  <section class="card"><div class="empty"><strong>待机 · 无运行中实验</strong>在实验准备中完成三步预检后启动实验。
    <div class="row" style="justify-content:center;margin-top:12px"><button class="btn primary" type="button" onclick={() => nav.go('preflight')}>去实验准备</button></div></div></section>
{:else}
  <div class="page-head">
    <div>
      <div class="row" style="margin-bottom:6px">
        <Badge tone={runStatusTone[rs.status]} live={run.active}>{rs.status === 'running' || rs.status === 'paused' ? `${runStatusLabel[rs.status]} · 第 ${rs.current_step_no} / ${rs.total_steps} 段` : runStatusLabel[rs.status]}</Badge>
        <span class="mono soft">{fmtDuration(rs.elapsed_s)}</span>
        {#if rs.temperature_mode === 'program'}<Badge>温度程序由仪表执行</Badge>{/if}
      </div>
      <h1>{exp.code} · {exp.sample_name}</h1>
      <p>{TYPE_LABEL[exp.experiment_type]} · 配方 {exp.recipe_name} v{exp.recipe_version}（快照）· 惰性气 {GAS_LABEL[exp.inert_gas]} · 启动 {fmtClock(exp.started_at)} · 操作者 {exp.operator}</p>
    </div>
    <div class="actions">
      {#if allowed?.reset_interlock}<button class="btn" type="button" onclick={() => (dialog = 'reset')}>联锁复位</button>{/if}
      {#if allowed?.pause || allowed?.resume}
        <button class="btn" type="button" disabled={run.busy !== null} onclick={togglePause}>{rs.status === 'paused' || rs.status === 'interrupted' ? '恢复' : '暂停'}</button>
      {/if}
      <button class="btn" type="button" disabled={!online || !allowed?.stop || run.busy !== null} onclick={() => (dialog = 'stop')}
        title={allowed?.stop ? '' : '惰性处置中或已结束'}>提前结束并处置</button>
    </div>
  </div>

  {#if purging && rs.purge}
    <div class={`callout ${rs.emergency || rs.end_reason === 'alarm' || rs.end_reason === 'fault' ? 'danger' : 'warn'}`} role="status">
      <strong>{rs.emergency ? '紧急停气已执行并锁存。' : rs.end_reason === 'completed' ? '配方最后一段：惰性处置中。' : `${rs.end_reason_text ?? '实验已结束'}，惰性处置中。`}</strong>
      {rs.purge.summary} 吹扫；加热：{rs.purge.heating_text}。吹扫满 {Math.round(rs.purge.required_s)} s 且炉温低于 {rs.purge.safe_temperature_c} ℃ 后进入“待核查”；期间所有调气控件不可用。
      {#if rs.end_detail && rs.end_reason !== 'completed'}<div>原因：{rs.end_detail}</div>{/if}
      {#if rs.purge.apply_error}<div><strong>{rs.purge.apply_error}</strong></div>{/if}
      <div class="row" style="margin-top:8px">
        <div class="progress fill" aria-label="吹扫进度"><div style={`width:${purgePct}%`}></div></div>
        <span class="mono small">{Math.round(rs.purge.elapsed_s)} / {Math.round(rs.purge.required_s)} s · {fmtTemp(live?.temperature_c)} ℃ {rs.purge.temperature_ok ? '✓' : `> ${rs.purge.safe_temperature_c}`}</span>
      </div>
    </div>
  {:else if terminal}
    <div class={`callout ${rs.status === 'completed' ? 'good' : 'warn'}`} role="status">
      <strong>实验已结束 · 待核查。</strong> {rs.end_reason_text ?? ''}{rs.end_detail && rs.end_reason !== 'completed' ? `：${rs.end_detail}` : ''}。
      归档前不能开始下一次实验。{#if rs.error}<div>{rs.error}</div>{/if}
      <div class="actions"><button class="btn sm" type="button" onclick={() => nav.go('analysis', rs.experiment_id)}>去分析与归档</button></div>
    </div>
  {:else if rs.status === 'interrupted'}
    <div class="callout danger"><strong>{rs.status_text}</strong> 联锁：{rs.interlock.text} · 报警：{rs.alarm.text}</div>
  {/if}
  {#if rs.stale_devices.length}
    <div class="callout warn"><strong>回读过期：{rs.stale_devices.join('、')}。</strong> 数值显示为 —，该段数据不入库；手动调气已禁用，但不自动停机。请到现场核实连接。</div>
  {/if}
  {#if run.pollError}<div class="callout warn">状态刷新失败：{run.pollError}</div>{/if}

  <section class="card">
    <div class="phases">
      {#each rs.steps as s}
        <div class={`phase ${s.state}`}>
          <span class="n">{s.state === 'done' ? '✓' : s.step_no}</span>
          <div>
            <div class="t">{s.display_name} {#if s.kind === 'reaction'}<Badge tone={exp.experiment_type === 'reduction' ? 'tred' : 'tox'}>反应段</Badge>{/if}</div>
            <div class="d">{fmtTemp(s.target_temp_c)} ℃{s.ramp_rate_cpm ? ` @${s.ramp_rate_cpm} ℃/min` : ''} · {flowsText(s.flows)} · 保持 {s.hold_seconds} s</div>
            {#if s.state === 'active' && rs.step_progress && s.step_no === rs.step_progress.step_no}
              <div class="bar"><div style={`width:${Math.min(100, (rs.step_progress.hold_elapsed_s / Math.max(1, rs.step_progress.hold_s)) * 100)}%`}></div></div>
            {/if}
          </div>
          <span class="tiny soft mono">
            {#if s.state === 'done'}已完成{:else if s.state === 'active' && rs.step_progress}{rs.step_progress.target_reached ? `${fmtMinSec(rs.step_progress.hold_elapsed_s)} / ${fmtMinSec(s.hold_seconds)}` : '升温中'}{:else if s.state === 'active'}进行中{:else if s.state === 'interrupted'}已中断{:else if s.state === 'skipped'}未执行{:else}待执行{/if}
          </span>
        </div>
      {/each}
    </div>
  </section>

  <section class="grid metrics">
    <Metric label="炉温 PV / SP" value={`${fmtTemp(live?.temperature_c)} / ${fmtTemp(live?.target_temp_c)}`} unit="℃"
      hint={live?.temperature_c == null ? '回读过期 · 等待有效读数' : live?.target_temp_c != null ? `偏差 ${fmtTemp((live.temperature_c ?? 0) - live.target_temp_c)} ℃` : terminal ? '实验已结束 · 最后读数' : '处置中，不跟踪设定'} />
    <Metric label="样品重量" value={fmtMass(live?.weight_g)} unit="g"
      hint={live?.delta_m_g != null ? `Δm ${live.delta_m_g >= 0 ? '+' : ''}${fmtMass(live.delta_m_g)} g · 基准 ${fmtMass(live.reference_weight_g)} g` : live?.weight_g == null ? '回读过期 · 等待有效读数' : '反应段开始后计算 Δm'} />
    <Metric label={`${degreeName} α`} value={fmtPct(live?.degree_pct)} unit="%"
      hint={live?.reaction_started_at ? `测定计时自 ${fmtClock(live.reaction_started_at)}` : '反应段开始后计时'} />
    <Metric label="总供气流量" value={fmtFlow(live?.total_flow_lpm)} unit="L/min" hint={live?.flow_summary ?? DASH} />
  </section>

  <div class="grid main-side">
    <div class="stack">
      <section class="card">
        <div class="card-head"><h2>重量与炉温 · 全程</h2><span class="tiny soft">x：分钟</span></div>
        <LineChart label="重量与炉温曲线" height={280} bands={bands} xLabel="min" yLabel="样品重量 g" y2Label="炉温 ℃" series={[
          { name: '样品重量 g（左轴）', color: 'var(--c1)', points: weightSeries },
          { name: '炉温 ℃（右轴）', color: 'var(--c2)', points: tempSeries, axis: 'right', dashed: true },
        ]} />
      </section>
      <section class="card">
        <div class="card-head"><h2>事件与命令记录</h2><span class="tiny soft">最新在上</span></div>
        <div class="events">
          {#each rs.events as event}
            <div class={`ev ${event.kind}`}><time>{fmtClock(event.at)}</time><strong>{event.title}</strong><span>{event.detail}{event.actor !== '系统' ? ` · ${event.actor}` : ''}</span></div>
          {:else}<p class="soft small">暂无事件</p>{/each}
        </div>
      </section>
    </div>

    <div class="stack">
      <section class="card">
        <div class="card-head">
          <div><h2>供气</h2><p>{TYPE_LABEL[exp.experiment_type]}允许 {editableGases.map((g) => g.label).join(' / ')}</p></div>
          <Seg label="配气模式" value={rs.gas_mode} disabled={!allowed?.set_gas_mode || run.busy !== null}
            onselect={(id) => (dialog = id as 'manual' | 'auto')} options={[{ id: 'auto', label: '按配方' }, { id: 'manual', label: '手动' }]} />
        </div>
        <div class="gascards">
          {#each rs.gases as gas}
            <div class={`gascard ${gas.allowed ? '' : 'disabled'}`}>
              <div class="top"><span class="gas">{gas.label}</span>
                <Badge tone={gas.state === 'flowing' ? 'good' : gas.state === 'purging' ? 'danger' : ''}>{gas.state === 'flowing' ? '供气中' : gas.state === 'purging' ? '吹扫中' : gas.state === 'disabled' ? '本次禁用' : '已关闭'}</Badge></div>
              <div class="pv">{fmtFlow(gas.pv)}<small>L/min 实测</small></div>
              {#if manual && gas.allowed}
                <label class="field"><span>目标流量 · 上限 {fmtFlow(gas.usage_limit)}</span>
                  <input class="mono" type="number" min="0" step="0.01" max={gas.usage_limit ?? undefined} value={draft[gas.gas] ?? ''}
                    aria-invalid={(draft[gas.gas] ?? 0) > (gas.usage_limit ?? Infinity)}
                    oninput={(e) => (draft = { ...draft, [gas.gas]: e.currentTarget.value === '' ? NaN : Number(e.currentTarget.value) })}
                    disabled={!allowed?.manual_gas || run.busy !== null} /></label>
              {:else}
                <div class="meta">设定 {fmtFlow(gas.commanded)}{gas.readback !== null ? ` · 回读 ${fmtFlow(gas.readback)}` : ''}</div>
              {/if}
              <div class="meta">{gas.hazard ? `${gas.hazard} · ` : ''}使用上限 {fmtFlow(gas.usage_limit)} · 设备 {fmtFlow(gas.device_limit)}</div>
            </div>
          {/each}
        </div>
        {#if manual}
          <div class="stack tight" style="margin-top:12px">
            <p class="tiny soft">手动值须 ≤ 使用上限，且只能填本次类型允许的气体。提交后命令经三态确认，回读不一致自动回退到配方值。</p>
            {#if !allowed?.manual_gas && rs.blocked.manual_gas}<div class="callout warn">{rs.blocked.manual_gas}</div>{/if}
            <CommandStates command={rs.last_command?.kind === 'manual_gas' ? rs.last_command : null} pending={run.busy === 'manual-gas'} />
            {#if rs.last_command?.state === 'failed'}<p class="tiny" style="color:var(--danger)">{rs.last_command.message}</p>{/if}
            <button class="btn primary" type="button" disabled={!online || !allowed?.manual_gas || run.busy !== null || draftValid() !== null}
              title={draftValid() ?? ''} onclick={() => (dialog = 'submit')}>
              {#if run.busy === 'manual-gas'}<span class="spinner" aria-hidden="true"></span>{/if}提交手动设定（{flowsText(draft)}）
            </button>
          </div>
        {:else if run.inRun}
          <p class="tiny soft" style="margin-top:10px">按配方阶段自动配气。切换到手动需二次确认；回到按配方会重新下发当前阶段的气体设定。</p>
        {/if}
      </section>

      <section class="estop" aria-label="紧急停气">
        <h2>紧急停气 / 惰性吹扫</h2>
        <p class="small">立即关闭全部工艺气，{GAS_LABEL[exp.inert_gas]} 以 {fmtFlow(exp.purge_lpm)} L/min 吹扫并停止加热。<strong>点击即执行，不弹二次确认</strong>；执行后锁存，直到处置完成。</p>
        <button class="btn danger" type="button" disabled={!allowed?.emergency || run.emergencyBusy} onclick={emergency}>
          {#if run.emergencyBusy}<span class="spinner" aria-hidden="true"></span>{/if}{rs.emergency ? '已执行 · 吹扫中' : `■ 紧急停气并充 ${GAS_LABEL[exp.inert_gas]}`}
        </button>
        {#if rs.temperature_mode === 'program'}<p class="tiny">温控仪不支持远程停止：按下后请同时在温控器面板停止程序。</p>{/if}
      </section>
    </div>
  </div>
{/if}

<ConfirmDialog open={dialog === 'stop'} tone="danger" title="提前结束实验？" confirmLabel="结束并进入惰性处置" busy={run.busy === 'stop'}
  message="剩余阶段不再执行。工艺气体归零、惰性气吹扫并停止加热；吹扫满时长且炉温低于安全温度后进入待核查。"
  input={{ label: '结束原因（可选，写入审计）', placeholder: '例如 样品破裂' }} onconfirm={confirm} oncancel={() => (dialog = null)} />
<ConfirmDialog open={dialog === 'manual'} title="切换到手动配气？" confirmLabel="确认切换" busy={run.busy === 'gas-mode'}
  message="实验运行中切换配气模式需要二次确认。切换后气体保持当前设定，直到你提交新的手动设定。"
  onconfirm={confirm} oncancel={() => (dialog = null)} />
<ConfirmDialog open={dialog === 'auto'} title="切回按配方配气？" confirmLabel="确认切换" busy={run.busy === 'gas-mode'}
  message="将立即重新下发当前阶段的配方气体设定。" onconfirm={confirm} oncancel={() => (dialog = null)} />
<ConfirmDialog open={dialog === 'submit'} title="下发手动气体设定？" confirmLabel="下发" busy={run.busy === 'manual-gas'}
  message={`目标：${flowsText(draft)} L/min`} detail="命令依次经过 已受理 → 回读验证 → 生效；回读不一致视为失败并回退到配方值。"
  input={{ label: '调气原因（必填）', placeholder: '例如 微调还原势，对照 A-18', minLength: 2 }} onconfirm={confirm} oncancel={() => (dialog = null)} />
<ConfirmDialog open={dialog === 'reset'} title="执行联锁复位？" confirmLabel="复位" busy={run.busy === 'reset'}
  message="仅在报警已解除并确认、急停已释放时可用。" onconfirm={confirm} oncancel={() => (dialog = null)} />
