<script lang="ts">
  import { notifier } from '../lib/state/notify.svelte';
</script>

<div class="toasts" aria-live="polite">
  {#each notifier.toasts as toast (toast.id)}
    <div class="notice" data-tone={toast.tone} role="status">
      <div><div class="title">{toast.title}</div>{#if toast.text}<div>{toast.text}</div>{/if}</div>
      <button class="close" type="button" aria-label="关闭" onclick={() => notifier.dismiss(toast.id)}>×</button>
    </div>
  {/each}
</div>
