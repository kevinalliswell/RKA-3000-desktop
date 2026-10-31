<script lang="ts">
  import { onMount } from 'svelte'
  import uPlot from 'uplot'
  import 'uplot/dist/uPlot.min.css'
  import type { Sample } from '../lib/sim.svelte'
  let { samples, field, label, color = '#38bdf8' }: { samples: Sample[]; field: 'temperature_c' | 'weight_g'; label: string; color?: string } = $props()
  let host: HTMLDivElement
  let plot: uPlot | null = null
  function data(): uPlot.AlignedData {
    return [samples.map(s => Date.parse(s.sampled_at) / 1000), samples.map(s => s.quality === 'simulated' ? s[field] : null)]
  }
  onMount(() => {
    const render = () => {
      if (plot) plot.destroy()
      plot = new uPlot({ width: Math.max(280, host.clientWidth), height: 220, series: [{}, { label, stroke: color, width: 2 }],
        axes: [{ stroke: '#8594ac', grid: { stroke: '#29364a' } }, { stroke: '#8594ac', grid: { stroke: '#29364a' } }],
        scales: { x: { time: true } } }, data(), host)
    }
    render()
    const observer = new ResizeObserver(render)
    observer.observe(host)
    return () => { observer.disconnect(); plot?.destroy(); plot = null }
  })
  $effect(() => { samples; if (plot) plot.setData(data()) })
</script>
<div class="trend" role="img" aria-label={`${label}趋势，${samples.length}个采样点`} bind:this={host}></div>
