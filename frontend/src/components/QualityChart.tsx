import { useId, useState } from 'react'
import { ArrowUpRight } from 'lucide-react'
import type { Runtime, RuntimeQuality } from '../types'

type Bar = { key: string; label: string; quality: RuntimeQuality }

/** A version's bar name: its own name when that already names the model, else "Model · version". */
const versionName = (runtime: Runtime, presetName: string) =>
  presetName.toLowerCase().includes(runtime.name.toLowerCase()) ? presetName : `${runtime.name} · ${presetName}`

/** One bar per model version that has a score (a preset's own score wins over the model's), grouped by metric. */
export function qualityBars(runtimes: Runtime[]): Map<string, Bar[]> {
  const byMetric = new Map<string, Bar[]>()
  for (const runtime of runtimes) {
    for (const [key, preset] of Object.entries(runtime.presets)) {
      const quality = preset.quality ?? runtime.quality
      if (!quality) continue
      // A model-level score applies to every version, which would draw the same bar once per version: draw it once.
      if (!preset.quality && Object.keys(runtime.presets).indexOf(key) > 0) continue
      const label = preset.quality && Object.keys(runtime.presets).length > 1 ? versionName(runtime, preset.name) : runtime.name
      byMetric.set(quality.metric, [...(byMetric.get(quality.metric) ?? []), { key: `${runtime.id}:${key}`, label, quality }])
    }
  }
  return byMetric
}

/** Where the bars start. Elo-style scores sit far above zero, so a zero-based bar would hide the differences; the start
 * is a round number below the lowest score, and the chart says so. */
export function baseline(scores: number[]) {
  const low = Math.min(...scores), high = Math.max(...scores)
  const step = high > 500 ? 50 : high > 100 ? 10 : 5
  return Math.max(0, Math.floor((low - Math.max((high - low) * 0.6, high * 0.02)) / step) * step)
}

const format = (score: number) => Number.isInteger(score) ? String(score) : score.toFixed(1)

function QualityBars({ metric, bars }: { metric: string; bars: Bar[] }) {
  const id = useId()
  const [active, setActive] = useState<string | null>(null)
  const sorted = [...bars].sort((a, b) => b.quality.score - a.quality.score)
  const base = baseline(sorted.map((bar) => bar.quality.score))
  const top = sorted[0].quality.score
  const detail = sorted.find((bar) => bar.key === active)
  return <figure className="quality-chart" aria-labelledby={`${id}-title`}>
    <figcaption><strong id={`${id}-title`}>{metric}</strong><span>Higher is better. Bars start at {format(base)}.</span></figcaption>
    <ul className="quality-bars">
      {sorted.map((bar) => {
        const width = top === base ? 100 : Math.max(3, ((bar.quality.score - base) / (top - base)) * 100)
        return <li key={bar.key} className="quality-row" tabIndex={0} onPointerEnter={() => setActive(bar.key)} onPointerLeave={() => setActive(null)} onFocus={() => setActive(bar.key)} onBlur={() => setActive(null)}
          aria-label={`${bar.label}: ${format(bar.quality.score)}${bar.quality.estimated ? ', estimated' : ''}`}>
          <span className="quality-name">{bar.label}</span>
          <span className="quality-track"><span className={`quality-bar ${bar.quality.estimated ? 'quality-estimated' : ''} ${active === bar.key ? 'quality-bar-active' : ''}`} style={{ width: `${width}%` }} /></span>
          <span className="quality-value">{format(bar.quality.score)}{bar.quality.estimated && <small> est.</small>}</span>
        </li>
      })}
    </ul>
    <p className="quality-detail" aria-live="off">{detail
      ? <><strong>{detail.label}</strong>: {format(detail.quality.score)}{detail.quality.estimated ? ' (estimated)' : ''}{detail.quality.note ? `. ${detail.quality.note}` : ''}{detail.quality.as_of ? ` Read ${detail.quality.as_of}.` : ''}</>
      : 'Hover or focus a bar for how its score was found. Hatched bars are estimates.'}</p>
    <details className="quality-table">
      <summary>Table</summary>
      <table>
        <thead><tr><th scope="col">Model</th><th scope="col">Score</th><th scope="col">Basis</th><th scope="col">Read</th><th scope="col">Source</th></tr></thead>
        <tbody>{sorted.map((bar) => <tr key={bar.key}>
          <th scope="row">{bar.label}</th><td>{format(bar.quality.score)}</td><td>{bar.quality.estimated ? 'Estimate' : 'Published'}{bar.quality.note ? `: ${bar.quality.note}` : ''}</td><td>{bar.quality.as_of ?? ''}</td>
          <td>{bar.quality.source ? <a href={bar.quality.source} target="_blank" rel="noreferrer noopener">Source <ArrowUpRight size={12} aria-hidden="true" /></a> : ''}</td>
        </tr>)}</tbody>
      </table>
    </details>
  </figure>
}

/** Ranked bars of the published quality scores of one kind of model. Models measured on different metrics get their own
 * chart, and a metric with a single model is not charted: one bar says nothing. */
export function QualityChart({ runtimes }: { runtimes: Runtime[] }) {
  const charts = [...qualityBars(runtimes)].filter(([, bars]) => bars.length > 1)
  if (charts.length === 0) return null
  const unrated = runtimes.filter((runtime) => (runtime.workload !== 'text' || runtime.chat) && !runtime.quality && !Object.values(runtime.presets).some((preset) => preset.quality))
  return <div className="quality-charts">
    {charts.map(([metric, bars]) => <QualityBars key={metric} metric={metric} bars={bars} />)}
    {unrated.length > 0 && <p className="quality-unrated">No score yet: {unrated.map((runtime) => runtime.name).join(', ')}.</p>}
  </div>
}
