<script lang="ts">
  /** Segmented control for 2–3 mutually exclusive options that apply immediately. */
  let { options, value, label, disabled = false, onselect }: {
    options: { id: string; label: string; disabled?: boolean }[]; value: string; label: string; disabled?: boolean;
    onselect: (id: string) => void;
  } = $props();
</script>

<div class="seg" role="group" aria-label={label}>
  {#each options as option (option.id)}
    <button type="button" aria-pressed={value === option.id} disabled={disabled || option.disabled}
      onclick={() => { if (value !== option.id) onselect(option.id); }}>{option.label}</button>
  {/each}
</div>
