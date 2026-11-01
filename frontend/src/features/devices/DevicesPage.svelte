<script lang="ts">
  import { onMount } from 'svelte';
  import ConfirmDialog from '../../components/ConfirmDialog.svelte';
  import Badge from '../../components/Badge.svelte';
  import * as api from '../../lib/api/endpoints';
  import type { DeviceDescription, DeviceStatus, LimitsState } from '../../lib/api/types';
  import type { RunSession } from '../../lib/state/run.svelte';
  import { notifier } from '../../lib/state/notify.svelte';
  import { nav } from '../../lib/state/nav.svelte';
  import { errorMessage } from '../../lib/api/client';
  import { DEVICE_LABEL, fmtFlow, fmtMass, fmtTemp, GAS_LABEL } from '../../lib/format';

  let { run, online }: { run: RunSession; online: boolean } = $props();

  let status = $state<DeviceStatus | null>(null);
  let description = $state<DeviceDescription | null>(null);
  let limits = $state<LimitsState | null>(null);
  let error = $state('');
  let busy = $state(false);
  let setpoints: Record<number, number> = $state({});
  let temperature = $state(25);
  let pending = $state<'mfc' | 'temperature' | 'tare' | null>(null);
  let timer: ReturnType<typeof setTimeout> | undefined;

  const active = $derived(run.active);
  // While a run owns the devices the page shows the run's own readings instead of polling the bus a second time.
  const stale = $derived(active ? (run.state?.stale_devices ?? []) : (status?.degraded_devices ?? []));
  const tempValue = $derived(active ? run.state?.live?.temperature_c : status?.temperature_c);
  const weightValue = $derived(active ? run.state?.live?.weight_g : status?.weight_g);
  const usage = (gas: string) => limits?.gases.find((g) => g.gas === gas.toUpperCase())?.usage_limit ?? null;

  async function refresh() {
    try {
      if (!description) description = await api.describeDevices();
      if (!limits) limits = await api.getLimits();
      if (!active) {
        status = await api.deviceStatus();
        for (const channel of status.mfc ?? []) if (!(channel.address in setpoints)) setpoints[channel.address] = channel.setpoint_lpm;
      }
      error = '';
    } catch (e) { error = errorMessage(e); }
  }

  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(async () => { if (online) await refresh(); schedule(); }, 2000);
  }

  onMount(() => { void refresh(); schedule(); return () => clearTimeout(timer); });

  async function connect() {
    busy = true;
    try { await api.connectDevices(); notifier.push('ok', '设备已连接'); await refresh(); } catch (e) { error = errorMessage(e); } finally { busy = false; }
  }

  async function confirm() {
    const action = pending;
    pending = null;
    if (!action) return;
    busy = true;
    try {
      if (action === 'mfc') {
        status = await api.setMfcSetpoints(Object.entries(setpoints).map(([address, lpm]) => ({ address: Number(address), lpm: Number(lpm) })));
        notifier.push('ok', '流量设定已下发');
      } else if (action === 'temperature') {
        status = await api.setDeviceTemperature(Number(temperature));
        notifier.push('ok', '温度设定已下发');
      } else {
        const result = await api.tareBalance();
        notifier.push(result.ok ? 'ok' : 'warn', result.ok ? '天平已去皮' : '天平未确认去皮');
      }
      error = '';
    } catch (e) { error = errorMessage(e); } finally { busy = false; }
  }

  const canWrite = $derived(online && !active && !busy && status?.connected === true);
  const channelRows = $derived((description?.mfc_channels ?? []).map((channel) => {
    const live = status?.mfc?.find((m) => m.address === channel.address);
    const gasCard = run.state?.gases.find((g) => g.gas === channel.gas.toUpperCase());
    const sp = active ? (gasCard?.commanded ?? null) : (live?.setpoint_lpm ?? null);
    const pv = active ? (gasCard?.pv ?? null) : (live?.flow_lpm ?? null);
    const deviation = sp && pv !== null && sp > 0 ? ((pv - sp) / sp) * 100 : null;
    return { ...channel, sp, pv, deviation, disabled: active && gasCard ? !gasCard.allowed : false };
  }));
  const devices = $derived((description?.devices ?? []).map((d) => ({ ...d, fresh: !stale.includes(d.name) })));
</script>

<div class="page-head">
  <div>
    <h1>设备诊断</h1>
    <p>三台设备的回读新鲜度是所有控制的前提：任一台过期，界面降级显示（数值为 —），并禁止启动与手动调气，但不自动停机。</p>
  </div>
  <div class="actions">
    {#if description}<Badge tone={description.simulation ? 'warn' : 'good'}>{description.simulation ? '仿真' : '实机'}</Badge>{/if}
    <Badge tone={stale.length ? 'warn' : 'good'} dot>{stale.length ? `${stale.length} 台设备回读过期 · 控制受限` : '设备回读正常'}</Badge>
    <button class="btn sm" type="button" onclick={connect} disabled={!online || busy || active}>连接设备</button>
  </div>
</div>

{#if error}<div class="callout danger" role="alert"><strong>设备操作未完成。</strong> {error}</div>{/if}
{#if stale.length}
  <div class="callout warn"><strong>{stale.map((d) => DEVICE_LABEL[d] ?? d).join('、')}无有效回读。</strong> 读数显示为 —{active ? '，当前实验继续加热与供气，但手动调气已禁用，该段数据不入库' : '，实验准备中“设备回读新鲜”不通过'}。请到现场核实串口连接；恢复回读后自动解除。</div>
{/if}
{#if active}<div class="callout">实验运行中，设备由实验流程控制，此页只读显示运行数据。手动配气请在 <button class="linkish" type="button" onclick={() => nav.go('current')}>当前实验</button> 切换到手动并二次确认。</div>{/if}

{#if status && !status.supported && !active}
  <div class="callout warn">当前设备通路（PLC Modbus）不提供按设备查看的状态；实时数据见当前实验页。</div>
{:else}
  <div class="grid thirds">
    {#each devices as device}
      <section class="card">
        <div class="row between"><h2>{device.label}</h2><Badge tone={device.fresh ? 'good' : 'warn'} dot>{device.fresh ? '回读正常' : '回读过期'}</Badge></div>
        <div class="metric" style="border:0;padding:10px 0;background:none">
          <div class="v">
            {#if device.name === 'temp'}{fmtTemp(device.fresh ? tempValue : null)}<small>℃ PV</small>
            {:else if device.name === 'mfc'}{fmtFlow(device.fresh ? channelRows.reduce((a, r) => a + (r.pv ?? 0), 0) : null)}<small>L/min 总流量 · {channelRows.length} 通道</small>
            {:else}{fmtMass(device.fresh ? weightValue : null)}<small>g · 分辨率 0.001</small>{/if}
          </div>
        </div>
        <dl class="kv">
          <dt>端口</dt><dd class="mono">{device.port || (description?.simulation ? '仿真' : '未配置')}</dd>
          {#if device.slave_id}<dt>从站</dt><dd class="mono">{device.slave_id}</dd>{/if}
          {#if device.protocol}<dt>协议</dt><dd>{device.protocol}</dd>{/if}
          <dt>作用</dt><dd>{device.name === 'temp' ? '炉温采集与温度程序下发' : device.name === 'mfc' ? '气体流量设定与实测' : '样品重量采集'}</dd>
        </dl>
      </section>
    {/each}
  </div>

  <section class="card flush">
    <div class="card-head"><div><h2>MFC 通道 · 设备上限与使用上限</h2><p>设备上限 = 通道满量程；使用上限在系统设置中维护。</p></div>
      <button class="btn sm" type="button" onclick={() => nav.go('settings')}>使用上限设置 →</button></div>
    <div class="table-wrap">
      <table class="data">
        <thead><tr><th>通道</th><th>气体</th><th class="num">设备上限</th><th class="num">使用上限</th><th class="num">设定 SP</th><th class="num">实测 PV</th><th class="num">偏差</th><th>状态</th>{#if !active}<th>空闲手动设定</th>{/if}</tr></thead>
        <tbody>
          {#each channelRows as row}
            <tr>
              <td class="mono">MFC-{String(row.address).padStart(2, '0')}</td>
              <td>{row.label ?? row.gas}</td>
              <td class="num mono">{fmtFlow(row.full_scale_lpm)}</td>
              <td class="num mono">{fmtFlow(usage(row.gas))}</td>
              <td class="num mono">{fmtFlow(row.sp)}</td>
              <td class="num mono">{stale.includes('mfc') ? '—' : fmtFlow(row.pv)}</td>
              <td class="num mono">{row.deviation === null ? '—' : `${row.deviation >= 0 ? '+' : ''}${row.deviation.toFixed(1)}%`}</td>
              <td>{#if row.disabled}<Badge>本次禁用</Badge>{:else if (row.sp ?? 0) > 0}<Badge tone={Math.abs(row.deviation ?? 0) > 10 ? 'warn' : 'good'}>供气中</Badge>{:else}<Badge>已关闭</Badge>{/if}</td>
              {#if !active}<td><input type="number" min="0" max={row.full_scale_lpm} step="0.01" bind:value={setpoints[row.address]} disabled={!canWrite} aria-label={`MFC ${row.address} 设定`} /></td>{/if}
            </tr>
          {:else}<tr><td colspan="9"><div class="empty">没有配置 MFC 通道</div></td></tr>{/each}
        </tbody>
      </table>
    </div>
    {#if !active && status?.supported}
      <div class="row" style="padding:12px 16px">
        <button class="btn" type="button" disabled={!canWrite} onclick={() => (pending = 'mfc')}>下发全部流量设定（空闲调试）</button>
        <span class="tiny soft">仅用于空闲时的设备调试；实验中流量由配方或手动配气控制。</span>
      </div>
    {/if}
  </section>

  {#if !active && status?.supported}
    <div class="grid halves">
      <section class="card">
        <h2 style="margin-bottom:10px">温控仪 · 空闲调试</h2>
        <div class="row">
          <label class="field" style="max-width:200px"><span>目标 SV (℃)</span><input type="number" min="0" max="1600" step="0.1" bind:value={temperature} disabled={!canWrite} /></label>
          <button class="btn" type="button" style="align-self:end" disabled={!canWrite} onclick={() => (pending = 'temperature')}>下发温度设定</button>
        </div>
        {#if description?.temperature_program}
          <p class="tiny soft" style="margin-top:10px">实验中温度由仪表程序执行：程序组 {description.temperature_program.group}，段时间单位 {description.temperature_program.time_unit}，最多 {description.temperature_program.max_steps} 个配方段。仪表不支持远程启动或停止，需在面板上操作。</p>
        {/if}
      </section>
      <section class="card">
        <h2 style="margin-bottom:10px">电子天平</h2>
        <div class="row"><span>重量 <strong class="mono">{fmtMass(weightValue)} g</strong></span><span class="fill"></span>
          <button class="btn" type="button" disabled={!canWrite} onclick={() => (pending = 'tare')}>去皮</button></div>
        <p class="tiny soft" style="margin-top:10px">实验准备第 2 步要求“天平已去皮并放入样品”，启动时以天平读数核对初始质量。</p>
      </section>
    </div>
  {/if}
{/if}

<p class="tiny soft">联锁与气体探头：多设备通路未接入硬件联锁与可燃气探头，相应状态由现场设备保证，并在预检“现场检查”中由操作者确认。PLC 通路的联锁状态在当前实验页显示。可用气体：{(description?.mfc_channels ?? []).map((c) => GAS_LABEL[c.gas.toUpperCase() as keyof typeof GAS_LABEL] ?? c.gas).join(' / ')}。</p>

<ConfirmDialog open={pending !== null} busy={busy}
  title={pending === 'mfc' ? '下发流量设定' : pending === 'temperature' ? '下发温度设定' : '天平去皮'}
  message={pending === 'mfc' ? '将把表中的设定值写入全部 MFC 通道。' : pending === 'temperature' ? `将向温控仪写入 SV ${temperature} ℃。` : '去皮会把天平当前读数清零。请确认秤盘为空或只放置需要扣除的容器。'}
  confirmLabel="确认下发" onconfirm={confirm} oncancel={() => (pending = null)} />
