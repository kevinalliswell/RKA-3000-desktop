<script lang="ts">
  import { onMount } from 'svelte'
  let { title, detail, confirmText = '确认', danger = false, requireNote = false, note = $bindable(''), onconfirm, oncancel }: { title: string; detail: string; confirmText?: string; danger?: boolean; requireNote?: boolean; note?: string; onconfirm: () => void; oncancel: () => void } = $props()
  let cancelButton: HTMLButtonElement
  let dialog: HTMLDivElement
  onMount(() => {
    const previous = document.activeElement as HTMLElement | null
    cancelButton.focus()
    return () => { if (previous?.isConnected) previous.focus() }
  })
  function handleKey(event: KeyboardEvent) {
    if (event.key === 'Escape') { event.preventDefault(); oncancel() }
    if (event.key === 'Tab') {
      const items = [...dialog.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled)')]
      const first = items[0]
      const last = items.at(-1)
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
    }
    event.stopPropagation()
  }
</script>
<div class="modal-backdrop" role="presentation" onclick={oncancel} onkeydown={(event) => { if (event.key === 'Escape') oncancel() }}>
  <div class="modal" role="alertdialog" tabindex="-1" aria-modal="true" aria-labelledby="confirm-title" aria-describedby="confirm-detail" bind:this={dialog} onclick={(event) => event.stopPropagation()} onkeydown={handleKey}>
    <h2 id="confirm-title">{title}</h2><p id="confirm-detail">{detail}</p>
    {#if requireNote}<label class="modal-field">复核结论<input bind:value={note} placeholder="填写数据质量和处置结论" /></label>{/if}
    <div class="action-row"><button class="button secondary" bind:this={cancelButton} onclick={oncancel}>取消</button><button class:danger class="button primary" disabled={requireNote && !note.trim()} onclick={onconfirm}>{confirmText}</button></div>
  </div>
</div>
