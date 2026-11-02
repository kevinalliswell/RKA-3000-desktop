<script lang="ts">
  /** 16px stroke icons used in navigation and buttons (design canvas icon set). Decorative by default. */
  let { name, size = 16 }: { name: string; size?: number } = $props();
  const PATHS: Record<string, string> = {
    overview: '<rect x="2" y="2" width="5" height="5" rx="1"/><rect x="9" y="2" width="5" height="5" rx="1"/><rect x="2" y="9" width="5" height="5" rx="1"/><rect x="9" y="9" width="5" height="5" rx="1"/>',
    preflight: '<rect x="3" y="2.5" width="10" height="12" rx="1.5"/><path d="M6 7h4M6 10h4"/>',
    current: '<path d="M1.5 8h3l2-5 3 10 2-5h3"/>',
    recipes: '<path d="M6 1.5h4M7 1.5v5L3 13a1.5 1.5 0 0 0 1.3 2h7.4A1.5 1.5 0 0 0 13 13L9 6.5v-5"/>',
    history: '<circle cx="8" cy="8" r="6"/><path d="M8 4.5V8l2.5 1.5"/>',
    alarms: '<path d="M4 11V7a4 4 0 0 1 8 0v4l1 1.5H3z"/><path d="M6.5 14a1.5 1.5 0 0 0 3 0"/>',
    devices: '<rect x="4" y="4" width="8" height="8" rx="1.5"/><path d="M6 1.5v2.5M10 1.5v2.5M6 12v2.5M10 12v2.5M1.5 6h2.5M1.5 10h2.5M12 6h2.5M12 10h2.5"/>',
    audit: '<rect x="3" y="2.5" width="10" height="12" rx="1.5"/><path d="M6 7h4M6 10h2"/>',
    analysis: '<path d="M2 13h12M4 11V7M8 11V4M12 11V8"/>',
    reports: '<path d="M4 1.5h5l3 3v10H4z"/><path d="M9 1.5v3h3"/>',
    settings: '<circle cx="8" cy="8" r="2.2"/><path d="M8 1.5v2M8 12.5v2M1.5 8h2M12.5 8h2M3.4 3.4l1.4 1.4M11.2 11.2l1.4 1.4M3.4 12.6l1.4-1.4M11.2 4.8l1.4-1.4"/>',
    stop: '<rect x="3.5" y="3.5" width="9" height="9" rx="1"/>',
    check: '<path d="M3 8.5l3 3 7-7"/>',
    arrow: '<path d="M3 8h10M9 4l4 4-4 4"/>',
    plus: '<path d="M8 3v10M3 8h10"/>',
    download: '<path d="M8 2v8M4.5 6.5 8 10l3.5-3.5M3 13.5h10"/>',
  };
</script>

<svg aria-hidden="true" width={size} height={size} viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6"
  stroke-linecap="round" stroke-linejoin="round">{@html PATHS[name] ?? ''}</svg>
