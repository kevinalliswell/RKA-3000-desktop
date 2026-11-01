<script lang="ts">
  let { label, value, unit = '', hint = '', tone = '' }: {
    label: string; value: string; unit?: string; hint?: string; tone?: '' | 'good' | 'warn' | 'danger';
  } = $props();
</script>

<div class="metric" data-tone={tone || undefined}>
  <div class="l">{label}</div>
  <div class="v">{value}{#if unit}<small>{unit}</small>{/if}</div>
  {#if hint}<div class="h">{hint}</div>{/if}
</div>
