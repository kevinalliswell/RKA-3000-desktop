<script lang="ts">
  import { onMount } from 'svelte'
  import { Activity, Bell, BookOpen, ChartNoAxesCombined, ClipboardList, Cpu, FileText, FlaskConical, Gauge, History, Menu, Moon, RefreshCw, Settings2, Sun } from '@lucide/svelte'
  import { ws, type Page } from './lib/sim.svelte'
  import Overview from './pages/Overview.svelte'
  import Preflight from './pages/Preflight.svelte'
  import Current from './pages/Current.svelte'
  import Recipes from './pages/Recipes.svelte'
  import HistoryPage from './pages/History.svelte'
  import Alarms from './pages/Alarms.svelte'
  import Devices from './pages/Devices.svelte'
  import Audit from './pages/Audit.svelte'
  import Analysis from './pages/Analysis.svelte'
  import Reports from './pages/Reports.svelte'
  import Settings from './pages/Settings.svelte'
  import Help from './pages/Help.svelte'

  const groups = [
    { label: '工作台', items: [{id:'overview',label:'实时总览',icon:Gauge},{id:'preflight',label:'实验准备',icon:ClipboardList},{id:'current',label:'当前实验',icon:Activity}] },
    { label: '实验管理', items: [{id:'recipes',label:'实验配方',icon:FlaskConical},{id:'history',label:'历史实验',icon:History},{id:'alarms',label:'报警事件',icon:Bell}] },
    { label: '系统与结果', items: [{id:'devices',label:'设备诊断',icon:Cpu},{id:'audit',label:'操作审计',icon:ClipboardList},{id:'analysis',label:'数据分析',icon:ChartNoAxesCombined},{id:'reports',label:'报告中心',icon:FileText},{id:'settings',label:'系统设置',icon:Settings2},{id:'help',label:'使用帮助',icon:BookOpen}] },
  ] as const
  const names = Object.fromEntries(groups.flatMap(group => group.items.map(item => [item.id,item.label]))) as Record<Page,string>
  let dark = $state(true)
  let menuOpen = $state(false)
  function theme() {
    dark = !dark
    document.documentElement.dataset.theme = dark ? 'dark' : 'light'
    localStorage.setItem('rka-theme', dark ? 'dark' : 'light')
  }
  function navigate(page: Page) { ws.navigate(page); menuOpen = false }
  onMount(() => {
    localStorage.removeItem('rka-report-print')
    dark = localStorage.getItem('rka-theme') !== 'light'
    document.documentElement.dataset.theme = dark ? 'dark' : 'light'
    const hash = location.hash.slice(1)
    if (hash in names) ws.page = hash as Page
    void ws.load()
    void ws.loadDevices()
    const poll = window.setInterval(() => void ws.poll(), 2000)
    const devicesPoll = window.setInterval(() => void ws.loadDevices(), 30000)
    return () => { window.clearInterval(poll); window.clearInterval(devicesPoll) }
  })
</script>

<svelte:head><title>{names[ws.page]} · RKA-3000</title></svelte:head>
<div class="shell">
  {#if menuOpen}<button class="backdrop" aria-label="关闭导航" onclick={() => menuOpen = false}></button>{/if}
  <aside class:open={menuOpen} class="sidebar" aria-label="主导航">
    <div class="brand"><div class="brand-mark">R</div><div><strong>RKA-3000</strong><small>实验控制工作台</small></div></div>
    <nav class="nav-scroll">
      {#each groups as group}
        <div class="nav-group"><div class="nav-label">{group.label}</div>
          {#each group.items as item}
            <button class:active={ws.page === item.id} class="nav-item" aria-current={ws.page === item.id ? 'page' : undefined} onclick={() => navigate(item.id as Page)}><item.icon size={17} strokeWidth={1.8} /><span>{item.label}</span></button>
          {/each}
        </div>
      {/each}
    </nav>
    <div class="nav-foot"><strong>桌面新版 · v{ws.version}</strong><span>仿真实验工作台<br />真实设备写入禁用</span></div>
  </aside>
  <div class="workspace">
    <header class="topbar">
      <button class="icon-button menu-button" aria-label="打开导航" onclick={() => menuOpen = true}><Menu size={19} /></button>
      <div class="top-path"><small>USTB / RKA-3000</small><strong>{names[ws.page]}</strong></div>
      <div class="top-status">
        <span class="badge warn">仿真模式</span>
        <span class:good={ws.fresh} class:danger={!ws.fresh} class="badge"><span class="dot"></span>{ws.fresh ? '数据新鲜' : ws.snapshot?.state === 'offline' ? '仿真离线' : ws.snapshot?.state === 'stale' ? '数据过期' : '无有效采样'}</span>
        <button class="icon-button" aria-label="刷新数据" disabled={ws.busy} onclick={() => ws.load()}><RefreshCw size={17} /></button>
        <button class="icon-button theme-button" aria-label={dark ? '切换浅色界面' : '切换深色界面'} onclick={theme}>{#if dark}<Sun size={17} />{:else}<Moon size={17} />{/if}</button>
      </div>
    </header>
    <div class="scope-strip"><strong>仿真工作台</strong><span>实验流程由 Python 校验并持久化；模拟读数不能作为现场设备在线证明。真实设备写入保持禁用。</span></div>
    <main class="page" id="main-content">
      <div class="page-head"><div><p class="eyebrow">RKA-3000 / {ws.page.toUpperCase()}</p><h1>{names[ws.page]}</h1></div></div>
      {#if ws.error}<div class="callout danger" role="alert"><span>错误：{ws.error}</span><button class="text-button" onclick={() => ws.error = ''}>关闭</button></div>{/if}
      {#if ws.notice}<div class="callout" role="status"><span>{ws.notice}</span><button class="text-button" onclick={() => ws.notice = ''}>关闭</button></div>{/if}
      {#if ws.page === 'overview'}<Overview />{:else if ws.page === 'preflight'}<Preflight />{:else if ws.page === 'current'}<Current />{:else if ws.page === 'recipes'}<Recipes />{:else if ws.page === 'history'}<HistoryPage />{:else if ws.page === 'alarms'}<Alarms />{:else if ws.page === 'devices'}<Devices />{:else if ws.page === 'audit'}<Audit />{:else if ws.page === 'analysis'}<Analysis />{:else if ws.page === 'reports'}<Reports />{:else if ws.page === 'settings'}<Settings />{:else}<Help />{/if}
    </main>
  </div>
</div>
