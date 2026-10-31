<script lang="ts">
  import { onMount } from 'svelte'
  import { ArrowRight, Bell, Thermometer, Scale, Waves } from '@lucide/svelte'
  import { ws, fmt, num, gases, gasLabels, stateLabels } from '../lib/sim.svelte'
  import Trend from '../components/Trend.svelte'
  const total = () => ws.snapshot?.values ? gases.reduce((sum, gas) => sum + ws.snapshot!.values!.flows[gas], 0) : null
  onMount(() => { if (ws.run) void ws.loadRecentSamples(ws.run.id) })
</script>
<section class="hero"><div class="hero-main"><p class="eyebrow">SIMULATION WORKSPACE</p><h2>{ws.run ? `${ws.run.name} · ${stateLabels[ws.run.state] ?? ws.run.state}` : '仿真环境待机'}</h2><p>按配方与样品建立实验，经预检、惰性置换、反应、冷却、复核后归档。所有控制状态由 Python 确认。</p><button class="button hero-button" onclick={() => ws.navigate(ws.run ? 'current' : 'preflight')}>{ws.run ? '查看当前实验' : '开始实验准备'} <ArrowRight size={16}/></button></div><div class="hero-side"><div><span>运行阶段</span><strong>{ws.run ? stateLabels[ws.run.state] ?? ws.run.state : '待机'}</strong></div><div><span>数据模式</span><strong>软件仿真</strong></div><div><span>最新采样</span><strong>{fmt(ws.snapshot?.sampled_at)}</strong></div></div></section>
<div class="metric-grid">
  <div class="metric"><div class="metric-label"><Thermometer size={17}/>炉温 PV</div><div class="metric-value">{ws.fresh ? num(ws.snapshot?.values?.temperature_c, 1) : '—'} <em>℃</em></div><div class="metric-meta">{fmt(ws.snapshot?.sampled_at)}</div></div>
  <div class="metric"><div class="metric-label"><Scale size={17}/>样品质量</div><div class="metric-value">{ws.fresh ? num(ws.snapshot?.values?.weight_g, 3) : '—'} <em>g</em></div><div class="metric-meta">有效仿真采样</div></div>
  <div class="metric"><div class="metric-label"><Waves size={17}/>总供气流量</div><div class="metric-value">{ws.fresh ? num(total(), 2) : '—'} <em>L/min</em></div><div class="metric-meta">7 种气体 / 6 台 MFC</div></div>
  <div class="metric"><div class="metric-label"><Bell size={17}/>未确认报警</div><div class="metric-value">{ws.alarms.filter(a => !a.acknowledged_at).length}</div><div class="metric-meta">确认和解除分别记录</div></div>
</div>
<div class="content-grid"><section class="panel"><div class="panel-header"><h2>当前供气</h2><span class="badge">L/min</span></div><div class="gas-grid">{#each gases as gas}<div class="gas-readout"><span>{gasLabels[gas]}</span><strong>{ws.fresh ? num(ws.snapshot?.values?.flows[gas]) : '—'}</strong></div>{/each}</div></section><div class="stack"><section class="panel"><div class="panel-header"><h2>工作入口</h2></div><div class="link-list"><button onclick={() => ws.navigate('preflight')}><span><strong>实验准备</strong><small>样品、配方、现场确认</small></span><ArrowRight size={16}/></button><button onclick={() => ws.navigate('history')}><span><strong>历史与复核</strong><small>{ws.historyTotal} 条仿真实验</small></span><ArrowRight size={16}/></button><button onclick={() => ws.navigate('devices')}><span><strong>设备诊断</strong><small>仿真状态和现场接口说明</small></span><ArrowRight size={16}/></button></div></section></div></div>
<section class="panel overview-trend"><div class="panel-header"><h2>最近采样趋势</h2><span class="badge">最多 300 点 · 按需加载</span></div>{#if ws.run && ws.samples.length}<div class="panel-body two-charts"><Trend samples={ws.samples} field="temperature_c" label="温度 / ℃"/><Trend samples={ws.samples} field="weight_g" label="质量 / g" color="#f59e0b"/></div>{:else}<div class="empty">当前无实验采样。启动仿真后显示带时间戳的温度与质量趋势。</div>{/if}</section>
