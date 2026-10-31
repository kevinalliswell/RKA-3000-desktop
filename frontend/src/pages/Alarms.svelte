<script lang="ts">
  import { ws, fmt } from '../lib/sim.svelte'
  let tab = $state(0)
  let actor = $state('operator')
  async function ack(id: number) { try { await ws.request('sim_alarm_ack', { id, actor }); ws.notice = '报警确认已记录'; await ws.load() } catch { /* shown */ } }
  async function clear(id: number) { try { await ws.request('sim_alarm_clear', { id, actor }); ws.notice = '报警解除已记录'; await ws.load() } catch { /* shown */ } }
</script>
<p class="lead">报警发生、人工确认和解除是不同事件。确认不会把故障标记为解除。</p>
<div class="tabs"><button class:active={tab === 0} onclick={() => tab = 0}>未解除报警</button><button class:active={tab === 1} onclick={() => tab = 1}>历史事件</button></div>
<section class="panel"><div class="panel-header"><h2>{tab === 0 ? '当前报警' : '报警历史'}</h2><label>操作人 <input bind:value={actor} placeholder="姓名或工号"/></label></div><div class="table-wrap"><table><thead><tr><th>发生时间</th><th>级别</th><th>代码</th><th>内容</th><th>确认</th><th>解除</th><th>操作</th></tr></thead><tbody>{#each ws.alarms.filter(a => tab === 1 || !a.cleared_at) as alarm}<tr><td>{fmt(alarm.appeared_at)}</td><td>{alarm.severity}</td><td class="mono">{alarm.code}</td><td>{alarm.message}</td><td>{alarm.acknowledged_at ? `${alarm.acknowledged_by} · ${fmt(alarm.acknowledged_at)}` : '未确认'}</td><td>{alarm.cleared_at ? fmt(alarm.cleared_at) : '未解除'}</td><td>{#if !alarm.acknowledged_at}<button class="button secondary" onclick={() => ack(alarm.id)}>确认</button>{:else if !alarm.cleared_at}<button class="button secondary" onclick={() => clear(alarm.id)}>解除</button>{/if}</td></tr>{:else}<tr><td colspan="7" class="empty">暂无报警</td></tr>{/each}</tbody></table></div></section>
