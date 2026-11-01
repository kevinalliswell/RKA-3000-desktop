<script lang="ts">
  /** Lightweight SVG line chart; downsamples to the pixel width so long runs stay cheap. */
  export interface Series { name: string; color: string; points: [number, number][]; axis?: 'left' | 'right' }
  let { series, xLabel = '', yLabel = '', y2Label = '', height = 260 }: {
    series: Series[]; xLabel?: string; yLabel?: string; y2Label?: string; height?: number;
  } = $props();

  const W = 800;
  const PAD = { top: 14, right: 56, bottom: 30, left: 56 };

  function extent(values: number[], padded = true): [number, number] {
    if (!values.length) return [0, 1];
    let min = Math.min(...values), max = Math.max(...values);
    if (min === max) { min -= 1; max += 1; }
    const pad = padded ? (max - min) * 0.06 : 0;
    return [min - pad, max + pad];
  }

  function downsample(points: [number, number][], buckets: number): [number, number][] {
    if (points.length <= buckets) return points;
    const size = points.length / buckets;
    const out: [number, number][] = [];
    for (let i = 0; i < buckets; i += 1) {
      const slice = points.slice(Math.floor(i * size), Math.floor((i + 1) * size));
      if (slice.length) out.push(slice[Math.floor(slice.length / 2)]!);
    }
    return out;
  }

  const plotW = W - PAD.left - PAD.right;
  const plotH = $derived(height - PAD.top - PAD.bottom);
  const xs = $derived(series.flatMap((s) => s.points.map((p) => p[0])));
  const xExt = $derived(extent(xs, false));
  const leftExt = $derived(extent(series.filter((s) => s.axis !== 'right').flatMap((s) => s.points.map((p) => p[1]))));
  const rightExt = $derived(extent(series.filter((s) => s.axis === 'right').flatMap((s) => s.points.map((p) => p[1]))));
  const hasRight = $derived(series.some((s) => s.axis === 'right'));

  function sx(x: number) { return PAD.left + ((x - xExt[0]) / (xExt[1] - xExt[0])) * plotW; }
  function sy(y: number, ext: [number, number]) { return PAD.top + plotH - ((y - ext[0]) / (ext[1] - ext[0])) * plotH; }
  function path(s: Series) {
    const ext = s.axis === 'right' ? rightExt : leftExt;
    return downsample(s.points, plotW).map((p, i) => `${i ? 'L' : 'M'}${sx(p[0]).toFixed(1)},${sy(p[1], ext).toFixed(1)}`).join(' ');
  }
  function ticks(ext: [number, number], n = 5) {
    return Array.from({ length: n }, (_, i) => ext[0] + ((ext[1] - ext[0]) * i) / (n - 1));
  }
  function fmtTick(v: number) { return Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(1); }
  const empty = $derived(xs.length === 0);
</script>

<svg class="chart" viewBox={`0 0 ${W} ${height}`} role="img" aria-label={`${yLabel} 曲线`} style={`height:${height}px`}>
  <g class="grid">
    {#each ticks(leftExt) as t}
      <line x1={PAD.left} x2={W - PAD.right} y1={sy(t, leftExt)} y2={sy(t, leftExt)} />
      <text x={PAD.left - 6} y={sy(t, leftExt) + 3} text-anchor="end">{fmtTick(t)}</text>
    {/each}
    {#if hasRight}
      {#each ticks(rightExt) as t}
        <text x={W - PAD.right + 6} y={sy(t, rightExt) + 3}>{fmtTick(t)}</text>
      {/each}
    {/if}
    {#each ticks(xExt, 6) as t}
      <text x={sx(t)} y={height - 10} text-anchor="middle">{fmtTick(t)}</text>
    {/each}
  </g>
  <line class="axis" x1={PAD.left} x2={W - PAD.right} y1={PAD.top + plotH} y2={PAD.top + plotH} />
  <line class="axis" x1={PAD.left} x2={PAD.left} y1={PAD.top} y2={PAD.top + plotH} />
  {#if yLabel}<text x={PAD.left} y={10}>{yLabel}</text>{/if}
  {#if hasRight && y2Label}<text x={W - PAD.right} y={10}>{y2Label}</text>{/if}
  {#if xLabel}<text x={W - PAD.right + 8} y={height - 10}>{xLabel}</text>{/if}
  {#if empty}
    <text x={W / 2} y={height / 2} text-anchor="middle">暂无数据</text>
  {:else}
    {#each series as s}
      <path d={path(s)} fill="none" stroke={s.color} stroke-width="1.8" stroke-linejoin="round" />
    {/each}
  {/if}
</svg>
<div class="legend">
  {#each series as s}<span><i style={`background:${s.color}`}></i>{s.name}</span>{/each}
</div>
