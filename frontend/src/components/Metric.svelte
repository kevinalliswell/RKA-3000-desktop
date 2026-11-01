<script lang="ts">
  let { label, value, unit = '', tone = '' }: { label: string; value: string; unit?: string; tone?: '' | 'accent' | 'warn' | 'danger' } = $props();
</script>

<div class="metric" data-tone={tone || undefined}>
  <div class="label">{label}</div>
  <div class="value">{value}<span class="unit">{unit}</span></div>
</div>
