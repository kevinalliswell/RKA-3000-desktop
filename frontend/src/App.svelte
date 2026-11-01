<script lang="ts">
  import { onMount } from 'svelte';
  import Toasts from './components/Toasts.svelte';
  import Badge from './components/Badge.svelte';
  import { Connection } from './lib/state/connection.svelte';
  import { RunSession } from './lib/state/run.svelte';
  import { runStatusLabel, runStatusTone } from './lib/format';
  import RunPage from './features/run/RunPage.svelte';
  import RecipesPage from './features/recipes/RecipesPage.svelte';
  import DevicesPage from './features/devices/DevicesPage.svelte';
  import AnalysisPage from './features/analysis/AnalysisPage.svelte';
  import HistoryPage from './features/history/HistoryPage.svelte';
  import LogsPage from './features/logs/LogsPage.svelte';
  import SettingsPage from './features/settings/SettingsPage.svelte';

  type Page = 'run' | 'recipes' | 'devices' | 'analysis' | 'history' | 'logs' | 'settings';
  const pages: { id: Page; label: string }[] = [
    { id: 'run', label: '运行监控' }, { id: 'recipes', label: '配方' }, { id: 'devices', label: '设备' },
    { id: 'analysis', label: '数据分析' }, { id: 'history', label: '历史' }, { id: 'logs', label: '报警与日志' },
    { id: 'settings', label: '设置' },
  ];

  const connection = new Connection();
  const run = new RunSession();
  let page: Page = $state('run');
  let theme: 'light' | 'dark' | 'system' = $state('system');

  function applyTheme(value: typeof theme) {
    theme = value;
    if (value === 'system') delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = value;
    try { localStorage.setItem('rka3000-theme', value); } catch { /* ignore */ }
  }

  onMount(() => {
    try {
      const saved = localStorage.getItem('rka3000-theme') as typeof theme | null;
      if (saved === 'light' || saved === 'dark') applyTheme(saved);
    } catch { /* ignore */ }
    void connection.start();
    run.start();
    return () => { connection.dispose(); run.dispose(); };
  });

  const pendingAlarms = $derived(run.state?.pending_alarms.length ?? 0);
  const connectionLabel = $derived(
    connection.phase === 'online' ? (connection.health?.simulation_mode ? '本地服务在线 · 仿真' : '本地服务在线 · 实机')
    : connection.phase === 'connecting' ? '正在连接本地服务…'
    : connection.phase === 'retrying' ? `重连中 (${connection.attempts}/${connection.maxAttempts})`
    : connection.phase === 'exited' ? '业务服务已退出' : '本地服务不可用');
  const connectionTone = $derived(connection.phase === 'online' ? 'ok' : connection.phase === 'connecting' || connection.phase === 'retrying' ? 'busy' : 'danger');
</script>

<svelte:head><title>RKA-3000 实验系统</title></svelte:head>

<div class="shell">
  <header class="topbar">
    <div class="brand">
      <img src="/icon.png" alt="" />
      <div>
        <div class="eyebrow">USTB · RKA-3000</div>
        <h1>铁矿石氧化/还原动力学实验系统</h1>
      </div>
    </div>
    <div class="topbar-right">
      {#if run.state && run.state.status !== 'idle'}
        <Badge tone={runStatusTone[run.state.status]}>实验 {runStatusLabel[run.state.status]}</Badge>
      {/if}
      <Badge tone={connectionTone}>{connectionLabel}</Badge>
      <label class="small" style="display:flex;gap:6px;align-items:center;opacity:.85">主题
        <select class="input" style="min-height:30px;padding:2px 6px;width:auto" value={theme} onchange={(e) => applyTheme(e.currentTarget.value as typeof theme)}>
          <option value="system">跟随系统</option><option value="light">浅色</option><option value="dark">深色</option>
        </select>
      </label>
      <span class="small" style="opacity:.75">v{connection.health?.version ?? '…'}</span>
    </div>
  </header>

  <nav class="nav" aria-label="功能页">
    {#each pages as item}
      <button type="button" aria-current={page === item.id ? 'page' : undefined} onclick={() => (page = item.id)}>
        {item.label}{#if item.id === 'logs' && pendingAlarms}<span class="badge" data-tone="danger">{pendingAlarms}</span>{/if}
      </button>
    {/each}
  </nav>

  <main class="content">
    {#if connection.phase !== 'online'}
      <div class="notice" data-tone={connection.phase === 'exited' || connection.phase === 'offline' ? 'danger' : 'info'} role="alert" style="margin-bottom:16px">
        <div>
          <div class="title">{connectionLabel}</div>
          {#if connection.phase === 'offline' || connection.phase === 'exited'}
            <div>{connection.error || '无法连接本地业务服务。'}</div>
            <div class="small" style="margin-top:6px">
              请检查程序目录中的 rka3000-backend 是否完整；日志位于用户数据目录的 logs 子目录。
              {#if connection.phase === 'offline'}<button class="btn sm" type="button" style="margin-left:8px" onclick={() => connection.retry()}>重试连接</button>{/if}
            </div>
          {:else}
            <div class="small">界面已就绪，等待业务服务响应；数据将在连接恢复后自动刷新。</div>
          {/if}
        </div>
      </div>
    {/if}
    {#if connection.health?.restart_required}
      <div class="notice" data-tone="warn" role="status" style="margin-bottom:16px"><div><div class="title">设置已保存，需重启程序后生效</div><div class="small">设备通路、串口、存储与采集周期相关设置在下次启动时应用。</div></div></div>
    {/if}

    {#if page === 'run'}<RunPage {run} online={connection.online} />
    {:else if page === 'recipes'}<RecipesPage online={connection.online} runActive={run.active} />
    {:else if page === 'devices'}<DevicesPage online={connection.online} runActive={run.active} />
    {:else if page === 'analysis'}<AnalysisPage online={connection.online} />
    {:else if page === 'history'}<HistoryPage online={connection.online} activeExperimentId={run.active ? run.state?.experiment_id ?? null : null} />
    {:else if page === 'logs'}<LogsPage online={connection.online} {run} />
    {:else}<SettingsPage online={connection.online} health={connection.health} runActive={run.active} onsaved={() => connection.probe()} />{/if}
  </main>
</div>
<Toasts />
