<script lang="ts">
  import { ws, fmt } from '../lib/sim.svelte'
  let tab = $state(0)
  const events = () => ws.audit.filter(a => tab === 0 || (tab === 1 ? a.action.startsWith('run.') || a.action.startsWith('stage.') : a.action.includes('alarm') || a.action.includes('emergency')))
</script>
<p class="lead">所有仿真控制指令由 Python 校验并写入审计。界面只显示服务端确认后的结果。</p>
<div class="tabs">{#each ['全部事件','控制操作','报警与安全','旧库审计'] as label,i}<button class:active={tab === i} onclick={() => { tab = i; if (i === 3) void ws.loadLegacy() }}>{label}</button>{/each}</div>
{#if tab === 3}<section class="panel"><div class="panel-header"><h2>导入的旧版审计</h2><span class="badge warn">保留来源 · 仅查看</span></div><div class="table-wrap"><table><thead><tr><th>时间</th><th>操作者</th><th>动作</th><th>详情</th><th>来源</th></tr></thead><tbody>{#each ws.legacyAudit as event}<tr><td>{fmt(event.created_at)}</td><td>{event.actor}</td><td>{event.action}</td><td>{event.detail ?? '—'}</td><td class="mono">{event.source_hash.slice(0,12)}</td></tr>{:else}<tr><td colspan="5" class="empty">暂无旧库审计记录</td></tr>{/each}</tbody></table></div></section>{:else}
<section class="panel"><div class="panel-header"><h2>审计记录</h2><button class="button secondary" onclick={() => ws.load()}>刷新</button></div><div class="table-wrap"><table><thead><tr><th>时间</th><th>操作者</th><th>实验</th><th>动作</th><th>详情</th></tr></thead><tbody>{#each events() as event}<tr><td>{fmt(event.created_at)}</td><td>{event.actor}</td><td>{event.run_id ? `#${event.run_id}` : '系统'}</td><td class="mono">{event.action}</td><td>{event.detail}</td></tr>{:else}<tr><td colspan="5" class="empty">暂无记录</td></tr>{/each}</tbody></table></div></section>
{/if}
