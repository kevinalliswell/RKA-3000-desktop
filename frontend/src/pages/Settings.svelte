<script lang="ts">
  import { onMount } from 'svelte'
  import { open } from '@tauri-apps/plugin-dialog'
  import { ws, gases, gasLabels, gasChannels, type Gas, type Settings } from '../lib/sim.svelte'
  let tab = $state(0)
  let limits = $state<Record<Gas,number> | null>(null)
  let role = $state('operator')
  let scenario = $state('normal')
  let importResult = $state<Record<string,unknown> | null>(null)
  const max: Record<Gas,number> = { n2:20, ar:20, co:10, co2:20, h2:10, ch4:10, o2:20 }
  onMount(() => {
    void ws.request<Settings>('sim_settings').then(settings => {
      limits = structuredClone(settings.limits)
      role = settings.role
      scenario = settings.scenario
    }).catch(() => {})
  })
  async function saveSettings() { try { await ws.request('sim_settings_update', { limits, role, scenario }); ws.notice = '仿真设置已保存'; await ws.load() } catch { /* shown */ } }
  async function importLegacy() {
    try {
      const path = await open({ multiple: false, filters: [{ name: 'SQLite 数据库', extensions: ['db','sqlite','sqlite3'] }] })
      if (!path || typeof path !== 'string') return
      const result = await ws.request<Record<string,unknown>>('sim_import_legacy', { path })
      importResult = result
      ws.notice = result.already_imported ? '该文件已导入，无重复记录' : '旧数据库已备份并复制导入'
      await ws.load()
    } catch { /* shown */ }
  }
</script>
<p class="lead">界面偏好、仿真角色与气体上限。现场串口参数由独立配置文件管理，本版不连接或写入真实设备。</p>
<div class="tabs">{#each ['界面与仿真','现场通信','安全边界','旧数据导入'] as label,i}<button class:active={tab === i} onclick={() => tab = i}>{label}</button>{/each}</div>
{#if tab === 0}<section class="panel"><div class="panel-header"><h2>仿真配置</h2></div><div class="panel-body"><div class="form-grid"><label>仿真角色<select bind:value={role}><option value="operator">操作员</option><option value="reviewer">复核员</option><option value="administrator">管理员</option></select></label><label>测试场景<select bind:value={scenario}><option value="normal">正常</option><option value="offline">设备离线</option><option value="stale">采样过期</option><option value="alarm">报警暂停</option><option value="unstable">天平不稳定</option></select></label></div><h3 class="section-title">气体使用上限 · L/min</h3><p class="muted">仅仿真管理员可修改；有实验未归档时锁定。不得超过设备标称上限。角色切换只用于仿真演示。</p>{#if limits}<div class="gas-grid">{#each gases as gas}<label>{gasLabels[gas]} · {gasChannels[gas]}<input type="number" min="0.1" max={max[gas]} step="0.1" disabled={role !== 'administrator' || !!ws.run} bind:value={limits[gas]}/><small>设备上限 {max[gas]}</small></label>{/each}</div>{/if}<div class="action-row"><button class="button primary" disabled={!limits} onclick={saveSettings}>保存设置</button></div></div></section>{/if}
{#if tab === 1}<section class="panel"><div class="panel-header"><h2>现场通信</h2><span class="badge warn">未启用</span></div><div class="panel-body"><p>真实设备需要独立配置 TAIE Modbus RTU、Azbil CPL 与天平串口参数，并核对地址、气体、量程及联锁。当前桌面新版没有现场连接入口。</p><p>设备页预留首次扫描和约 30 秒后台复查的状态接口；没有现场配置时真实设备显示未知。</p></div></section>{/if}
{#if tab === 2}<section class="panel"><div class="panel-header"><h2>安全边界</h2></div><div class="panel-body check-list"><div>还原实验禁用 O₂；氧化实验禁用 CO、H₂、CH₄。</div><div>N₂ 与 Ar 共用 MFC-01，单次实验只能选择其中一种。</div><div>暂停、故障和紧急处置关闭仿真反应气；紧急处置不可直接恢复。</div><div>应用重启后未完成实验进入待复核，不自动续行。</div><div>真实设备写入在桌面新版中始终禁用。</div></div></section>{/if}
{#if tab === 3}<section class="panel"><div class="panel-header"><h2>旧 SQLite 数据导入</h2></div><div class="panel-body"><p>先关闭原 PySide6 程序，再选择旧数据库文件。程序校验旧表并备份当前工作库，随后复制记录；旧文件保持不变。相同文件重复导入不会重复写入。</p><button class="button primary" onclick={importLegacy}>选择旧数据库并导入</button>{#if importResult}<div class="callout"><span>{importResult.already_imported ? '已导入过' : '导入完成'} · 配方 {importResult.recipe_count as number} 条 · 实验 {importResult.run_count as number} 条<br/>工作库备份：{importResult.backup_path as string}</span></div>{/if}</div></section>{/if}
