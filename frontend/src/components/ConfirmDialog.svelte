<script lang="ts">
  /** Modal confirmation for side-effecting actions. Keyboard: Esc cancels, Enter confirms. */
  let { open, title, message, detail = '', confirmLabel = '确认', tone = 'primary', busy = false, onconfirm, oncancel }: {
    open: boolean; title: string; message: string; detail?: string; confirmLabel?: string;
    tone?: 'primary' | 'danger' | 'warn'; busy?: boolean; onconfirm: () => void; oncancel: () => void;
  } = $props();

  let confirmButton = $state<HTMLButtonElement | undefined>();
  $effect(() => { if (open) confirmButton?.focus(); });

  function onkeydown(event: KeyboardEvent) {
    if (event.key === 'Escape') oncancel();
    if (event.key === 'Enter' && !busy) onconfirm();
  }
</script>

{#if open}
  <div class="backdrop" role="presentation" onkeydown={onkeydown}>
    <div class="dialog" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title" aria-describedby="confirm-message" tabindex="-1">
      <h2 id="confirm-title">{title}</h2>
      <p id="confirm-message">{message}</p>
      {#if detail}<div class="detail">{detail}</div>{/if}
      <div class="actions">
        <button class="btn" type="button" onclick={oncancel} disabled={busy}>取消</button>
        <button class={`btn ${tone}`} type="button" onclick={onconfirm} disabled={busy} bind:this={confirmButton}>
          {#if busy}<span class="spinner" aria-hidden="true"></span>{/if}{confirmLabel}
        </button>
      </div>
    </div>
  </div>
{/if}
