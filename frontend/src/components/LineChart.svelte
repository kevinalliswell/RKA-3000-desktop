<script lang="ts">
  /**
   * SVG line chart: a solid main line and dashed secondary lines (design rule), an optional right
   * axis, and shaded x-ranges (for example the current stage). Downsamples to the pixel width.
   * Null y values break the line instead of drawing a fake value.
   */
  export interface Series { name: string; color: string; points: [number, number | null][]; axis?: 'left' | 'right'; dashed?: boolean }
  let { series, xLabel = '', yLabel = '', y2Label = '', height = 260, bands = [], yMin = null, yMax = null, label = '曲线' }: {
    series: Series[]; xLabel?: string; yLabel?: string; y2Label?: string; height?: number;
    bands?: { x0: number; x1: number; label?: string }[]; yMin?: number | null; yMax?: number | null; label?: string;
  } = $props();

  const W = 800;
  const PAD = { top: 18, right: 56, bottom: 30, left: 56 };

  function extent(values: number[], padded = true): [number, number] {
    if (!values.length) return [0, 1];
    let min = Math.min(...values), max = Math.max(...values);
    if (min === max) { min -= 1; max += 1; }
    const pad = padded ? (max - min) * 0.06 : 0;
    return [min - pad, max + pad];
  }

  function downsample(points: [number, number | null][], buckets: number): [number, number | null][] {
    if (points.length <= buckets * 2) return points;
    const size = points.length / buckets;
    const out: [number, number | null][] = [];
    for (let i = 0; i < buckets; i += 1) {
      const slice = points.slice(Math.floor(i * size), Math.floor((i + 1) * size));
      if (slice.length) out.push(slice[Math.floor(slice.length / 2)]!);
    }
    return out;
  }

  const plotW = W - PAD.left - PAD.right;
  const plotH = $derived(height - PAD.top - PAD.bottom);
  const valid = (s: Series) => s.points.filter((p): p is [number, number] => p[1] !== null && Number.isFinite(p[1]));
  const xs = $derived(series.flatMap((s) => s.points.map((p) => p[0])));
  const xExt = $derived(extent(xs, false));
  const leftExt = $derived.by((): [number, number] => {
    const ext = extent(series.filter((s) => s.axis !== 'right').flatMap((s) => valid(s).map((p) => p[1])));
    return [yMin ?? ext[0], yMax ?? ext[1]];
  });
  const rightExt = $derived(extent(series.filter((s) => s.axis === 'right').flatMap((s) => valid(s).map((p) => p[1]))));
  const hasRight = $derived(series.some((s) => s.axis === 'right'));

  function sx(x: number) { return PAD.left + ((x - xExt[0]) / (xExt[1] - xExt[0] || 1)) * plotW; }
  function sy(y: number, ext: [number, number]) { return PAD.top + plotH - ((y - ext[0]) / (ext[1] - ext[0] || 1)) * plotH; }
  function path(s: Series) {
    const ext = s.axis === 'right' ? rightExt : leftExt;
    let d = '';
    let pen = false;
    for (const [x, y] of downsample(s.points, plotW)) {
      if (y === null || !Number.isFinite(y)) { pen = false; continue; }
      d += `${pen ? 'L' : 'M'}${sx(x).toFixed(1)},${sy(y, ext).toFixed(1)}`;
      pen = true;
    }
    return d;
  }
  function ticks(ext: [number, number], n = 5) {
    return Array.from({ length: n }, (_, i) => ext[0] + ((ext[1] - ext[0]) * i) / (n - 1));
  }
  function fmtTick(v: number) { return Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2); }
  const empty = $derived(series.every((s) => valid(s).length === 0));
</script>

<svg class="chart" viewBox={`0 0 ${W} ${height}`} role="img" aria-label={label} style={`height:${height}px`}>
  {#each bands as band}
    {#if band.x1 > xExt[0] && band.x0 < xExt[1]}
      <rect class="band" x={sx(Math.max(band.x0, xExt[0]))} y={PAD.top} width={Math.max(0, sx(Math.min(band.x1, xExt[1])) - sx(Math.max(band.x0, xExt[0])))} height={plotH} />
      {#if band.label}<text x={sx(Math.max(band.x0, xExt[0])) + 4} y={PAD.top + 11}>{band.label}</text>{/if}
    {/if}
  {/each}
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
  {#if yLabel}<text x={PAD.left} y={11}>{yLabel}</text>{/if}
  {#if hasRight && y2Label}<text x={W - PAD.right} y={11} text-anchor="end">{y2Label}</text>{/if}
  {#if xLabel}<text x={W - PAD.right} y={height - 1} text-anchor="end">{xLabel}</text>{/if}
  {#if empty}
    <text x={W / 2} y={height / 2} text-anchor="middle">暂无数据</text>
  {:else}
    {#each series as s}
      <path d={path(s)} fill="none" stroke={s.color} stroke-width={s.dashed ? 1.6 : 2} stroke-dasharray={s.dashed ? '6 4' : undefined} stroke-linejoin="round" />
    {/each}
  {/if}
</svg>
<div class="legend">
  {#each series as s}<span><i class={s.dashed ? 'dash' : ''} style={`border-color:${s.color}`}></i>{s.name}</span>{/each}
</div>
