<script lang="ts">
  import { onMount } from 'svelte';
  import ConfirmDialog from '../../components/ConfirmDialog.svelte';
  import Metric from '../../components/Metric.svelte';
  import Badge from '../../components/Badge.svelte';
  import * as api from '../../lib/api/endpoints';
  import type { DeviceStatus } from '../../lib/api/types';
  import { notifier } from '../../lib/state/notify.svelte';
  import { errorMessage } from '../../lib/api/client';
  import { fmt } from '../../lib/format';

  let { online, runActive }: { online: boolean; runActive: boolean } = $props();

  let status = $state<DeviceStatus | null>(null);
  let error = $state('');
  let busy = $state(false);
  let setpoints: Record<number, number> = $state({});
  let temperature = $state(900);
  let pending = $state<'mfc' | 'temperature' | 'tare' | null>(null);
  let timer: ReturnType<typeof setTimeout> | undefined;

  async function refresh() {
    try {
      status = await api.deviceStatus();
      error = '';
      for (const channel of status.mfc ?? []) if (!(channel.address in setpoints)) setpoints[channel.address] = channel.setpoint_lpm;
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

  const description = $derived(status?.description);
  const canWrite = $derived(online && !runActive && !busy && status?.connected === true);
</script>

<div class="stack">
  <section class="panel">
    <div class="panel-head">
      <div class="row"><h2>设备状态</h2>
        {#if description}<Badge tone={description.simulation ? 'info' : 'ok'}>{description.simulation ? '仿真' : '实机'}</Badge><span class="muted small">{description.summary}</span>{/if}
        {#if status?.connected}<Badge tone="ok">已连接</Badge>{:else if status}<Badge tone="neutral">未连接</Badge>{/if}
      </div>
      <div class="row">
        <button class="btn sm" type="button" onclick={refresh} disabled={!online}>刷新</button>
        <button class="btn sm accent" type="button" onclick={connect} disabled={!online || busy || runActive}>连接设备</button>
      </div>
    </div>
    <div class="panel-body stack">
      {#if runActive}<div class="notice" data-tone="info">实验运行中，设备由实验流程控制。手动配气请在「运行监控」页切换到手动模式并二次确认。</div>{/if}
      {#if error}<div class="notice" data-tone="danger" role="alert"><div><div class="title">设备操作未完成</div><div>{error}</div></div><button class="close" type="button" aria-label="关闭" onclick={() => (error = '')}>×</button></div>{/if}
      {#if status && !status.supported}
        <div class="notice" data-tone="warn">当前设备通路（PLC Modbus）不提供按设备查看的状态页；实时数据见「运行监控」。</div>
      {:else if status}
        {#if status.degraded_devices?.length}<div class="notice" data-tone="warn" role="alert">通讯异常：{status.degraded_devices.join('、')}（显示上次有效值）</div>{/if}
        <div class="grid metrics">
          <Metric label="炉温 PV" value={fmt(status.temperature_c, 1)} unit="℃" tone="accent" />
          <Metric label="天平重量" value={fmt(status.weight_g, 3)} unit="g" />
          {#each status.mfc ?? [] as channel}
            <Metric label={`MFC ${channel.address} ${description?.mfc_channels.find((c) => c.address === channel.address)?.gas ?? ''}`} value={fmt(channel.flow_lpm, 3)} unit="L/min" />
          {/each}
        </div>
      {:else}<div class="empty"><strong>等待设备状态</strong>{online ? '正在读取…' : '本地服务未连接'}</div>{/if}
    </div>
  </section>

  {#if status?.supported}
    <div class="grid two">
      <section class="panel">
        <div class="panel-head"><h3>质量流量计设定（空闲手动控制）</h3><button class="btn warn sm" type="button" disabled={!canWrite} onclick={() => (pending = 'mfc')}>下发全部流量设定</button></div>
        <div class="panel-body">
          <div class="table-wrap" style="max-height:none"><table><thead><tr><th>地址</th><th>气体</th><th class="num">满量程</th><th class="num">实测 L/min</th><th>设定 L/min</th></tr></thead><tbody>
            {#each status.mfc ?? [] as channel}
              {@const meta = description?.mfc_channels.find((c) => c.address === channel.address)}
              <tr><td class="mono">{channel.address}</td><td>{meta?.gas ?? '--'}{meta?.role ? ` · 配方 ${meta.role}` : ''}</td><td class="num">{fmt(meta?.full_scale_lpm, 2)}</td><td class="num">{fmt(channel.flow_lpm, 3)}</td>
                <td><input type="number" min="0" max={meta?.full_scale_lpm ?? 50} step="0.01" bind:value={setpoints[channel.address]} disabled={!canWrite} aria-label={`MFC ${channel.address} 设定`} /></td></tr>
            {/each}
          </tbody></table></div>
        </div>
      </section>
      <div class="stack">
        <section class="panel">
          <div class="panel-head"><h3>温控仪</h3></div>
          <div class="panel-body row">
            <label class="field" style="max-width:200px"><span>目标 SV (℃)</span><input type="number" min="0" max="1600" step="0.1" bind:value={temperature} disabled={!canWrite} /></label>
            <button class="btn warn" type="button" disabled={!canWrite} onclick={() => (pending = 'temperature')}>下发温度设定</button>
            <span class="muted small">实验中温度由仪表程序执行，此处仅用于空闲时手动调试。</span>
          </div>
        </section>
        <section class="panel">
          <div class="panel-head"><h3>电子天平</h3></div>
          <div class="panel-body row">
            <span>重量 <strong>{fmt(status.weight_g, 3)} g</strong></span>
            <span class="spacer"></span>
            <button class="btn warn" type="button" disabled={!canWrite} onclick={() => (pending = 'tare')}>去皮</button>
          </div>
        </section>
        {#if description?.temperature_program}
          <section class="panel"><div class="panel-head"><h3>温度程序</h3></div>
            <div class="panel-body small muted">仪表程序组 {description.temperature_program.group}，段时间单位 {description.temperature_program.time_unit}，最多 {description.temperature_program.max_steps} 个配方步骤。仪表不支持远程启动，实验启动后需在面板上启动程序。</div></section>
        {/if}
      </div>
    </div>
  {/if}
</div>

<ConfirmDialog open={pending !== null} busy={busy}
  title={pending === 'mfc' ? '下发流量设定' : pending === 'temperature' ? '下发温度设定' : '天平去皮'}
  message={pending === 'mfc' ? '将把表中的设定值写入全部 MFC 通道。' : pending === 'temperature' ? `将向温控仪写入 SV ${temperature} ℃。` : '去皮会把天平当前读数清零。请确认秤盘为空或只放置需要扣除的容器。'}
  confirmLabel="确认下发" tone="warn" onconfirm={confirm} oncancel={() => (pending = null)} />
