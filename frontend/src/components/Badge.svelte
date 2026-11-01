<script lang="ts">
  import type { Tone } from '../lib/format';
  let { tone = '', dot = false, live = false, children }: {
    tone?: Tone; dot?: boolean; live?: boolean; children: import('svelte').Snippet;
  } = $props();
</script>

<span class={`badge ${tone}${live ? ' live' : ''}`}>{#if dot || live}<span class="dot" aria-hidden="true"></span>{/if}{@render children()}</span>
