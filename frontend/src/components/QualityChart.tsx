import { useId, useState } from 'react'
import { ArrowUpRight } from 'lucide-react'
import type { Runtime, RuntimeQuality } from '../types'

type Bar = { key: string; label: string; quality: RuntimeQuality }

/** A version's bar name: its own name when that already names the model, else "Model · version". */
const versionName = (runtime: Runtime, presetName: string) =>
  presetName.toLowerCase().includes(runtime.name.toLowerCase()) ? presetName : `${runtime.name} · ${presetName}`

/** One bar per model version and metric, grouped by metric. A version's own score for a metric replaces the model's for
 * that metric; a metric no version overrides is drawn once for the model, since it applies to every version. */
export function qualityBars(runtimes: Runtime[]): Map<string, Bar[]> {
  const byMetric = new Map<string, Bar[]>()
  const scoresOf = (owner: { quality?: RuntimeQuality | null; rankings?: RuntimeQuality[] }) =>
    new Map([owner.quality, ...(owner.rankings ?? [])].filter((score): score is RuntimeQuality => !!score).map((score) => [score.metric, score]))
  const add = (metric: string, bar: Bar) => byMetric.set(metric, [...(byMetric.get(metric) ?? []), bar])
  for (const runtime of runtimes) {
    const shared = scoresOf(runtime)
    const presets = Object.entries(runtime.presets).map(([key, preset]) => ({ key, preset, own: scoresOf(preset) }))
    const metrics = new Set([...shared.keys(), ...presets.flatMap(({ own }) => [...own.keys()])])
    for (const metric of metrics) {
      if (!presets.some(({ own }) => own.has(metric))) {
        add(metric, { key: `${runtime.id}:${presets[0].key}`, label: runtime.name, quality: shared.get(metric)! })
        continue
      }
      for (const { key, preset, own } of presets) {
        const quality = own.get(metric) ?? shared.get(metric)
        if (quality) add(metric, { key: `${runtime.id}:${key}`, label: presets.length > 1 ? versionName(runtime, preset.name) : runtime.name, quality })
      }
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

/** The rankings a kind of model offers: metrics at least two of its models have a score on. */
export const qualityCharts = (runtimes: Runtime[]) => [...qualityBars(runtimes)].filter(([, bars]) => bars.length > 1)

/** The chosen ranking, or the first when none is chosen or the choice is gone. */
export const chosenChart = (charts: ReturnType<typeof qualityCharts>, metric: string | null) => charts.find(([name]) => name === metric) ?? charts[0]

/** Each model's best score on a ranking (a model with several versions counts by its best), by runtime id. */
export function scoresOn(bars: Bar[]) {
  const best = new Map<string, number>()
  for (const bar of bars) {
    const id = bar.key.split(':')[0]
    best.set(id, Math.max(best.get(id) ?? -Infinity, bar.quality.score))
  }
  return best
}

/** Ranked bars of the published quality scores of one kind of model, one ranking at a time: a button per metric switches
 * between them. A metric with a single model is not offered: one bar says nothing. */
export function QualityChart({ runtimes, metric: chosen, onMetric }: { runtimes: Runtime[]; metric: string | null; onMetric: (metric: string) => void }) {
  const charts = qualityCharts(runtimes)
  const tabs = useId()
  if (charts.length === 0) return null
  const [metric, bars] = chosenChart(charts, chosen)
  const scored = new Set(bars.map((bar) => bar.key.split(':')[0]))
  const unrated = runtimes.filter((runtime) => (runtime.workload !== 'text' || runtime.chat) && !scored.has(runtime.id))
  // Folded by default: the cards are the page's subject, and the ranking is there when it is wanted.
  return <details className="quality-charts">
    <summary><span>Quality ranking</span><small>{charts.map(([name]) => name).join(' · ')}</small></summary>
    <div className="quality-charts-body">
      {charts.length > 1 && <div className="quality-tabs" role="group" aria-label="Ranking">
        {charts.map(([name, list]) => <button key={name} type="button" id={`${tabs}-${name}`} className={`button button-small ${name === metric ? 'button-primary' : 'button-secondary'}`} aria-pressed={name === metric} onClick={() => onMetric(name)}>{name}<small>{list.length}</small></button>)}
      </div>}
      <QualityBars key={metric} metric={metric} bars={bars} />
      {unrated.length > 0 && <p className="quality-unrated">Not on this ranking: {unrated.map((runtime) => runtime.name).join(', ')}.</p>}
    </div>
  </details>
}
