<script lang="ts">
  import { onMount } from 'svelte'
  let { title, detail, confirmText = '确认', danger = false, requireNote = false, note = $bindable(''), onconfirm, oncancel }: { title: string; detail: string; confirmText?: string; danger?: boolean; requireNote?: boolean; note?: string; onconfirm: () => void; oncancel: () => void } = $props()
  let cancelButton: HTMLButtonElement
  onMount(() => cancelButton.focus())
</script>
<div class="modal-backdrop" role="presentation" onclick={oncancel} onkeydown={(event) => { if (event.key === 'Escape') oncancel() }}>
  <div class="modal" role="alertdialog" tabindex="-1" aria-modal="true" aria-labelledby="confirm-title" aria-describedby="confirm-detail" onclick={(event) => event.stopPropagation()} onkeydown={(event) => { if (event.key === 'Escape') oncancel(); event.stopPropagation() }}>
    <h2 id="confirm-title">{title}</h2><p id="confirm-detail">{detail}</p>
    {#if requireNote}<label class="modal-field">复核结论<input bind:value={note} placeholder="填写数据质量和处置结论" /></label>{/if}
    <div class="action-row"><button class="button secondary" bind:this={cancelButton} onclick={oncancel}>取消</button><button class:danger class="button primary" disabled={requireNote && !note.trim()} onclick={onconfirm}>{confirmText}</button></div>
  </div>
</div>
