<script lang="ts">
  let { tone = 'neutral', children }: { tone?: 'neutral' | 'ok' | 'warn' | 'danger' | 'info' | 'busy'; children: import('svelte').Snippet } = $props();
</script>

<span class="badge" data-tone={tone}>{@render children()}</span>
