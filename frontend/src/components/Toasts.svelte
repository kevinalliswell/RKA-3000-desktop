<script lang="ts">
  import { notifier } from '../lib/state/notify.svelte';
  const tone = { ok: 'good', warn: 'warn', danger: 'danger', info: '' } as const;
</script>

<div class="toasts" aria-live="polite">
  {#each notifier.toasts as toast (toast.id)}
    <div class={`toast ${tone[toast.tone]}`} role="status">
      <div><div class="title">{toast.title}</div>{#if toast.text}<div class="soft">{toast.text}</div>{/if}</div>
      <button class="close" type="button" aria-label="关闭提示" onclick={() => notifier.dismiss(toast.id)}>×</button>
    </div>
  {/each}
</div>
