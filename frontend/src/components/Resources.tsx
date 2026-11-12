import type { ReactNode } from 'react'
import { AlertCircle, CircleHelp, Cpu } from 'lucide-react'
import { formatBytes, humanAge } from '../api'
import type { Host, Memory } from '../types'

export function ResourceCard({ title, icon, iconClass, memory, age, isCurrent, error, kind, stale }: {
  title: string; icon: ReactNode; iconClass: string; memory?: Memory | null
  age: number | null; isCurrent: boolean; error?: string; kind: string; stale: boolean
}) {
  const known = !!memory && isCurrent
  const used = known ? memory.used_bytes : null
  const total = known ? memory.total_bytes : null
  const available = known ? memory.available_bytes : null
  const percent = total && used != null ? Math.min(100, Math.max(0, used / total * 100)) : 0
  return <article className={`resource-card ${stale && known ? 'resource-stale' : ''}`}>
    <div className="resource-card-top"><div className="resource-title"><span className={`resource-icon ${iconClass}`}>{icon}</span><div><h3>{title}</h3><span>{kind === 'RAM' ? 'Physical RAM' : 'NVIDIA · NVML'}</span></div></div><span className="icon-help" title={`${title} measurements are supplied by host telemetry.`} aria-label={`${title} information`}><CircleHelp size={16} /></span></div>
    <div className="resource-value-row"><strong>{formatBytes(used)}</strong><span>of {formatBytes(total)}</span></div>
    <div className="progress-track" role="progressbar" aria-label={`${title} used`} aria-valuenow={known ? Math.round(percent) : undefined} aria-valuemin={0} aria-valuemax={100}><div className={`progress-fill ${iconClass}`} style={{ width: `${percent}%` }} /></div>
    <div className="resource-stats"><span><span className="stats-dot used-dot" />Used <b>{known ? `${percent.toFixed(0)}%` : '—'}</b></span><span><span className="stats-dot available-dot" />Available <b>{formatBytes(available)}</b></span></div>
    <div className="resource-card-bottom">{error ? <span className="resource-error"><AlertCircle size={13} />{error}</span> : known ? <span className={stale ? 'stale-copy' : 'sample-copy'}>{stale ? 'Last known measurement' : humanAge(age)}</span> : <span className="sample-copy">{isCurrent ? 'Waiting for a valid sample' : 'Connect to view measurements'}</span>}<span className="capacity-label">{stale && known ? 'STALE' : known ? 'MEASURED' : 'NO DATA'}</span></div>
  </article>
}

export function GpuCard({ host, age, stale, isCurrent }: { host?: Host; age: number | null; stale: boolean; isCurrent: boolean }) {
  const gpus = host?.gpus ?? []
  const availableDevices = gpus.filter((gpu) => gpu.memory !== null).length
  if (!isCurrent || !host) return <ResourceCard title="Graphics memory" icon={<Cpu size={17} />} iconClass="icon-blue" memory={null} age={age} isCurrent={false} kind="VRAM" stale={stale} />
  if (gpus.length === 0) return <article className="resource-card"><div className="resource-card-top"><div className="resource-title"><span className="resource-icon icon-blue"><Cpu size={17} /></span><div><h3>Graphics memory</h3><span>GPU telemetry</span></div></div><span className="icon-help" title="VRAM is measured with NVIDIA NVML." aria-label="Graphics memory information"><CircleHelp size={16} /></span></div><div className="gpu-unavailable"><div className="gpu-empty-icon"><Cpu size={20} /></div><strong>GPU memory unavailable</strong><p>{host.gpu_error ?? 'No GPU devices have been reported by the host.'}</p></div><div className="resource-card-bottom"><span className="sample-copy">{humanAge(age)}</span><span className="capacity-label">NO DATA</span></div></article>
  const capacityState = stale ? 'STALE' : availableDevices === 0 ? 'NO DATA' : availableDevices < gpus.length || host.gpu_error ? 'PARTIAL' : 'MEASURED'
  return <article className={`resource-card gpu-card ${stale ? 'resource-stale' : ''}`}><div className="resource-card-top"><div className="resource-title"><span className="resource-icon icon-blue"><Cpu size={17} /></span><div><h3>Graphics memory</h3><span>{gpus.length} physical GPU{gpus.length === 1 ? '' : 's'}</span></div></div><span className="icon-help" title="VRAM is measured with NVIDIA NVML." aria-label="Graphics memory information"><CircleHelp size={16} /></span></div><div className="gpu-list">{gpus.map((gpu, i) => <div className="gpu-item" key={gpu.id}><div className="gpu-name"><strong>{gpu.name}</strong><span>DEVICE {String(i + 1).padStart(2, '0')}</span></div>{gpu.memory ? <><div className="resource-value-row gpu-value"><strong>{formatBytes(gpu.memory.used_bytes)}</strong><span>of {formatBytes(gpu.memory.total_bytes)}</span></div><div className="progress-track" role="progressbar" aria-label={`${gpu.name} used`} aria-valuenow={Math.round(gpu.memory.used_bytes / gpu.memory.total_bytes * 100)} aria-valuemin={0} aria-valuemax={100}><div className="progress-fill icon-blue" style={{ width: `${Math.min(100, gpu.memory.used_bytes / gpu.memory.total_bytes * 100)}%` }} /></div><div className="resource-stats"><span><span className="stats-dot used-dot" />Used <b>{(gpu.memory.used_bytes / gpu.memory.total_bytes * 100).toFixed(0)}%</b></span><span><span className="stats-dot available-dot" />Available <b>{formatBytes(gpu.memory.available_bytes)}</b></span></div></> : <div className="gpu-error"><AlertCircle size={14} />{gpu.error ?? host.gpu_error ?? 'VRAM accounting unavailable for this device.'}</div>}</div>)}</div><div className="resource-card-bottom"><span className={stale ? 'stale-copy' : 'sample-copy'}>{stale ? 'Last known measurement' : humanAge(age)}{host.gpu_error ? ` · ${host.gpu_error}` : ''}</span><span className="capacity-label">{capacityState}</span></div></article>
}

