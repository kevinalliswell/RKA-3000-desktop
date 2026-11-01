<script lang="ts">
  import { onMount } from 'svelte';
  import Badge from '../../components/Badge.svelte';
  import Seg from '../../components/Seg.svelte';
  import ConfirmDialog from '../../components/ConfirmDialog.svelte';
  import * as api from '../../lib/api/endpoints';
  import type { AppConfig, Flows, GasKey, Health, LimitsPreview, LimitsState, Task } from '../../lib/api/types';
  import { notifier } from '../../lib/state/notify.svelte';
  import { prefs, THEMES, type Theme } from '../../lib/state/prefs.svelte';
  import { nav } from '../../lib/state/nav.svelte';
  import { errorMessage } from '../../lib/api/client';
  import { downloadText, fmtFlow, fmtShort, GAS_LABEL, taskStatusLabel } from '../../lib/format';

  let { online, health, runActive, onsaved }: { online: boolean; health: Health | null; runActive: boolean; onsaved: () => void } = $props();

  let tab = $state<'limits' | 'system' | 'appearance' | 'diagnostics'>('limits');

  // ------------------------------------------------------------ gas usage limits
  let limits = $state<LimitsState | null>(null);
  let proposed = $state<Record<string, string>>({});
  let reason = $state('');
  let preview = $state<LimitsPreview | null>(null);
  let confirmApply = $state(false);
  let applying = $state(false);
  let limitsError = $state('');

  async function loadLimits() {
    try {
      limits = await api.getLimits();
      proposed = Object.fromEntries(limits.gases.filter((g) => g.available).map((g) => [g.gas, fmtFlow(g.usage_limit)]));
      preview = null;
      limitsError = '';
    } catch (e) { limitsError = errorMessage(e); }
  }

  const changes = $derived.by((): Flows => {
    const out: Flows = {};
    for (const gas of limits?.gases ?? []) {
      if (!gas.available) continue;
      const value = Number(proposed[gas.gas]);
      if (proposed[gas.gas] !== undefined && Number.isFinite(value) && Math.abs(value - (gas.usage_limit ?? 0)) > 1e-9) out[gas.gas] = value;
    }
    return out;
  });
  const invalid = $derived((limits?.gases ?? []).filter((g) => g.available).find((g) => {
    const v = Number(proposed[g.gas]);
    return !Number.isFinite(v) || v <= 0 || v > (g.device_limit ?? 0);
  }));
  const hasChanges = $derived(Object.keys(changes).length > 0);

  async function doPreview() {
    try { preview = await api.previewLimits(changes); limitsError = ''; } catch (e) { limitsError = errorMessage(e); }
  }

  async function apply() {
    applying = true;
    try {
      const result = await api.applyLimits(changes, reason, prefs.operator || undefined);
      notifier.push('ok', `使用上限策略 v${result.policy.version} 已生效`, result.applied?.affected.length ? `${result.applied.affected.length} 个配方现已不可执行` : '没有配方受影响');
      reason = '';
      await loadLimits();
    } catch (e) { limitsError = errorMessage(e); } finally { applying = false; confirmApply = false; }
  }

  // ------------------------------------------------------------ system configuration
  let config = $state<AppConfig | null>(null);
  let draft = $state<AppConfig | null>(null);
  let restartKeys: string[] = $state([]);
  let error = $state('');
  let saving = $state(false);
  let fileInput: HTMLInputElement | undefined = $state();

  async function loadConfig() {
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

  // ------------------------------------------------------------ diagnostics
  let backendLog = $state('');
  let backendPath = $state('');
  let tasks = $state<Task[]>([]);
  async function loadDiagnostics() {
    try {
      const log = await api.backendLog();
      backendLog = log.content;
      backendPath = log.path;
      tasks = await api.listTasks(30);
    } catch (e) { error = errorMessage(e); }
  }

  let operatorDraft = $state('');
  onMount(() => { operatorDraft = prefs.operator; });
  $effect(() => {
    if (!online) return;
    if (tab === 'limits') void loadLimits();
    else if (tab === 'system') void loadConfig();
    else if (tab === 'diagnostics') void loadDiagnostics();
  });
</script>

<div class="page-head">
  <div>
    <h1>系统设置</h1>
    <p>核心是气体使用上限：设备上限是硬件能力（MFC 满量程），使用上限是本机运行限制。实验未归档时锁定，变更前必须预览影响并填写原因。</p>
  </div>
  {#if limits}
    <div class="actions"><Badge tone="dark">策略 v{limits.policy.version}</Badge><Badge tone={limits.locked ? 'warn' : 'good'}>{limits.locked ? '已锁定' : '待机 · 可配置'}</Badge></div>
  {/if}
</div>

<div class="tabs" role="tablist">
  <button type="button" role="tab" aria-selected={tab === 'limits'} onclick={() => (tab = 'limits')}>气体使用上限</button>
  <button type="button" role="tab" aria-selected={tab === 'system'} onclick={() => (tab = 'system')}>采集与设备</button>
  <button type="button" role="tab" aria-selected={tab === 'appearance'} onclick={() => (tab = 'appearance')}>外观与操作者</button>
  <button type="button" role="tab" aria-selected={tab === 'diagnostics'} onclick={() => (tab = 'diagnostics')}>诊断与日志</button>
</div>

{#if tab === 'limits'}
  {#if limitsError}<div class="callout danger">{limitsError}</div>{/if}
  {#if limits?.locked}<div class="callout warn"><strong>{limits.locked}</strong> 运行中实验的快照内上限不变。</div>{/if}
  <div class="grid main-side">
    <section class="card flush">
      <div class="card-head"><h2>气体使用上限</h2><span class="tiny soft">单位 L/min · 最多两位小数</span></div>
      <div class="table-wrap">
        <table class="data">
          <thead><tr><th>气体 / 危险属性</th><th class="num">设备上限</th><th class="num">当前生效</th><th>拟设使用上限</th></tr></thead>
          <tbody>
            {#each limits?.gases ?? [] as gas}
              <tr>
                <td><strong>{gas.label}</strong>{#if gas.hazard}<span class="tiny soft"> · {gas.hazard}</span>{/if}{#if !gas.available}<div class="tiny soft">未配置 MFC 通道</div>{/if}</td>
                <td class="num mono">{fmtFlow(gas.device_limit)}</td>
                <td class="num mono">{fmtFlow(gas.usage_limit)}</td>
                <td>{#if gas.available}
                  <input aria-label={`${gas.label} 使用上限`} inputmode="decimal" value={proposed[gas.gas] ?? ''} disabled={Boolean(limits?.locked)}
                    aria-invalid={!(Number(proposed[gas.gas]) > 0 && Number(proposed[gas.gas]) <= (gas.device_limit ?? 0))}
                    oninput={(e) => { proposed = { ...proposed, [gas.gas]: e.currentTarget.value }; preview = null; }} />
                {:else}<span class="soft">—</span>{/if}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
      <div style="padding:12px 16px 16px" class="stack tight">
        {#if invalid}<div class="callout danger">{invalid.label} 使用上限须大于 0 且不超过设备上限 {fmtFlow(invalid.device_limit)}。</div>{/if}
        <label class="field"><span>变更原因（必填，写入审计）</span>
          <input bind:value={reason} placeholder="例如 可燃气安全评审结论" disabled={Boolean(limits?.locked)} maxlength="200" /></label>
        <div class="row">
          <button class="btn" type="button" disabled={!online || !hasChanges || Boolean(invalid)} onclick={doPreview}>预览变更影响</button>
          <button class="btn primary" type="button" disabled={!online || !preview || Boolean(limits?.locked) || reason.trim().length < 2 || Boolean(invalid)}
            onclick={() => (confirmApply = true)}>确认应用 · 生成策略 v{(limits?.policy.version ?? 0) + 1}</button>
          {#if hasChanges}<button class="btn" type="button" onclick={loadLimits}>取消修改</button>{/if}
        </div>
        {#if preview}
          <div class={`callout ${preview.affected.length ? 'warn' : 'good'}`}>
            拟设 {preview.changes.map((c) => `${c.label} ${fmtFlow(c.before)} → ${fmtFlow(c.after)}`).join('；')}。
            {#if preview.affected.length}应用后 {preview.affected.length} 个可执行配方超出新限制，将被阻止启动：{preview.affected.map((a) => `${a.name} v${a.version}`).join('、')}。{:else}没有可执行配方受影响。{/if}
            确认后生成策略 v{preview.next_version} 并写入审计。
          </div>
        {/if}
      </div>
    </section>
    <div class="stack">
      <section class="card">
        <h2 style="margin-bottom:8px">规则</h2>
        <dl class="kv">
          <dt>何时能改</dt><dd>无运行中或待核查实验</dd>
          <dt>范围</dt><dd>0 &lt; 值 ≤ 设备上限</dd>
          <dt>生效影响</dt><dd>配方可执行性、启动预检、手动调气</dd>
          <dt>记录</dt><dd>版本号 +1，原因与受影响配方写入审计</dd>
          <dt>运行中</dt><dd>当前实验快照内的上限不变</dd>
          <dt>权限</dt><dd>本机未启用账号，修改人取“当前操作者”</dd>
        </dl>
      </section>
      <section class="card">
        <h2 style="margin-bottom:8px">策略历史</h2>
        {#each limits?.history ?? [] as item}
          <div class="ev"><time>v{item.version}</time><strong>{item.reason}</strong><span>{item.actor || '—'} · {fmtShort(item.created_at)}</span></div>
        {/each}
      </section>
    </div>
  </div>
{:else if tab === 'system'}
  <section class="card">
    <div class="card-head"><h2>采集与设备</h2>
      <div class="row">
        <button class="btn sm" type="button" onclick={() => fileInput?.click()} disabled={!online || runActive}>导入配置</button>
        <button class="btn sm" type="button" onclick={exportConfig} disabled={!config}>导出配置</button>
        <input class="sr-only" type="file" accept=".json,application/json" bind:this={fileInput} onchange={(e) => { const f = e.currentTarget.files?.[0]; if (f) void importConfig(f); e.currentTarget.value = ''; }} />
        <button class="btn primary sm" type="button" onclick={save} disabled={!online || saving || !changed.length || (runActive && needsRestart)}>{#if saving}<span class="spinner" aria-hidden="true"></span>{/if}保存设置</button>
      </div>
    </div>
    <div class="stack">
      {#if error}<div class="callout danger" role="alert"><strong>设置未保存。</strong> {error}</div>{/if}
      {#if runActive}<div class="callout">实验运行中不能修改设备、存储和采集相关设置。</div>{/if}
      {#if needsRestart}<div class="callout warn">已修改的 {changed.filter((k) => restartKeys.includes(k)).join('、')} 需要重启程序后生效。</div>{/if}
      {#if draft}
        <h3>运行模式</h3>
        <div class="form-grid three">
          <label class="field"><span>仿真模式</span><select bind:value={draft.simulation_mode}><option value={true}>是（无硬件）</option><option value={false}>否（连接实机）</option></select><span class="hint">实机模式需填写下方串口。</span></label>
          <label class="field"><span>设备通路</span><select bind:value={draft.device_backend}><option value="multi_device">温控仪 + MFC + 天平</option><option value="plc_modbus">PLC Modbus（contract_v1）</option></select></label>
          <label class="field"><span>温度控制方式</span><select bind:value={draft.temperature_mode}><option value="program">仪表程序（启动时一次下发，过程中不调节）</option><option value="setpoint">逐段下发设定值</option></select></label>
          <label class="field"><span>默认配气模式</span><select bind:value={draft.default_gas_mode}><option value="auto">按配方</option><option value="manual">手动</option></select></label>
          <label class="field"><span>采样周期 (ms)</span><input type="number" min="100" max="60000" bind:value={draft.poll_interval_ms} /></label>
          <label class="field"><span>批量落库条数</span><input type="number" min="1" max="1000" bind:value={draft.acquisition_batch_size} /></label>
          <label class="field"><span>升温超时宽限 (s)</span><input type="number" min="0" bind:value={draft.step_heatup_grace_seconds} /></label>
          <label class="field"><span>步骤总超时宽限 (s)</span><input type="number" min="0" bind:value={draft.step_total_grace_seconds} /></label>
          <label class="field"><span>回读过期报警延时 (s)</span><input type="number" min="5" max="3600" bind:value={draft.degraded_fault_seconds} /><span class="hint">持续过期超过该时长记录警告；不自动停机。</span></label>
          <label class="field"><span>处置结束炉温 (℃)</span><input type="number" min="50" max="600" bind:value={draft.purge_exit_temperature_c} /><span class="hint">吹扫满时长且炉温低于此值才进入待核查。</span></label>
        </div>
        {#if draft.device_backend === 'multi_device'}
          <h3>温控仪（TAIE · Modbus RTU）</h3>
          <div class="form-grid three">
            <label class="field"><span>串口</span><input bind:value={draft.temp_port} placeholder="COM3" /></label>
            <label class="field"><span>从站地址</span><input type="number" min="1" max="247" bind:value={draft.temp_slave_id} /></label>
            <label class="field"><span>波特率</span><input type="number" bind:value={draft.temp_baudrate} /></label>
            <label class="field"><span>程序组</span><input type="number" min="0" max="2" bind:value={draft.temp_program_group} /></label>
            <label class="field"><span>段时间单位</span><select bind:value={draft.temp_segment_time_unit}><option value="min">分钟</option><option value="s">秒</option></select><span class="hint">需与仪表设置一致，请在现场确认。</span></label>
          </div>
          <h3>质量流量计总线（Azbil CPL · RS-485）</h3>
          <div class="form-grid three">
            <label class="field"><span>串口</span><input bind:value={draft.mfc_port} placeholder="COM4" /></label>
            <label class="field"><span>波特率</span><input type="number" bind:value={draft.mfc_baudrate} /></label>
          </div>
          <div class="table-wrap"><table class="data"><thead><tr><th>地址</th><th>气体（N2 / AR / H2 / CO / CO2 / CH4 / O2）</th><th>满量程 L/min（= 设备上限）</th><th></th></tr></thead><tbody>
            {#each draft.mfc_channels as channel, i}
              <tr><td><input type="number" min="1" max="127" bind:value={channel.address} aria-label="地址" /></td><td><input bind:value={channel.gas} aria-label="气体" /></td><td><input type="number" min="0.01" step="0.01" bind:value={channel.full_scale_lpm} aria-label="满量程" /></td><td><button class="btn sm" type="button" onclick={() => removeChannel(i)} disabled={draft.mfc_channels.length === 1} aria-label="删除通道">×</button></td></tr>
            {/each}
          </tbody></table></div>
          <div class="row"><button class="btn sm" type="button" onclick={addChannel}>新增通道</button><span class="soft small">每种气体使用名称匹配的第一个通道；没有通道的气体在配方与调气中不可用。</span></div>
          <h3>电子天平</h3>
          <div class="form-grid three">
            <label class="field"><span>串口</span><input bind:value={draft.balance_port} placeholder="COM5" /></label>
            <label class="field"><span>协议</span><select bind:value={draft.balance_protocol}><option value="gs_cpa">GS-CPA</option><option value="longteng">龙腾</option></select></label>
            <label class="field"><span>波特率</span><input type="number" bind:value={draft.balance_baudrate} /></label>
          </div>
        {:else}
          <h3>PLC（Modbus RTU）</h3>
          <div class="form-grid three">
            <label class="field"><span>串口</span><input bind:value={draft.plc_serial_port} placeholder="COM3" /></label>
            <label class="field"><span>波特率</span><input type="number" bind:value={draft.plc_baudrate} /></label>
            <label class="field"><span>从站地址</span><input type="number" min="1" max="247" bind:value={draft.plc_unit_id} /></label>
            <label class="field"><span>寄存器映射</span><input bind:value={draft.mapping_profile} /></label>
          </div>
        {/if}
        <h3>存储与日志</h3>
        <div class="form-grid three">
          <label class="field"><span>数据库路径</span><input bind:value={draft.db_path} placeholder="留空使用默认位置" /><span class="hint">默认：{health?.database ?? '—'}</span></label>
          <label class="field"><span>非实验审计保留条数</span><input type="number" min="100" bind:value={draft.audit_log_limit} /><span class="hint">属于实验的记录随实验保存，不删除。</span></label>
          <label class="field"><span>日志单文件上限 (字节)</span><input type="number" min="100000" bind:value={draft.log_max_bytes} /></label>
          <label class="field"><span>日志备份数</span><input type="number" min="0" max="20" bind:value={draft.log_backup_count} /></label>
        </div>
      {:else}<div class="empty">{online ? '正在加载设置…' : '本地服务未连接'}</div>{/if}
    </div>
  </section>
{:else if tab === 'appearance'}
  <div class="grid halves">
    <section class="card">
      <h2 style="margin-bottom:12px">主题</h2>
      <Seg label="主题" value={prefs.theme} onselect={(id) => prefs.setTheme(id as Theme)} options={THEMES.map((t) => ({ id: t.id, label: t.label }))} />
      <p class="tiny soft" style="margin-top:10px">默认跟随系统的浅色 / 深色；也可固定为浅色、深色或科技蓝。顶栏按钮在三种主题间循环。只保存在本机。</p>
    </section>
    <section class="card">
      <h2 style="margin-bottom:12px">当前操作者</h2>
      <div class="row">
        <label class="field fill"><span>姓名（写入操作审计）</span><input bind:value={operatorDraft} maxlength="40" placeholder="例如 实验员 A" /></label>
        <button class="btn" type="button" style="align-self:end" onclick={() => { prefs.setOperator(operatorDraft); notifier.push('ok', '已保存当前操作者'); }}>保存</button>
      </div>
      <p class="tiny soft" style="margin-top:10px">本机未启用账号与密码；操作者姓名由使用者自行填写，用于审计记录与实验准备的默认值。</p>
    </section>
  </div>
{:else}
  <div class="grid halves">
    <section class="card">
      <h2 style="margin-bottom:8px">诊断信息</h2>
      <dl class="kv">
        <dt>后端版本 / 接口版本</dt><dd>{health?.version ?? '—'} / {health?.api_version ?? '—'}</dd>
        <dt>数据目录</dt><dd class="mono">{health?.data_dir ?? '—'}</dd>
        <dt>数据库</dt><dd class="mono">{health?.database ?? '—'}</dd>
        <dt>导出目录</dt><dd class="mono">{health?.export_dir ?? '—'}</dd>
        <dt>后端日志</dt><dd class="mono">{health?.log_path ?? '—'}</dd>
        {#if health?.notes.length}<dt>启动说明</dt><dd>{#each health.notes as note}<div>{note}</div>{/each}</dd>{/if}
      </dl>
    </section>
    <section class="card flush">
      <div class="card-head"><h2>后台任务</h2><button class="btn sm" type="button" onclick={loadDiagnostics}>刷新</button></div>
      <div class="table-wrap"><table class="data"><thead><tr><th>创建</th><th>类型</th><th>状态</th><th>结果 / 错误</th></tr></thead><tbody>
        {#each tasks as task}<tr><td class="mono">{fmtShort(task.created_at)}</td><td>{task.kind}</td><td><Badge tone={task.status === 'completed' ? 'good' : task.status === 'failed' ? 'danger' : ''}>{taskStatusLabel[task.status]}</Badge></td><td class="small mono">{task.error ?? task.result?.filename ?? ''}</td></tr>
        {:else}<tr><td colspan="4"><div class="empty">暂无后台任务</div></td></tr>{/each}
      </tbody></table></div>
    </section>
  </div>
  <section class="card">
    <div class="card-head"><h2>后端日志</h2>
      <div class="row"><span class="tiny soft mono">{backendPath}</span>
        <button class="btn sm" type="button" onclick={() => downloadText('backend.log', backendLog, 'text/plain')} disabled={!backendLog}>下载日志</button></div></div>
    <pre class="log">{backendLog || '（空）'}</pre>
  </section>
{/if}

<ConfirmDialog open={confirmApply} busy={applying} title={`生成使用上限策略 v${(limits?.policy.version ?? 0) + 1}？`} confirmLabel="确认应用"
  message={`${Object.entries(changes).map(([gas, value]) => `${GAS_LABEL[gas as GasKey]} → ${fmtFlow(value)}`).join('；')}。原因：${reason}`}
  detail={preview?.affected.length ? `受影响配方：${preview.affected.map((a) => a.name).join('、')}，应用后在实验准备中不可选。` : '没有可执行配方受影响。'}
  onconfirm={apply} oncancel={() => (confirmApply = false)} />
