<script lang="ts">
  import { onMount } from 'svelte'
  import { Activity, AlertTriangle, ArrowRight, Bell, BookOpen, ChartNoAxesCombined, Check,
    ChevronRight, ClipboardList, Clock3, Cpu, FileText, FlaskConical, Gauge, History,
    Menu, Moon, RefreshCw, Scale, Settings2, Sun, Thermometer, Waves } from '@lucide/svelte'
  import { callBackend, type Bootstrap, type ExperimentDetail, type ExperimentSummary, type RecipeDetail, type RecipeSummary, type Snapshot } from './lib/bridge'

  type Page = 'overview' | 'preflight' | 'current' | 'recipes' | 'history' | 'alarms' |
    'devices' | 'audit' | 'analysis' | 'reports' | 'settings' | 'help'
  const groups = [
    { label: '工作台', items: [
      { id: 'overview', label: '实时总览', icon: Gauge },
      { id: 'preflight', label: '实验准备', icon: ClipboardList },
      { id: 'current', label: '当前实验', icon: Activity },
    ] },
    { label: '实验管理', items: [
      { id: 'recipes', label: '实验配方', icon: FlaskConical },
      { id: 'history', label: '历史实验', icon: History },
      { id: 'alarms', label: '报警事件', icon: Bell },
    ] },
    { label: '系统与结果', items: [
      { id: 'devices', label: '设备诊断', icon: Cpu },
      { id: 'audit', label: '操作审计', icon: ClipboardList },
      { id: 'analysis', label: '数据分析', icon: ChartNoAxesCombined },
      { id: 'reports', label: '报告中心', icon: FileText },
      { id: 'settings', label: '系统设置', icon: Settings2 },
      { id: 'help', label: '使用帮助', icon: BookOpen },
    ] },
  ] as const
  const names = Object.fromEntries(groups.flatMap(group => group.items.map(item => [item.id, item.label]))) as Record<Page, string>
  const tabs: Partial<Record<Page, string[]>> = {
    preflight: ['样品信息', '选择配方', '启动检查'],
    current: ['运行监控', '实时趋势', '控制记录'],
    recipes: ['配方列表', '配方详情'],
    history: ['实验列表', '实验详情'],
    alarms: ['当前报警', '历史事件'],
    devices: ['设备概览', '连接拓扑', 'MFC 通道', '通信诊断'],
    audit: ['全部事件', '控制操作', '报警与安全'],
    analysis: ['指标工作台', '计算依据'],
    reports: ['报告列表', '报告预览', '字段与审签'],
    settings: ['界面与采样', '串口配置', '安全边界'],
    help: ['实验流程', '版本状态'],
  }
  const descriptions: Record<Page, string> = {
    overview: '按实验任务组织设备、采样与下一步操作。',
    preflight: '按实验流程检查样品、配方、设备与现场条件。',
    current: '查看当前实验状态、实时数据和阶段进度。',
    recipes: '查看现有 Python 数据库中的实验配方。',
    history: '查询现有数据库中的实验记录。',
    alarms: '查看报警状态及其处理原则。',
    devices: '区分仿真读数与现场设备通信状态。',
    audit: '追溯实验控制和安全相关操作。',
    analysis: '对有效实验数据进行方法计算与质量评估。',
    reports: '从历史实验生成技术记录并审核。',
    settings: '界面偏好、通信配置和安全边界。',
    help: '了解系统使用流程与当前版本范围。',
  }

  let page = $state<Page>('overview')
  let selectedTab = $state(0)
  let dark = $state(true)
  let menuOpen = $state(false)
  let boot = $state<Bootstrap | null>(null)
  let snapshot = $state<Snapshot | null>(null)
  let recipes = $state<RecipeSummary[]>([])
  let history = $state<ExperimentSummary[]>([])
  let selectedRecipe = $state<RecipeSummary | null>(null)
  let selectedExperiment = $state<ExperimentSummary | null>(null)
  let recipeDetail = $state<RecipeDetail | null>(null)
  let experimentDetail = $state<ExperimentDetail | null>(null)
  let historySearch = $state('')
  let historyStatus = $state('all')
  let error = $state('')
  let busy = $state(false)
  let now = $state(Date.now())
  let tempSeries = $state<number[]>([])
  let weightSeries = $state<number[]>([])

  const fresh = () => snapshot !== null && now - new Date(snapshot.sampled_at).getTime() < 8000
  const number = (value: number | undefined, digits: number) => value === undefined ? '—' : value.toFixed(digits)
  const date = (value: string | null | undefined) => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'
  const filteredHistory = () => history.filter(item =>
    (historyStatus === 'all' || item.status === historyStatus) &&
    `${item.id} ${item.name} ${item.recipe_name ?? ''}`.toLowerCase().includes(historySearch.toLowerCase()))
  const points = (values: number[]) => {
    if (values.length < 2) return '0,64 100,64'
    const low = Math.min(...values), span = Math.max(Math.max(...values) - low, 0.1)
    return values.map((value, index) => `${index * 100 / (values.length - 1)},${72 - (value - low) * 54 / span}`).join(' ')
  }
  function navigate(target: Page) {
    page = target
    selectedTab = 0
    menuOpen = false
    window.location.hash = target
  }
  async function refresh(full = false) {
    if (busy) return
    busy = true
    try {
      if (full) {
        const result = await callBackend<Bootstrap>('bootstrap')
        boot = result
        recipes = result.recipes
        history = result.experiments
        snapshot = result.snapshot
      } else {
        snapshot = await callBackend<Snapshot>('snapshot')
      }
      if (snapshot) {
        tempSeries = [...tempSeries, snapshot.values.temperature_c].slice(-30)
        weightSeries = [...weightSeries, snapshot.values.weight_g].slice(-30)
      }
      now = Date.now()
      error = ''
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause)
      now = Date.now()
    } finally {
      busy = false
    }
  }
  async function loadHistory() {
    try {
      history = (await callBackend<{ items: ExperimentSummary[] }>('history')).items
      error = ''
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause)
    }
  }
  async function openRecipe(item: RecipeSummary) {
    selectedRecipe = item
    recipeDetail = null
    selectedTab = 1
    try {
      recipeDetail = await callBackend<RecipeDetail>('recipe_detail', { id: item.id })
      error = ''
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause)
    }
  }
  async function openExperiment(item: ExperimentSummary) {
    selectedExperiment = item
    experimentDetail = null
    selectedTab = 1
    try {
      experimentDetail = await callBackend<ExperimentDetail>('experiment_detail', { id: item.id })
      error = ''
    } catch (cause) {
      error = cause instanceof Error ? cause.message : String(cause)
    }
  }
  function changeTheme() {
    dark = !dark
    document.documentElement.dataset.theme = dark ? 'dark' : 'light'
    localStorage.setItem('rka-theme', dark ? 'dark' : 'light')
  }
  onMount(() => {
    dark = localStorage.getItem('rka-theme') !== 'light'
    document.documentElement.dataset.theme = dark ? 'dark' : 'light'
    const hash = window.location.hash.slice(1)
    if (hash in names) page = hash as Page
    void refresh(true)
    const timer = window.setInterval(() => void refresh(), 2000)
    return () => window.clearInterval(timer)
  })
</script>

<svelte:head><title>{names[page]} · RKA-3000</title></svelte:head>
<div class="shell">
  {#if menuOpen}<button class="backdrop" aria-label="关闭导航" onclick={() => menuOpen = false}></button>{/if}
  <aside class:open={menuOpen} class="sidebar" aria-label="主导航">
    <div class="brand"><div class="brand-mark">R</div><div><strong>RKA-3000</strong><small>实验控制工作台</small></div></div>
    <nav class="nav-scroll">
      {#each groups as group}
        <div class="nav-group"><div class="nav-label">{group.label}</div>
          {#each group.items as item}
            <button class:active={page === item.id} class="nav-item" aria-current={page === item.id ? 'page' : undefined} onclick={() => navigate(item.id)}>
              <item.icon size={17} strokeWidth={1.8} /><span>{item.label}</span>
            </button>
          {/each}
        </div>
      {/each}
    </nav>
    <div class="nav-foot"><strong>桌面新版 · v{boot?.version ?? '0.7.0'}</strong><span>仿真只读预览<br />真实设备控制尚未接入</span></div>
  </aside>
  <div class="workspace">
    <header class="topbar">
      <button class="icon-button menu-button" aria-label="打开导航" onclick={() => menuOpen = true}><Menu size={19} /></button>
      <div class="top-path"><small>USTB / RKA-3000</small><strong>{names[page]}</strong></div>
      <div class="top-status">
        <span class="badge warn">仿真模式</span>
        <span class:good={fresh()} class:danger={!fresh()} class="badge"><span class="dot"></span>{fresh() ? '仿真数据新鲜' : '数据不可用'}</span>
        <button class="icon-button" aria-label="刷新数据" title="刷新数据" disabled={busy} onclick={() => refresh(true)}><span class:spin={busy}><RefreshCw size={17} /></span></button>
        <button class="icon-button theme-button" aria-label={dark ? '切换浅色界面' : '切换深色界面'} onclick={changeTheme}>{#if dark}<Sun size={17} />{:else}<Moon size={17} />{/if}<span>{dark ? '浅色' : '深色'}</span></button>
      </div>
    </header>
    <div class="scope-strip"><strong>桌面新版预览</strong><span>当前仅连接 Python 仿真数据与既有数据库；现场设备在线状态、实验控制和真实写入尚未启用。</span></div>
    <main class="page" id="main-content">
      <div class="page-head"><div><p class="eyebrow">RKA-3000 / {page.toUpperCase()}</p><h1>{names[page]}</h1><p class="lead">{descriptions[page]}</p></div>
        {#if page === 'overview'}<button class="button primary" onclick={() => navigate('preflight')}>实验准备 <ArrowRight size={16} /></button>{/if}
        {#if page === 'devices' || page === 'history'}<button class="button secondary" disabled={busy} onclick={() => page === 'history' ? loadHistory() : refresh(true)}><RefreshCw size={15} /> 刷新状态</button>{/if}
      </div>
      {#if error}<div class="callout danger" role="alert"><AlertTriangle size={18} /><span>{error}</span></div>{/if}
      {#if page === 'overview'}
        <section class="hero"><div class="hero-main"><p class="eyebrow">SYSTEM STANDBY</p><h2>设备待机 · 仿真环境已就绪</h2><p>先核对实验配方、样品信息及现场安全条件。新版桌面界面目前提供状态预览，实验执行请使用原桌面程序。</p><button class="button hero-button" onclick={() => navigate('preflight')}>查看实验准备 <ArrowRight size={16} /></button></div><div class="hero-side"><div><span>运行阶段</span><strong>待机</strong></div><div><span>数据模式</span><strong>软件仿真</strong></div><div><span>最新采样</span><strong>{date(snapshot?.sampled_at)}</strong></div></div></section>
        <div class="metric-grid">
          <div class="metric"><div class="metric-label"><Thermometer size={17} />炉温 PV</div><div class="metric-value">{fresh() ? number(snapshot?.values.temperature_c, 1) : '—'} <em>℃</em></div><div class="metric-meta">仿真温控读数</div></div>
          <div class="metric"><div class="metric-label"><Scale size={17} />样品重量</div><div class="metric-value">{fresh() ? number(snapshot?.values.weight_g, 3) : '—'} <em>g</em></div><div class="metric-meta">仿真天平读数</div></div>
          <div class="metric"><div class="metric-label"><Waves size={17} />总供气流量</div><div class="metric-value">{fresh() && snapshot ? number(snapshot.values.n2_lpm + snapshot.values.h2_lpm + snapshot.values.co_lpm, 2) : '—'} <em>L/min</em></div><div class="metric-meta">现有三气路仿真映射</div></div>
          <div class="metric"><div class="metric-label"><Bell size={17} />报警字</div><div class="metric-value">{fresh() ? snapshot?.values.alarm_word ?? '—' : '—'} <em>bit</em></div><div class="metric-meta">{snapshot?.values.alarm_word ? '请检查报警位' : '仿真状态无报警'}</div></div>
        </div>
        <div class="content-grid"><section class="panel"><div class="panel-header"><div><h2>温度趋势</h2><p>最近 60 秒仿真采样</p></div><span class="badge">℃</span></div><div class="chart"><div class="chart-value">{number(snapshot?.values.temperature_c, 1)} <small>℃</small></div><svg viewBox="0 0 100 88" preserveAspectRatio="none" role="img" aria-label="最近温度趋势"><line x1="0" y1="72" x2="100" y2="72"/><line x1="0" y1="44" x2="100" y2="44"/><line x1="0" y1="18" x2="100" y2="18"/><polyline points={points(tempSeries)} /></svg><div class="chart-axis"><span>60 秒前</span><span>当前</span></div></div></section>
          <div class="stack"><section class="panel"><div class="panel-header"><h2>下一步操作</h2></div><div class="link-list"><button onclick={() => navigate('preflight')}><span><strong>完成实验前预检</strong><small>检查样品、配方和现场条件</small></span><ChevronRight size={17} /></button><button onclick={() => navigate('recipes')}><span><strong>核对实验配方</strong><small>{recipes.length} 条既有配方</small></span><ChevronRight size={17} /></button><button onclick={() => navigate('history')}><span><strong>查看历史实验</strong><small>确认数据质量和记录</small></span><ChevronRight size={17} /></button></div></section><section class="panel"><div class="panel-header"><h2>设备链路</h2><button class="text-button" onclick={() => navigate('devices')}>查看诊断 <ArrowRight size={14} /></button></div><div class="device-list"><div><strong>温控器 · TAIE</strong><span class="badge warn">仿真</span></div><div><strong>MFC · Azbil</strong><span class="badge warn">仿真</span></div><div><strong>电子天平</strong><span class="badge warn">仿真</span></div></div></section></div>
        </div>
      {:else}
        {#if tabs[page]}<div class="tabs" role="tablist" aria-label={`${names[page]}子页面`}>{#each tabs[page] as label, index}<button role="tab" aria-selected={selectedTab === index} class:active={selectedTab === index} onclick={() => selectedTab = index}>{label}</button>{/each}</div>{/if}
        {#if page === 'recipes'}
          {#if selectedTab === 0}<section class="panel"><div class="panel-header"><div><h2>已保存配方</h2><p>来自现有 Python 数据库</p></div><span class="badge">{recipes.length} 条</span></div><div class="table-wrap"><table><thead><tr><th>编号</th><th>配方名称</th><th>更新时间</th><th>操作</th></tr></thead><tbody>{#each recipes as item}<tr><td class="mono">{item.id}</td><td><strong>{item.name}</strong></td><td>{date(item.updated_at)}</td><td><button class="text-button" onclick={() => openRecipe(item)}>查看详情 <ArrowRight size={14} /></button></td></tr>{:else}<tr><td colspan="4" class="empty">暂无配方记录</td></tr>{/each}</tbody></table></div></section>
          {:else}<section class="panel"><div class="panel-header"><h2>{recipeDetail?.item.name ?? selectedRecipe?.name ?? '配方详情'}</h2></div><div class="panel-body">{#if recipeDetail}<div class="detail-grid"><div><span>配方编号</span><strong>#{recipeDetail.item.id}</strong></div><div><span>创建时间</span><strong>{date(recipeDetail.item.created_at)}</strong></div><div><span>阶段数量</span><strong>{recipeDetail.steps.length}</strong></div></div><h3 class="section-title">阶段参数</h3><div class="table-wrap"><table><thead><tr><th>阶段</th><th>目标 ℃</th><th>速率 ℃/min</th><th>保持 s</th><th>N₂ L/min</th><th>H₂ L/min</th><th>CO L/min</th></tr></thead><tbody>{#each recipeDetail.steps as step}<tr><td class="mono">{step.step_no}</td><td>{number(step.target_temp_c, 1)}</td><td>{number(step.ramp_rate_cpm, 2)}</td><td>{step.hold_seconds}</td><td>{number(step.n2_lpm, 2)}</td><td>{number(step.h2_lpm, 2)}</td><td>{number(step.co_lpm, 2)}</td></tr>{:else}<tr><td colspan="7" class="empty">暂无阶段参数</td></tr>{/each}</tbody></table></div><p class="muted">当前仅展示现有三气路配方，新增气体仍待现场映射。</p>{:else}<p class="empty">{selectedRecipe ? '正在读取配方详情…' : '请先从配方列表选择一条记录。'}</p>{/if}</div></section>{/if}
        {:else if page === 'history'}
          {#if selectedTab === 0}<section class="panel"><div class="panel-header"><div><h2>实验记录</h2><p>按名称、编号或配方筛选</p></div><span class="badge">{filteredHistory().length} 条</span></div><div class="filter-row"><input aria-label="搜索实验" placeholder="搜索编号、样品或配方" bind:value={historySearch} /><select aria-label="实验状态" bind:value={historyStatus}><option value="all">全部状态</option><option value="RUNNING">运行中</option><option value="FINISHED">已完成</option><option value="ABORTED">已中止</option></select></div><div class="table-wrap"><table><thead><tr><th>编号</th><th>实验名称</th><th>配方</th><th>状态</th><th>开始时间</th><th>操作</th></tr></thead><tbody>{#each filteredHistory() as item}<tr><td class="mono">{item.id}</td><td><strong>{item.name}</strong></td><td>{item.recipe_name ?? '—'}</td><td><span class="badge">{item.status}</span></td><td>{date(item.started_at)}</td><td><button class="text-button" onclick={() => openExperiment(item)}>查看详情 <ArrowRight size={14} /></button></td></tr>{:else}<tr><td colspan="6" class="empty">没有匹配的实验记录</td></tr>{/each}</tbody></table></div></section>
          {:else}<section class="panel"><div class="panel-header"><h2>{experimentDetail?.item.name ?? selectedExperiment?.name ?? '实验详情'}</h2></div><div class="panel-body">{#if experimentDetail}<div class="detail-grid"><div><span>实验编号</span><strong>#{experimentDetail.item.id}</strong></div><div><span>当前状态</span><strong>{experimentDetail.item.status}</strong></div><div><span>使用配方</span><strong>{experimentDetail.item.recipe_name ?? '—'}</strong></div><div><span>开始时间</span><strong>{date(experimentDetail.item.started_at)}</strong></div><div><span>结束时间</span><strong>{date(experimentDetail.item.finished_at)}</strong></div><div><span>采样数 / 报警数</span><strong>{experimentDetail.summary?.sample_count ?? 0} / {experimentDetail.alarms.length}</strong></div></div><p class="muted">原始采样范围：{date(experimentDetail.summary?.first_sampled_at)} 至 {date(experimentDetail.summary?.last_sampled_at)}。无采样数据时报告不能用于结果判断。</p>{:else}<p class="empty">{selectedExperiment ? '正在读取实验详情…' : '请先从实验列表选择一条记录。'}</p>{/if}</div></section>{/if}
        {:else if page === 'devices'}
          {#if selectedTab === 0}<div class="device-grid">{#each [{ name: '温控器', model: 'TAIE · Modbus RTU', value: `${number(snapshot?.values.temperature_c, 1)} ℃`, icon: Thermometer }, { name: '质量流量控制器', model: 'Azbil · CPL', value: `${number(snapshot?.values.n2_lpm, 2)} / ${number(snapshot?.values.h2_lpm, 2)} / ${number(snapshot?.values.co_lpm, 2)} L/min`, icon: Waves }, { name: '电子天平', model: '串口 ASCII', value: `${number(snapshot?.values.weight_g, 3)} g`, icon: Scale }] as item}<div class="device-card"><div class="device-icon"><item.icon size={21} /></div><span class="badge warn">仿真读数</span><h2>{item.name}</h2><p>{item.model}</p><strong>{fresh() ? item.value : '—'}</strong><small>采集于 {date(snapshot?.sampled_at)}</small></div>{/each}</div>
          {:else if selectedTab === 1}<section class="panel"><div class="panel-header"><h2>独立串口拓扑</h2></div><div class="topology"><div class="topology-core">Python 通信层</div><span>↙</span><span>↓</span><span>↘</span><div>TAIE<br /><small>Modbus RTU</small></div><div>Azbil MFC<br /><small>CPL</small></div><div>电子天平<br /><small>ASCII</small></div></div><div class="panel-body"><p class="muted">现场端口、地址、量程和气体映射须由配置与设备回读核验。本界面尚未读取现场连接状态。</p></div></section>
          {:else if selectedTab === 2}<section class="panel"><div class="panel-header"><h2>MFC 通道与介质</h2><span class="badge warn">待现场核验</span></div><div class="panel-body"><p class="muted">原型中的 6 通道与 7 种气体是目标设计；当前 Python 主链路仍为 N₂/H₂/CO 三气路。不能用仿真值证明现场 MFC 在线。</p></div></section>
          {:else}<section class="panel"><div class="panel-header"><h2>通信诊断</h2></div><div class="panel-body"><div class="callout"><AlertTriangle size={18} /><span>本桌面新版尚未启动真实设备扫描。只有仿真桥接数据有最新采样时间；现场在线状态应由独立通信线程定期轮询后提供。</span></div><div class="detail-grid"><div><span>数据源</span><strong>Python 仿真客户端</strong></div><div><span>最新采样</span><strong>{date(snapshot?.sampled_at)}</strong></div><div><span>数据有效性</span><strong>{fresh() ? '新鲜' : '过期 / 不可用'}</strong></div></div></div></section>{/if}
        {:else if page === 'preflight'}
          <section class="panel"><div class="panel-header"><h2>{selectedTab === 0 ? '01 · 样品信息' : selectedTab === 1 ? '02 · 选择实验配方' : '03 · 启动前检查'}</h2><span class="badge warn">只读预览</span></div><div class="panel-body">{#if selectedTab === 0}<div class="form-grid"><label>样品名称<input placeholder="请输入样品名称" disabled /></label><label>初始质量 · g<input placeholder="待天平稳定读数" disabled /></label></div><p class="muted">新版暂未保存实验准备信息；实际实验从原桌面程序启动。</p>{:else if selectedTab === 1}<div class="simple-list">{#each recipes as item}<div><FlaskConical size={18} /><strong>{item.name}</strong><span>#{item.id}</span></div>{:else}<p class="empty">暂无可用配方</p>{/each}</div>{:else}<div class="check-list"><div><Check size={17} />确认配方类型与气体介质匹配</div><div><Check size={17} />确认温控、MFC、天平回读新鲜</div><div><Check size={17} />确认独立急停和现场安全条件</div><div><Check size={17} />确认置换、反应和安全收尾阶段</div></div><div class="callout warn"><AlertTriangle size={18} /><span>现场通信与安全条件未接入，此页不能作为启动许可。</span></div>{/if}</div></section>
        {:else if page === 'current'}
          <section class="panel"><div class="panel-header"><h2>{tabs.current?.[selectedTab]}</h2><span class="badge">待机</span></div><div class="panel-body">{#if selectedTab === 1}<div class="two-charts"><div class="mini-chart"><strong>炉温 · ℃</strong><svg viewBox="0 0 100 88" preserveAspectRatio="none" role="img" aria-label="炉温趋势"><polyline points={points(tempSeries)} /></svg></div><div class="mini-chart"><strong>重量 · g</strong><svg viewBox="0 0 100 88" preserveAspectRatio="none" role="img" aria-label="重量趋势"><polyline points={points(weightSeries)} /></svg></div></div>{:else}<div class="empty-state"><Activity size={35} /><h3>当前没有由新版界面启动的实验</h3><p>控制、暂停、继续和结束动作仍在原桌面程序中。新版仅显示仿真状态。</p></div>{/if}</div></section>
        {:else if page === 'alarms'}
          <section class="panel"><div class="panel-header"><h2>{tabs.alarms?.[selectedTab]}</h2><span class="badge warn">仿真状态</span></div><div class="panel-body">{#if selectedTab === 0 && snapshot?.values.alarm_word}<div class="callout danger"><AlertTriangle size={18} /><span>仿真报警字：{snapshot.values.alarm_word}。请在原桌面程序中查看细节。</span></div>{:else}<div class="empty-state"><Bell size={35} /><h3>{selectedTab === 0 ? '当前无仿真报警' : '历史报警尚未迁入'}</h3><p>真实报警确认和解除必须分别记录，并以现场故障状态为准。</p></div>{/if}</div></section>
        {:else if page === 'settings'}
          <section class="panel"><div class="panel-header"><h2>{tabs.settings?.[selectedTab]}</h2></div><div class="panel-body">{#if selectedTab === 0}<div class="settings-row"><span><strong>界面主题</strong><small>偏好仅保存在本机</small></span><button class="button secondary" onclick={changeTheme}>{dark ? '切换浅色' : '切换深色'}</button></div><div class="settings-row"><span><strong>仿真采样</strong><small>界面每 2 秒请求一次，过期阈值 8 秒</small></span><span class="badge good">运行中</span></div>{:else if selectedTab === 1}<div class="callout"><Cpu size={18} /><span>现场配置由 Python 后端的独立设备配置文件管理。新版暂不提供修改入口，也不会自动连接真实串口。</span></div>{:else}<div class="check-list"><div><Check size={17} />真实设备写入未开放</div><div><Check size={17} />仿真值不能作为启动许可</div><div><Check size={17} />急停和断气由独立硬件负责</div></div>{/if}</div></section>
        {:else if page === 'help'}
          <section class="panel"><div class="panel-header"><h2>{tabs.help?.[selectedTab]}</h2></div><div class="panel-body">{#if selectedTab === 0}<div class="workflow">{#each ['选择实验类型与配方', '核验气源与现场设备', '录入样品并完成预检', '惰性气体置换', '升温与反应测定', '安全吹扫与冷却', '复核数据并生成报告'] as step, index}<div><b>{String(index + 1).padStart(2, '0')}</b><span>{step}</span></div>{/each}</div>{:else}<div class="detail-grid"><div><span>界面技术</span><strong>Tauri 2 + Svelte 5</strong></div><div><span>业务后端</span><strong>Python</strong></div><div><span>当前版本</span><strong>v{boot?.version ?? '0.7.0'}</strong></div><div><span>运行范围</span><strong>仿真只读预览</strong></div></div>{/if}</div></section>
        {:else}
          <section class="panel"><div class="panel-header"><h2>{names[page]}</h2><span class="badge warn">迁移中</span></div><div class="panel-body"><div class="empty-state"><Clock3 size={35} /><h3>此功能正在迁入新版桌面界面</h3><p>{page === 'reports' ? '原桌面程序已支持生成实验技术记录；新版报告列表、预览与导出尚待接入。' : page === 'analysis' ? '指标计算需要核对方法标准和数据有效性，目前不输出未经验证的结果。' : '正式审计需要来自后端的操作者、时间戳和设备回读，当前不展示演示记录。'}</p></div></div></section>
        {/if}
      {/if}
    </main>
  </div>
</div>
