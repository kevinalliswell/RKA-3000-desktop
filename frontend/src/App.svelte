<script lang="ts">
  import { onMount } from 'svelte';
  import Toasts from './components/Toasts.svelte';
  import Badge from './components/Badge.svelte';
  import Icon from './components/Icon.svelte';
  import { Connection } from './lib/state/connection.svelte';
  import { RunSession } from './lib/state/run.svelte';
  import { prefs, THEMES } from './lib/state/prefs.svelte';
  import { nav, NAV } from './lib/state/nav.svelte';
  import * as api from './lib/api/endpoints';
  import type { Overview } from './lib/api/types';
  import { DEVICE_LABEL, runStatusLabel, runStatusTone } from './lib/format';
  import OverviewPage from './features/overview/OverviewPage.svelte';
  import PreflightPage from './features/preflight/PreflightPage.svelte';
  import CurrentPage from './features/run/CurrentPage.svelte';
  import RecipesPage from './features/recipes/RecipesPage.svelte';
  import HistoryPage from './features/history/HistoryPage.svelte';
  import AlarmsPage from './features/alarms/AlarmsPage.svelte';
  import DevicesPage from './features/devices/DevicesPage.svelte';
  import AuditPage from './features/audit/AuditPage.svelte';
  import AnalysisPage from './features/analysis/AnalysisPage.svelte';
  import ReportsPage from './features/reports/ReportsPage.svelte';
  import SettingsPage from './features/settings/SettingsPage.svelte';

  const connection = new Connection();
  const run = new RunSession();
  let summary = $state<Overview | null>(null);
  let now = $state(new Date());
  let summaryTimer: ReturnType<typeof setTimeout> | undefined;

  async function refreshSummary() {
    clearTimeout(summaryTimer);
    if (connection.online) {
      try { summary = await api.overview(); } catch { /* shown by the connection banner */ }
    }
    summaryTimer = setTimeout(refreshSummary, 4000);
  }

  onMount(() => {
    prefs.load();
    void connection.start();
    run.start();
    void refreshSummary();
    const clock = setInterval(() => (now = new Date()), 1000);
    return () => { connection.dispose(); run.dispose(); clearInterval(clock); clearTimeout(summaryTimer); };
  });

  const pendingAlarms = $derived(run.state?.pending_alarms.length ?? summary?.pending_alarms.length ?? 0);
  const pendingReview = $derived(summary?.counts.pending ?? 0);
  const stale = $derived(run.state?.stale_devices ?? []);
  const connectionLabel = $derived(
    connection.phase === 'online' ? '' : connection.phase === 'connecting' ? '正在连接本地服务…'
    : connection.phase === 'retrying' ? `重连中 (${connection.attempts}/${connection.maxAttempts})`
    : connection.phase === 'exited' ? '业务服务已退出' : '本地服务不可用');
  const themeName = $derived(THEMES.find((t) => t.id === prefs.effectiveTheme())?.label ?? '');
  const nextTheme = $derived(({ light: '深色', dark: '科技蓝', blue: '浅色' } as const)[prefs.effectiveTheme()]);
  const clock = $derived(`${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')} ${now.toLocaleTimeString('zh-CN', { hour12: false })}`);
  const limitsLocked = $derived(Boolean(run.active || pendingReview));
  const navCount = (id: string) => id === 'alarms' ? pendingAlarms : id === 'analysis' ? pendingReview : 0;
</script>

<svelte:head><title>RKA-3000 实验系统</title></svelte:head>

<div class="shell">
  <aside class="sidebar">
    <div class="brand">
      <div class="mark" aria-hidden="true">R</div>
      <div><div class="name">RKA-3000</div><div class="sub">实验控制工作台</div></div>
    </div>
    <nav class="nav" aria-label="主导航">
      {#each NAV as group}
        <div class="group">
          <p class="group-title">{group.title}</p>
          {#each group.items as item}
            <button type="button" aria-current={nav.page === item.id ? 'page' : undefined} onclick={() => nav.go(item.id)}>
              <Icon name={item.id} />{item.label}
              {#if navCount(item.id)}<b class={`count${item.id === 'analysis' ? ' warn' : ''}`}>{navCount(item.id)}</b>{/if}
            </button>
          {/each}
        </div>
      {/each}
    </nav>
    <div class="sidebar-foot">
      <strong>{prefs.operator || '未设置操作者'}</strong> · 当前操作者<br />
      使用上限策略 v{summary?.limits_version ?? '…'} · {limitsLocked ? '实验未归档，已锁定' : '待机可配置'}<br />
      v{connection.health?.version ?? '…'}{connection.health?.simulation_mode ? ' · 仿真模式' : ''}
    </div>
  </aside>

  <div class="main">
    <header class="topbar">
      <span class="crumb">{nav.crumb()}</span>
      <span class="fill"></span>
      <button type="button" class="tgl" onclick={() => prefs.cycleTheme()} title={`当前：${themeName}`}><i aria-hidden="true"></i>切换：{nextTheme}</button>
      {#if run.state && run.active}
        <Badge tone={runStatusTone[run.state.status]} live={run.active}>{runStatusLabel[run.state.status]}</Badge>
      {/if}
      {#if !connection.online}
        <Badge tone={connection.phase === 'exited' || connection.phase === 'offline' ? 'danger' : 'warn'} dot>{connectionLabel}</Badge>
      {:else if stale.length}
        <Badge tone="warn" dot>回读过期：{stale.map((d) => DEVICE_LABEL[d] ?? d).join('、')}</Badge>
      {:else}
        <Badge tone="good" dot>{run.active ? '回读正常' : '本地服务在线'}{connection.health?.simulation_mode ? ' · 仿真' : ''}</Badge>
      {/if}
      {#if pendingAlarms}
        <button type="button" class="badge warn" style="border:0" onclick={() => nav.go('alarms')}>{pendingAlarms} 条待确认报警</button>
      {/if}
      <span class="clock mono">{clock}</span>
    </header>

    <main class="content">
      {#if !connection.online}
        <div class={`callout ${connection.phase === 'exited' || connection.phase === 'offline' ? 'danger' : 'warn'}`} role="alert">
          <strong>{connectionLabel}</strong>
          {#if connection.phase === 'offline' || connection.phase === 'exited'}
            <div>{connection.error || '无法连接本地业务服务。'} 请检查程序目录中的 rka3000-backend 是否完整；日志位于用户数据目录的 logs 子目录。</div>
            {#if connection.phase === 'offline'}<div class="actions"><button class="btn sm" type="button" onclick={() => connection.retry()}>重试连接</button></div>{/if}
          {:else}
            <div>界面已就绪，等待业务服务响应；数据将在连接恢复后自动刷新。</div>
          {/if}
        </div>
      {/if}
      {#if connection.health?.restart_required}
        <div class="callout warn" role="status"><strong>设置已保存，需重启程序后生效。</strong> 设备通路、串口、存储与采集周期相关设置在下次启动时应用。</div>
      {/if}
      {#if connection.health?.notes?.length && nav.page === 'overview'}
        <div class="callout" role="status">{#each connection.health.notes as note}<div>{note}</div>{/each}</div>
      {/if}

      {#if nav.page === 'overview'}<OverviewPage {run} {summary} online={connection.online} />
      {:else if nav.page === 'preflight'}<PreflightPage {run} online={connection.online} />
      {:else if nav.page === 'current'}<CurrentPage {run} online={connection.online} />
      {:else if nav.page === 'recipes'}<RecipesPage online={connection.online} runActive={run.active} />
      {:else if nav.page === 'history'}<HistoryPage online={connection.online} />
      {:else if nav.page === 'alarms'}<AlarmsPage {run} online={connection.online} />
      {:else if nav.page === 'devices'}<DevicesPage {run} online={connection.online} />
      {:else if nav.page === 'audit'}<AuditPage online={connection.online} />
      {:else if nav.page === 'analysis'}<AnalysisPage online={connection.online} onarchived={refreshSummary} />
      {:else if nav.page === 'reports'}<ReportsPage online={connection.online} />
      {:else}<SettingsPage online={connection.online} health={connection.health} runActive={run.active} onsaved={() => connection.probe()} />{/if}
    </main>
  </div>
</div>
<Toasts />
