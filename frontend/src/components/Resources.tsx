import type { ReactNode } from 'react'
import { AlertCircle, CircleHelp, Cpu } from 'lucide-react'
import { formatBytes, humanAge } from '../api'
import type { Host, Memory, ModelMemory, Runtime, RuntimeEstimate } from '../types'


/** One running model's share of a memory bar. */
export type Segment = { id: string; label: string; bytes: number; color: string }

const segmentColors = ['#e08a3c', '#2d9c8a', '#d4528c', '#5b6fd6', '#a2b33a', '#9b59c9']

/** A stable color per model, in catalog order, shared by the bars and the model cards. */
export function modelColor(runtimes: Runtime[] | null | undefined, modelId: string) {
  const index = (runtimes ?? []).findIndex((runtime) => runtime.id === modelId)
  return segmentColors[(index < 0 ? 0 : index) % segmentColors.length]
}

function validUsage(value: unknown): value is ModelMemory {
  if (!value || typeof value !== 'object') return false
  const usage = value as Record<string, unknown>
  const okBytes = (bytes: unknown) => typeof bytes === 'number' && Number.isFinite(bytes) && bytes >= 0
  return (usage.ram_bytes === null || okBytes(usage.ram_bytes)) && !!usage.gpus && typeof usage.gpus === 'object'
    && Object.values(usage.gpus as object).every(okBytes)
}

/** Per-model usage from a host snapshot, dropping anything malformed. */
export function modelUsage(host: Host | undefined, modelId: string): ModelMemory | undefined {
  const usage = host?.model_memory?.[modelId]
  return validUsage(usage) ? usage : undefined
}

export function ramSegments(host: Host | undefined, runtimes: Runtime[] | null | undefined): Segment[] {
  return (runtimes ?? []).flatMap((runtime) => {
    const bytes = modelUsage(host, runtime.id)?.ram_bytes
    return bytes ? [{ id: runtime.id, label: runtime.name, bytes, color: modelColor(runtimes, runtime.id) }] : []
  })
}

export function gpuSegments(host: Host | undefined, runtimes: Runtime[] | null | undefined, gpuId: string): Segment[] {
  return (runtimes ?? []).flatMap((runtime) => {
    const bytes = modelUsage(host, runtime.id)?.gpus[gpuId]
    return bytes ? [{ id: runtime.id, label: runtime.name, bytes, color: modelColor(runtimes, runtime.id) }] : []
  })
}

/** One resource a start would need, compared with what live telemetry says is free for it. */
export type Fit = { key: string; label: string; need: number; free: number | null; headroom: number; fits: boolean | null }

/** Mirror of admission's rule (available − headroom − reservations), for display. The host checks again on Start. */
export function estimateFit(host: Host | undefined, estimate: RuntimeEstimate, fresh: boolean): Fit[] {
  const free = (available: number | undefined, headroom: number, reserved: number) =>
    fresh && available != null ? Math.max(0, available - headroom - reserved) : null
  const ramFree = free(host?.ram?.available_bytes, estimate.ram_headroom_bytes, estimate.reserved_ram_bytes)
  const fits: Fit[] = [{ key: 'ram', label: 'RAM', need: estimate.ram_bytes, free: ramFree, headroom: estimate.ram_headroom_bytes, fits: ramFree == null ? null : estimate.ram_bytes <= ramFree }]
  for (const [id, need] of Object.entries(estimate.gpu_vram_bytes_by_id)) {
    const gpu = host?.gpus.find((item) => item.id === id)
    const gpuFree = free(gpu?.memory?.available_bytes, estimate.gpu_headroom_bytes, estimate.reserved_gpu_vram_bytes_by_id[id] ?? 0)
    fits.push({ key: id, label: gpu?.name ?? 'GPU', need, free: gpuFree, headroom: estimate.gpu_headroom_bytes, fits: gpuFree == null ? null : need <= gpuFree })
  }
  return fits
}

/** A model that is not running, drawn after current use to show what starting it would add. */
export type Preview = { label: string; bytes: number; color: string; fits: boolean | null }

/** A used-memory bar split into each running model's share and everything else; hover a part for its size. */
function UsageBar({ label, used, total, fillClass, segments = [], preview }: { label: string; used: number | null; total: number | null; fillClass: string; segments?: Segment[]; preview?: Preview }) {
  const percent = (bytes: number) => total ? Math.min(100, Math.max(0, bytes / total * 100)) : 0
  const usedPercent = used == null ? 0 : percent(used)
  let left = usedPercent
  const parts = segments.map((segment) => {
    const width = Math.min(left, percent(segment.bytes))
    left -= width
    return { ...segment, width }
  }).filter((part) => part.width > 0)
  const otherBytes = used == null ? 0 : Math.max(0, used - segments.reduce((sum, segment) => sum + segment.bytes, 0))
  return <div className="progress-track usage-track" role="progressbar" aria-label={`${label} used`} aria-valuenow={used == null ? undefined : Math.round(usedPercent)} aria-valuemin={0} aria-valuemax={100}>
    {parts.map((part) => <span key={part.id} className="usage-seg" tabIndex={0} style={{ width: `${part.width}%`, background: part.color }}
      aria-label={`${part.label}: ${formatBytes(part.bytes)}`} data-tip={`${part.label} · ${formatBytes(part.bytes)}`} />)}
    {left > 0 && <span className={`usage-seg progress-fill ${fillClass} ${parts.length ? 'usage-other' : ''}`} tabIndex={parts.length ? 0 : -1} style={{ width: `${left}%` }}
      data-tip={parts.length ? `Other programs · ${formatBytes(otherBytes)}` : undefined} aria-label={parts.length ? `Other programs: ${formatBytes(otherBytes)}` : undefined} />}
    {preview && used != null && (() => {
      const room = 100 - usedPercent
      const width = Math.min(room, percent(preview.bytes))
      const tip = `${preview.label} if started · needs ${formatBytes(preview.bytes)}${preview.fits === false ? ' · won’t fit' : ''}`
      return <span className={`usage-seg usage-preview ${preview.fits === false ? 'usage-preview-short' : ''} ${width < percent(preview.bytes) ? 'usage-preview-clipped' : ''}`} tabIndex={0}
        style={{ width: `${Math.max(width, 1)}%`, color: preview.color }} data-tip={tip} aria-label={tip} />
    })()}
  </div>
}

export function ResourceCard({ title, icon, iconClass, memory, age, isCurrent, error, kind, stale, segments, preview }: {
  title: string; icon: ReactNode; iconClass: string; memory?: Memory | null
  age: number | null; isCurrent: boolean; error?: string; kind: string; stale: boolean; segments?: Segment[]; preview?: Preview
}) {
  const known = !!memory && isCurrent
  const used = known ? memory.used_bytes : null
  const total = known ? memory.total_bytes : null
  const available = known ? memory.available_bytes : null
  const percent = total && used != null ? Math.min(100, Math.max(0, used / total * 100)) : 0
  return <article className={`resource-card ${stale && known ? 'resource-stale' : ''}`}>
    <div className="resource-card-top"><div className="resource-title"><span className={`resource-icon ${iconClass}`}>{icon}</span><div><h3>{title}</h3><span>{kind === 'RAM' ? 'Physical RAM' : 'NVIDIA · NVML'}</span></div></div><span className="icon-help" title={`${title} measurements are supplied by host telemetry.`} aria-label={`${title} information`}><CircleHelp size={16} /></span></div>
    <div className="resource-value-row"><strong>{formatBytes(used)}</strong><span>of {formatBytes(total)}</span></div>
    <UsageBar label={title} used={used} total={total} fillClass={iconClass} segments={known ? segments : []} preview={known ? preview : undefined} />
    <div className="resource-stats"><span><span className="stats-dot used-dot" />Used <b>{known ? `${percent.toFixed(0)}%` : '—'}</b></span><span><span className="stats-dot available-dot" />Available <b>{formatBytes(available)}</b></span></div>
    <div className="resource-card-bottom">{error ? <span className="resource-error"><AlertCircle size={13} />{error}</span> : known ? <span className={stale ? 'stale-copy' : 'sample-copy'}>{stale ? 'Last known measurement' : humanAge(age)}</span> : <span className="sample-copy">{isCurrent ? 'Waiting for a valid sample' : 'Connect to view measurements'}</span>}<span className="capacity-label">{stale && known ? 'STALE' : known ? 'MEASURED' : 'NO DATA'}</span></div>
  </article>
}

export function GpuCard({ host, age, stale, isCurrent, runtimes, previews }: { host?: Host; age: number | null; stale: boolean; isCurrent: boolean; runtimes?: Runtime[] | null; previews?: Record<string, Preview> }) {
  const gpus = host?.gpus ?? []
  const availableDevices = gpus.filter((gpu) => gpu.memory !== null).length
  if (!isCurrent || !host) return <ResourceCard title="Graphics memory" icon={<Cpu size={17} />} iconClass="icon-blue" memory={null} age={age} isCurrent={false} kind="VRAM" stale={stale} />
  if (gpus.length === 0) return <article className="resource-card"><div className="resource-card-top"><div className="resource-title"><span className="resource-icon icon-blue"><Cpu size={17} /></span><div><h3>Graphics memory</h3><span>GPU telemetry</span></div></div><span className="icon-help" title="VRAM is measured with NVIDIA NVML." aria-label="Graphics memory information"><CircleHelp size={16} /></span></div><div className="gpu-unavailable"><div className="gpu-empty-icon"><Cpu size={20} /></div><strong>GPU memory unavailable</strong><p>{host.gpu_error ?? 'No GPU devices have been reported by the host.'}</p></div><div className="resource-card-bottom"><span className="sample-copy">{humanAge(age)}</span><span className="capacity-label">NO DATA</span></div></article>
  const capacityState = stale ? 'STALE' : availableDevices === 0 ? 'NO DATA' : availableDevices < gpus.length || host.gpu_error ? 'PARTIAL' : 'MEASURED'
  return <article className={`resource-card gpu-card ${stale ? 'resource-stale' : ''}`}><div className="resource-card-top"><div className="resource-title"><span className="resource-icon icon-blue"><Cpu size={17} /></span><div><h3>Graphics memory</h3><span>{gpus.length} physical GPU{gpus.length === 1 ? '' : 's'}</span></div></div><span className="icon-help" title="VRAM is measured with NVIDIA NVML." aria-label="Graphics memory information"><CircleHelp size={16} /></span></div><div className="gpu-list">{gpus.map((gpu, i) => <div className="gpu-item" key={gpu.id}><div className="gpu-name"><strong>{gpu.name}</strong><span>DEVICE {String(i + 1).padStart(2, '0')}</span></div>{gpu.memory ? <><div className="resource-value-row gpu-value"><strong>{formatBytes(gpu.memory.used_bytes)}</strong><span>of {formatBytes(gpu.memory.total_bytes)}</span></div><UsageBar label={gpu.name} used={gpu.memory.used_bytes} total={gpu.memory.total_bytes} fillClass="icon-blue" segments={gpuSegments(host, runtimes, gpu.id)} preview={previews?.[gpu.id]} /><div className="resource-stats"><span><span className="stats-dot used-dot" />Used <b>{(gpu.memory.used_bytes / gpu.memory.total_bytes * 100).toFixed(0)}%</b></span><span><span className="stats-dot available-dot" />Available <b>{formatBytes(gpu.memory.available_bytes)}</b></span></div></> : <div className="gpu-error"><AlertCircle size={14} />{gpu.error ?? host.gpu_error ?? 'VRAM accounting unavailable for this device.'}</div>}</div>)}</div><div className="resource-card-bottom"><span className={stale ? 'stale-copy' : 'sample-copy'}>{stale ? 'Last known measurement' : humanAge(age)}{host.gpu_error ? ` · ${host.gpu_error}` : ''}</span><span className="capacity-label">{capacityState}</span></div></article>
}

