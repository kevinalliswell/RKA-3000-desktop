<script lang="ts">
  import { ws } from '../lib/sim.svelte'
  let tab = $state(0)
  const steps = ['配方与样品','启动预检','惰性置换','反应测定','吹扫冷却','数据复核','归档与报告']
</script>
<p class="lead">桌面新版用于七气体仿真实验流程验证。原 PySide6 程序继续承担现有完整实验入口。</p>
<div class="tabs"><button class:active={tab === 0} onclick={() => tab = 0}>实验流程</button><button class:active={tab === 1} onclick={() => tab = 1}>版本状态</button></div>
{#if tab === 0}<section class="panel"><div class="panel-header"><h2>标准实验流程</h2></div><div class="panel-body"><div class="workflow">{#each steps as step,i}<div><b>{String(i+1).padStart(2,'0')}</b><strong>{step}</strong></div>{/each}</div><p class="muted">暂停可恢复；故障暂停须先解除仿真场景；紧急处置只能复核后归档。重启后未完成实验标记待复核。</p><button class="button primary" onclick={() => ws.navigate('preflight')}>开始实验准备</button></div></section>{/if}
{#if tab === 1}<section class="panel"><div class="panel-header"><h2>版本与限制</h2></div><div class="panel-body"><div class="detail-grid"><div><span>应用版本</span><strong>{ws.version}</strong></div><div><span>后端</span><strong>Python 仿真工作线程</strong></div><div><span>界面</span><strong>Tauri 2 + Svelte 5</strong></div><div><span>现场连接</span><strong>未启用</strong></div><div><span>真实写入</span><strong>禁用</strong></div><div><span>PDF</span><strong>系统打印对话框</strong></div></div><p class="muted">现场地址、介质、量程及联锁尚待核验；仿真结果不能作为真机验收。</p></div></section>{/if}
