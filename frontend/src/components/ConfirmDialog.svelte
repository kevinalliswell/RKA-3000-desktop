<script lang="ts">
  /**
   * Modal confirmation for side-effecting actions. With ``input`` it also collects a reason/note;
   * the confirm button stays disabled until the text is long enough. Esc cancels.
   */
  let { open, title, message, detail = '', confirmLabel = '确认', tone = 'primary', busy = false, input = null, onconfirm, oncancel }: {
    open: boolean; title: string; message: string; detail?: string; confirmLabel?: string;
    tone?: 'primary' | 'danger'; busy?: boolean;
    input?: { label: string; placeholder?: string; minLength?: number; initial?: string } | null;
    onconfirm: (text: string) => void; oncancel: () => void;
  } = $props();

  let text = $state('');
  let confirmButton = $state<HTMLButtonElement | undefined>();
  let textarea = $state<HTMLTextAreaElement | undefined>();
  $effect(() => {
    if (open) {
      text = input?.initial ?? '';
      queueMicrotask(() => (input ? textarea?.focus() : confirmButton?.focus()));
    }
  });
  const tooShort = $derived(input ? text.trim().length < (input.minLength ?? 0) : false);

  function onkeydown(event: KeyboardEvent) {
    if (event.key === 'Escape' && !busy) oncancel();
  }
</script>

{#if open}
  <div class="backdrop" role="presentation" onkeydown={onkeydown}>
    <div class="dialog" role="alertdialog" aria-modal="true" aria-labelledby="confirm-title" aria-describedby="confirm-message" tabindex="-1">
      <h2 id="confirm-title">{title}</h2>
      <p id="confirm-message">{message}</p>
      {#if detail}<div class="detail">{detail}</div>{/if}
      {#if input}
        <label class="field">
          <span>{input.label}</span>
          <textarea bind:this={textarea} bind:value={text} placeholder={input.placeholder ?? ''} maxlength="300"></textarea>
          {#if input.minLength}<span class="hint">至少 {input.minLength} 个字，会写入操作审计</span>{/if}
        </label>
      {/if}
      <div class="actions">
        <button class="btn" type="button" onclick={oncancel} disabled={busy}>取消</button>
        <button class={`btn ${tone}`} type="button" onclick={() => onconfirm(text.trim())} disabled={busy || tooShort} bind:this={confirmButton}>
          {#if busy}<span class="spinner" aria-hidden="true"></span>{/if}{confirmLabel}
        </button>
      </div>
    </div>
  </div>
{/if}
