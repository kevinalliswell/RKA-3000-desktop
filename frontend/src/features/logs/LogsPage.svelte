<script lang="ts">
  import { onMount } from 'svelte';
  import Badge from '../../components/Badge.svelte';
  import * as api from '../../lib/api/endpoints';
  import type { AlarmRecord, AuditRecord, Task } from '../../lib/api/types';
  import type { RunSession } from '../../lib/state/run.svelte';
  import { errorMessage } from '../../lib/api/client';
  import { downloadText, fmtTime, taskStatusLabel } from '../../lib/format';

  let { online, run }: { online: boolean; run: RunSession } = $props();

  let tab: 'alarms' | 'audit' | 'tasks' | 'backend' = $state('alarms');
  let alarms: AlarmRecord[] = $state([]);
  let audit: AuditRecord[] = $state([]);
  let tasks: Task[] = $state([]);
  let backendLog = $state('');
  let backendPath = $state('');
  let error = $state('');
  let loading = $state(false);

  async function refresh() {
    if (!online) return;
    loading = true;
    try {
      if (tab === 'alarms') alarms = await api.listAlarms(undefined, 300);
      else if (tab === 'audit') audit = await api.listAudit(500);
      else if (tab === 'tasks') tasks = await api.listTasks(50);
      else { const log = await api.backendLog(); backendLog = log.content; backendPath = log.path; }
      error = '';
    } catch (e) { error = errorMessage(e); } finally { loading = false; }
  }

  onMount(() => { void refresh(); });
  $effect(() => { void tab; if (online) void refresh(); });
  const pending = $derived(run.state?.pending_alarms ?? []);
</script>

<div class="stack">
  <section class="panel">
    <div class="panel-head">
      <div class="row">
        <h2>报警与日志</h2>
        {#if pending.length}<Badge tone="danger">{pending.length} 条待确认报警</Badge>{/if}
      </div>
      <div class="row">
        {#each [['alarms', '报警历史'], ['audit', '操作审计'], ['tasks', '后台任务'], ['backend', '后端日志']] as [id, label]}
          <button class="btn sm" type="button" aria-pressed={tab === id} style={tab === id ? 'background:var(--accent-soft);color:var(--accent-ink);border-color:var(--accent-soft)' : ''} onclick={() => (tab = id as typeof tab)}>{label}</button>
        {/each}
        <button class="btn sm" type="button" onclick={refresh} disabled={!online || loading}>刷新</button>
        {#if tab === 'backend'}<button class="btn sm" type="button" onclick={() => downloadText('backend.log', backendLog, 'text/plain')} disabled={!backendLog}>下载日志</button>{/if}
      </div>
    </div>
    <div class="panel-body stack">
      {#if error}<div class="notice" data-tone="danger" role="alert">{error}</div>{/if}
      {#if tab === 'alarms'}
        {#if alarms.length}
          <div class="table-wrap"><table><thead><tr><th>时间</th><th>实验</th><th>代码</th><th>级别</th><th>内容</th><th>确认</th></tr></thead><tbody>
            {#each alarms as alarm}<tr><td class="mono">{fmtTime(alarm.created_at)}</td><td class="mono">{alarm.experiment_id ?? '--'}</td><td class="mono">{alarm.code}</td><td><Badge tone={alarm.level === 'CRITICAL' ? 'danger' : alarm.level === 'HIGH' ? 'warn' : 'neutral'}>{alarm.level}</Badge></td><td>{alarm.message}</td><td class="small">{alarm.acknowledged_at ? `${fmtTime(alarm.acknowledged_at)} · ${alarm.acknowledged_by ?? ''}` : '未确认'}</td></tr>{/each}
          </tbody></table></div>
        {:else}<div class="empty"><strong>没有报警记录</strong>报警触发后会在此记录并保留确认信息。</div>{/if}
      {:else if tab === 'audit'}
        {#if audit.length}
          <div class="table-wrap"><table><thead><tr><th>时间</th><th>操作者</th><th>动作</th><th>详情</th></tr></thead><tbody>
            {#each audit as row}<tr><td class="mono">{fmtTime(row.created_at)}</td><td>{row.actor}</td><td class="mono">{row.action}</td><td class="small">{row.detail}</td></tr>{/each}
          </tbody></table></div>
        {:else}<div class="empty">暂无操作记录。</div>{/if}
      {:else if tab === 'tasks'}
        {#if tasks.length}
          <div class="table-wrap"><table><thead><tr><th>创建</th><th>类型</th><th>状态</th><th>进度</th><th>结果 / 错误</th></tr></thead><tbody>
            {#each tasks as task}<tr><td class="mono">{fmtTime(task.created_at)}</td><td>{task.kind}</td><td><Badge tone={task.status === 'completed' ? 'ok' : task.status === 'failed' ? 'danger' : task.status === 'cancelled' ? 'neutral' : 'busy'}>{taskStatusLabel[task.status]}</Badge></td><td class="num">{Math.round(task.progress * 100)}%</td><td class="small mono">{task.error ?? task.result?.path ?? ''}</td></tr>{/each}
          </tbody></table></div>
        {:else}<div class="empty">暂无后台任务（导出、报告）。</div>{/if}
      {:else}
        <p class="small muted">文件：<span class="mono">{backendPath || '--'}</span>（显示最后 256 KB）</p>
        <pre class="log">{backendLog || '（空）'}</pre>
      {/if}
    </div>
  </section>
</div>
