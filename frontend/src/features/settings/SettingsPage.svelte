<script lang="ts">
  import { onMount } from 'svelte';
  import * as api from '../../lib/api/endpoints';
  import type { AppConfig, Health } from '../../lib/api/types';
  import { notifier } from '../../lib/state/notify.svelte';
  import { errorMessage } from '../../lib/api/client';
  import { downloadText } from '../../lib/format';

  let { online, health, runActive, onsaved }: { online: boolean; health: Health | null; runActive: boolean; onsaved: () => void } = $props();

  let config = $state<AppConfig | null>(null);
  let draft = $state<AppConfig | null>(null);
  let restartKeys: string[] = $state([]);
  let error = $state('');
  let saving = $state(false);
  let fileInput: HTMLInputElement | undefined = $state();

  async function load() {
    try {
      const response = await api.getSettings();
      config = response.config;
      draft = JSON.parse(JSON.stringify(response.config)) as AppConfig;
      restartKeys = response.restart_required_keys ?? [];
      error = '';
    } catch (e) { error = errorMessage(e); }
  }

  const changed = $derived.by(() => {
    if (!config || !draft) return [] as (keyof AppConfig)[];
    return (Object.keys(draft) as (keyof AppConfig)[]).filter((key) => JSON.stringify(draft![key]) !== JSON.stringify(config![key]));
  });
  const needsRestart = $derived(changed.some((key) => restartKeys.includes(key)));

  async function save() {
    if (!draft || saving || !changed.length) return;
    saving = true;
    try {
      const updates = Object.fromEntries(changed.map((key) => [key, draft![key]])) as Partial<AppConfig>;
      const response = await api.putSettings(updates);
      config = response.config;
      draft = JSON.parse(JSON.stringify(response.config)) as AppConfig;
      notifier.push('ok', '设置已保存', response.restart_required ? '部分设置需重启程序后生效' : undefined);
      onsaved();
    } catch (e) { error = errorMessage(e); } finally { saving = false; }
  }

  function exportConfig() { if (config) downloadText('rka3000-config.json', JSON.stringify({ format: 'rka3000-config', version: 1, ...config }, null, 2)); }

  async function importConfig(file: File) {
    try {
      const document = JSON.parse(await file.text()) as Record<string, unknown>;
      delete document.format; delete document.version;
      const response = await api.putSettings(document as Partial<AppConfig>);
      config = response.config; draft = JSON.parse(JSON.stringify(response.config)) as AppConfig;
      notifier.push('ok', '配置已导入', response.restart_required ? '需重启程序后生效' : undefined);
      onsaved();
    } catch (e) { error = errorMessage(e); }
  }

  function addChannel() { if (draft) draft.mfc_channels = [...draft.mfc_channels, { address: (draft.mfc_channels.at(-1)?.address ?? 0) + 1, gas: 'N2', full_scale_lpm: 5 }]; }
  function removeChannel(index: number) { if (draft) draft.mfc_channels = draft.mfc_channels.filter((_, i) => i !== index); }

  onMount(() => { void load(); });
  $effect(() => { if (online) void load(); });
</script>

<div class="stack">
  <section class="panel">
    <div class="panel-head"><h2>设置</h2>
      <div class="row">
        <button class="btn sm" type="button" onclick={() => fileInput?.click()} disabled={!online || runActive}>导入配置</button>
        <button class="btn sm" type="button" onclick={exportConfig} disabled={!config}>导出配置</button>
        <input class="sr-only" type="file" accept=".json,application/json" bind:this={fileInput} onchange={(e) => { const f = e.currentTarget.files?.[0]; if (f) void importConfig(f); e.currentTarget.value = ''; }} />
        <button class="btn sm" type="button" onclick={load} disabled={!online}>重新加载</button>
        <button class="btn primary" type="button" onclick={save} disabled={!online || saving || !changed.length || (runActive && needsRestart)}>{#if saving}<span class="spinner" aria-hidden="true"></span>{/if}保存设置</button>
      </div>
    </div>
    <div class="panel-body stack">
      {#if error}<div class="notice" data-tone="danger" role="alert"><div><div class="title">设置未保存</div><div>{error}</div></div><button class="close" type="button" aria-label="关闭" onclick={() => (error = '')}>×</button></div>{/if}
      {#if runActive}<div class="notice" data-tone="info">实验运行中不能修改设备、存储和采集相关设置。</div>{/if}
      {#if needsRestart}<div class="notice" data-tone="warn">已修改的 {changed.filter((k) => restartKeys.includes(k)).join('、')} 需要重启程序后生效。</div>{/if}
      {#if draft}
        <h3>运行模式</h3>
        <div class="form-grid">
          <label class="field"><span>仿真模式</span><select bind:value={draft.simulation_mode}><option value={true}>是（无硬件）</option><option value={false}>否（连接实机）</option></select><span class="hint">实机模式需填写下方串口。</span></label>
          <label class="field"><span>设备通路</span><select bind:value={draft.device_backend}><option value="multi_device">温控仪 + MFC + 天平</option><option value="plc_modbus">PLC Modbus（contract_v1）</option></select></label>
          <label class="field"><span>温度控制模式</span><select bind:value={draft.temperature_mode}><option value="program">仪表程序（启动时下发，过程不调整）</option><option value="setpoint">逐步下发设定值</option></select></label>
          <label class="field"><span>默认配气模式</span><select bind:value={draft.default_gas_mode}><option value="auto">自动（按配方）</option><option value="manual">手动</option></select></label>
          <label class="field"><span>采样周期 (ms)</span><input type="number" min="100" max="60000" bind:value={draft.poll_interval_ms} /></label>
          <label class="field"><span>批量落库条数</span><input type="number" min="1" max="1000" bind:value={draft.acquisition_batch_size} /></label>
          <label class="field"><span>升温超时宽限 (s)</span><input type="number" min="0" bind:value={draft.step_heatup_grace_seconds} /></label>
          <label class="field"><span>步骤总超时宽限 (s)</span><input type="number" min="0" bind:value={draft.step_total_grace_seconds} /></label>
          <label class="field"><span>设备无响应故障阈值 (s)</span><input type="number" min="5" max="3600" bind:value={draft.degraded_fault_seconds} /></label>
        </div>
        {#if draft.device_backend === 'multi_device'}
          <h3>温控仪（TAIE · Modbus RTU）</h3>
          <div class="form-grid">
            <label class="field"><span>串口</span><input bind:value={draft.temp_port} placeholder="COM3" /></label>
            <label class="field"><span>从站地址</span><input type="number" min="1" max="247" bind:value={draft.temp_slave_id} /></label>
            <label class="field"><span>波特率</span><input type="number" bind:value={draft.temp_baudrate} /></label>
            <label class="field"><span>程序组</span><input type="number" min="0" max="2" bind:value={draft.temp_program_group} /></label>
            <label class="field"><span>段时间单位</span><select bind:value={draft.temp_segment_time_unit}><option value="min">分钟</option><option value="s">秒</option></select><span class="hint">需与仪表设置一致，请在现场确认。</span></label>
          </div>
          <h3>质量流量计总线（Azbil CPL · RS-485）</h3>
          <div class="form-grid">
            <label class="field"><span>串口</span><input bind:value={draft.mfc_port} placeholder="COM4" /></label>
            <label class="field"><span>波特率</span><input type="number" bind:value={draft.mfc_baudrate} /></label>
          </div>
          <div class="table-wrap" style="max-height:none"><table><thead><tr><th>地址</th><th>气体</th><th>满量程 L/min</th><th></th></tr></thead><tbody>
            {#each draft.mfc_channels as channel, i}
              <tr><td><input type="number" min="1" max="127" bind:value={channel.address} aria-label="地址" /></td><td><input bind:value={channel.gas} aria-label="气体" /></td><td><input type="number" min="0.01" step="0.01" bind:value={channel.full_scale_lpm} aria-label="满量程" /></td><td><button class="btn sm" type="button" onclick={() => removeChannel(i)} disabled={draft.mfc_channels.length === 1} aria-label="删除通道">×</button></td></tr>
            {/each}
          </tbody></table></div>
          <div class="row"><button class="btn sm" type="button" onclick={addChannel}>新增通道</button><span class="muted small">配方中的 N2 / H2 / CO 设定下发到气体名为 N2、H2、CO 的第一个通道。</span></div>
          <h3>电子天平</h3>
          <div class="form-grid">
            <label class="field"><span>串口</span><input bind:value={draft.balance_port} placeholder="COM5" /></label>
            <label class="field"><span>协议</span><select bind:value={draft.balance_protocol}><option value="gs_cpa">GS-CPA</option><option value="longteng">龙腾</option></select></label>
            <label class="field"><span>波特率</span><input type="number" bind:value={draft.balance_baudrate} /></label>
          </div>
        {:else}
          <h3>PLC（Modbus RTU）</h3>
          <div class="form-grid">
            <label class="field"><span>串口</span><input bind:value={draft.plc_serial_port} placeholder="COM3" /></label>
            <label class="field"><span>波特率</span><input type="number" bind:value={draft.plc_baudrate} /></label>
            <label class="field"><span>从站地址</span><input type="number" min="1" max="247" bind:value={draft.plc_unit_id} /></label>
            <label class="field"><span>寄存器映射</span><input bind:value={draft.mapping_profile} /></label>
          </div>
        {/if}
        <h3>存储与日志</h3>
        <div class="form-grid">
          <label class="field"><span>数据库路径</span><input bind:value={draft.db_path} placeholder="留空使用默认位置" /><span class="hint">默认：{health?.database ?? '--'}</span></label>
          <label class="field"><span>审计记录保留条数</span><input type="number" min="100" bind:value={draft.audit_log_limit} /></label>
          <label class="field"><span>日志单文件上限 (字节)</span><input type="number" min="100000" bind:value={draft.log_max_bytes} /></label>
          <label class="field"><span>日志备份数</span><input type="number" min="0" max="20" bind:value={draft.log_backup_count} /></label>
        </div>
      {:else}<div class="empty">{online ? '正在加载设置…' : '本地服务未连接'}</div>{/if}
    </div>
  </section>
  <section class="panel">
    <div class="panel-head"><h3>诊断信息</h3></div>
    <div class="panel-body">
      <dl class="kv">
        <dt>后端版本 / 接口版本</dt><dd>{health?.version ?? '--'} / {health?.api_version ?? '--'}</dd>
        <dt>数据目录</dt><dd class="mono">{health?.data_dir ?? '--'}</dd>
        <dt>数据库</dt><dd class="mono">{health?.database ?? '--'}</dd>
        <dt>导出目录</dt><dd class="mono">{health?.export_dir ?? '--'}</dd>
        <dt>后端日志</dt><dd class="mono">{health?.log_path ?? '--'}</dd>
        {#if health?.notes.length}<dt>启动说明</dt><dd>{#each health.notes as note}<div>{note}</div>{/each}</dd>{/if}
      </dl>
    </div>
  </section>
</div>
