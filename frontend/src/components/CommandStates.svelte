<script lang="ts">
  /** Three-state command display: accepted → readback verified → applied (grey = not reached). */
  import type { Command } from '../lib/api/types';
  let { command, pending = false }: { command: Command | null; pending?: boolean } = $props();
  const has = (code: string) => command?.steps.some((s) => s.code === code) ?? false;
  const accepted = $derived(pending ? 'on' : has('accepted') ? 'ok' : '');
  const verify = $derived(has('mismatch') ? 'bad' : has('verified') || has('verify_na') ? 'ok' : '');
  const applied = $derived(has('applied') ? 'ok' : command?.state === 'failed' ? 'bad' : '');
  const verifyLabel = $derived(has('mismatch') ? '回读不一致' : has('verify_na') ? '回读不适用' : '回读验证');
</script>

<div class="cmd" aria-label="命令状态">
  <span class={accepted}>已受理</span>
  <span class={verify}>{verifyLabel}</span>
  <span class={applied}>{command?.state === 'failed' ? (has('reverted') ? '已回退配方值' : '未生效') : '生效'}</span>
</div>
