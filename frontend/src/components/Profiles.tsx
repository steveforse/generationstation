import { useState } from 'react'
import { Activity, AlertCircle, ArrowUpRight, CircleHelp, Cpu, Database, Plus, X } from 'lucide-react'
import { formatBytes } from '../api'
import type { Host, Model, ModelProfile, Operation, Refusal } from '../types'
import { RefusalDetails } from './Refusal'

export function ProfileManager({ profiles, models, host, fresh, catalogError, actionError, operations, pendingModelId, refusals, onRegister, onLifecycle }: {
  profiles: ModelProfile[] | null; models: Model[] | null; host?: Host; fresh: boolean; catalogError: string; actionError: string
  operations: Operation[]; pendingModelId: string | null; refusals: Record<string, Refusal>
  onRegister: (profile: { id: string; name: string; workload: string; ram_peak_bytes: number; gpu_vram_bytes_by_id: Record<string, number>; mode: 'simulation' }) => Promise<boolean>
  onLifecycle: (model: Model, action: 'load' | 'unload', profile: ModelProfile) => Promise<void>
}) {
  const [formOpen, setFormOpen] = useState(false)
  const [modelId, setModelId] = useState('')
  const [name, setName] = useState('')
  const [workload, setWorkload] = useState('')
  const [ramGib, setRamGib] = useState('')
  const [gpuNeeds, setGpuNeeds] = useState<Array<{ deviceId: string; gib: string }>>([])
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState('')
  const gpus = host?.gpus ?? []
  const canRegister = fresh && !!host
  const gigabyte = 1024 ** 3
  const ramBytes = Number(ramGib) * gigabyte
  const gpuMap: Record<string, number> = {}
  let validGpuRows = true
  for (const requirement of gpuNeeds) {
    const bytes = Number(requirement.gib) * gigabyte
    if (!requirement.deviceId || !Number.isSafeInteger(Math.round(bytes)) || bytes <= 0 || gpuMap[requirement.deviceId]) validGpuRows = false
    if (requirement.deviceId && Number.isSafeInteger(Math.round(bytes)) && bytes > 0) gpuMap[requirement.deviceId] = Math.round(bytes)
  }
  const formValid = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(modelId.trim())
    && name.trim().length > 0 && name.trim().length <= 200 && workload.trim().length > 0 && workload.trim().length <= 40
    && Number.isSafeInteger(Math.round(ramBytes)) && ramBytes > 0 && validGpuRows
    && gpuNeeds.every((need) => need.deviceId && gpus.some((gpu) => gpu.id === need.deviceId))

  const resetForm = () => { setModelId(''); setName(''); setWorkload(''); setRamGib(''); setGpuNeeds([]); setFormError('') }
  const addGpuNeed = () => {
    const selected = new Set(gpuNeeds.map((need) => need.deviceId))
    const first = gpus.find((gpu) => !selected.has(gpu.id))
    if (first) setGpuNeeds((items) => [...items, { deviceId: first.id, gib: '' }])
  }
  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setFormError('')
    if (!canRegister) { setFormError('Connect to a host with a fresh telemetry sample before registering a profile.'); return }
    if (!formValid) { setFormError('Enter a valid profile ID, model name, workload, and positive memory requirements for reported devices.'); return }
    setSubmitting(true)
    const ok = await onRegister({ id: modelId.trim(), name: name.trim(), workload: workload.trim(), ram_peak_bytes: Math.round(ramBytes), gpu_vram_bytes_by_id: gpuMap, mode: 'simulation' })
    setSubmitting(false)
    if (ok) { resetForm(); setFormOpen(false) }
  }

  const operatingHost = fresh && host?.loading_enabled === true && host.host.role === 'desktop' && host.host.scope === 'host' && host.ram !== null
  const stateLabel = (state: string) => ({ unloaded: 'Unloaded', checking: 'Checking capacity', loading: 'Loading simulation worker', simulation_ready: 'Simulation ready', unloading: 'Unloading simulation worker', error: 'Worker error', unavailable: 'Unavailable' }[state] ?? state.replaceAll('_', ' '))

  return <section id="models" className="models-section" aria-labelledby="profile-heading">
    <div className="section-heading model-heading"><div><h2 id="profile-heading">Model profiles</h2><p>Register memory requirements, then exercise capacity checks</p></div><button className="button button-primary" onClick={() => { setFormOpen(!formOpen); setFormError('') }} disabled={!canRegister} title={!canRegister ? 'A fresh connected host sample is needed to bind exact GPU IDs.' : undefined}><Plus size={15} /> Register profile</button></div>
    <div className="simulation-notice"><span className="simulation-badge">SIMULATION WORKER</span><strong>No inference</strong><span>This M2 worker tests admission and lifecycle only. It does not read model weights, run commands, or generate output.</span></div>
    {!fresh && <div className="profile-gate"><AlertCircle size={16} /><span>Connect to a host with fresh telemetry before registering a profile or using Load/Unload.</span></div>}
    {catalogError && <div className="inline-alert"><AlertCircle size={17} /><span>{catalogError}</span></div>}
    {actionError && <div className="inline-alert"><AlertCircle size={17} /><span>{actionError}</span></div>}
    {formOpen && <form className="profile-form" onSubmit={submit} aria-label="Register simulation model profile">
      <div className="profile-form-heading"><div><strong>New simulation profile</strong><small>Memory values are explicit peak requirements. They are not inferred from model files.</small></div><span className="simulation-badge">SIMULATION ONLY</span></div>
      <div className="profile-form-grid">
        <label className="field"><span>PROFILE ID</span><input className="text-input" required minLength={1} maxLength={64} pattern="[A-Za-z0-9][A-Za-z0-9._-]{0,63}" value={modelId} onChange={(event) => setModelId(event.target.value)} placeholder="my-model-profile" /><small>Letters, numbers, dot, underscore, and hyphen.</small></label>
        <label className="field"><span>MODEL NAME</span><input className="text-input" required maxLength={200} value={name} onChange={(event) => setName(event.target.value)} placeholder="A label you choose" /></label>
        <label className="field"><span>WORKLOAD</span><input className="text-input" required maxLength={40} value={workload} onChange={(event) => setWorkload(event.target.value)} placeholder="Your workload label" /><small>Free text. No model or runtime is assumed.</small></label>
        <label className="field"><span>PEAK SYSTEM RAM (GiB)</span><input className="text-input" type="number" required min="0.000001" step="any" value={ramGib} onChange={(event) => setRamGib(event.target.value)} placeholder="For example, 12" /><small>{ramBytes > 0 && Number.isSafeInteger(Math.round(ramBytes)) ? `${Math.round(ramBytes).toLocaleString()} bytes (GiB × 1,073,741,824)` : 'Enter a positive RAM requirement.'}</small></label>
      </div>
      <div className="gpu-requirements-head"><div><strong>Per-device VRAM requirements</strong><small>Select the UUID reported by this connected host for each GPU requirement.</small></div><button className="button button-secondary" type="button" onClick={addGpuNeed} disabled={!gpus.length || gpuNeeds.length >= gpus.length}>Add GPU requirement</button></div>
      {gpuNeeds.length === 0 && <p className="gpu-form-empty">No GPU requirement added. Use this only if the simulation profile does not need VRAM.</p>}
      <div className="gpu-requirements">{gpuNeeds.map((need, index) => {
        const usedElsewhere = new Set(gpuNeeds.filter((_, other) => other !== index).map((item) => item.deviceId))
        return <div className="gpu-requirement-row" key={index}>
          <label className="field"><span>GPU DEVICE {index + 1}</span><select className="text-input" aria-label={`GPU device ${index + 1}`} required value={need.deviceId} onChange={(event) => setGpuNeeds((items) => items.map((item, row) => row === index ? { ...item, deviceId: event.target.value } : item))}><option value="">Choose a reported GPU</option>{gpus.filter((gpu) => !usedElsewhere.has(gpu.id)).map((gpu) => <option key={gpu.id} value={gpu.id}>{gpu.name} · {gpu.id}</option>)}</select></label>
          <label className="field"><span>PEAK VRAM (GiB)</span><input className="text-input" type="number" required min="0.000001" step="any" aria-label={`Peak VRAM GiB for GPU ${index + 1}`} value={need.gib} onChange={(event) => setGpuNeeds((items) => items.map((item, row) => row === index ? { ...item, gib: event.target.value } : item))} placeholder="For example, 8" /><small>{Number(need.gib) > 0 && Number.isSafeInteger(Math.round(Number(need.gib) * gigabyte)) ? `${Math.round(Number(need.gib) * gigabyte).toLocaleString()} bytes` : 'Enter a positive VRAM requirement.'}</small></label>
          <button className="remove-requirement" type="button" aria-label={`Remove GPU requirement ${index + 1}`} onClick={() => setGpuNeeds((items) => items.filter((_, row) => row !== index))}><X size={16} /></button>
        </div>
      })}</div>
      {formError && <div className="form-error" role="alert"><AlertCircle size={15} />{formError}</div>}
      <div className="profile-form-actions"><span>Server admission checks remain authoritative for every load.</span><div><button className="button button-secondary" type="button" onClick={() => { resetForm(); setFormOpen(false) }}>Cancel</button><button className="button button-primary" type="submit" disabled={!formValid || !canRegister || submitting}>{submitting ? 'Registering…' : 'Register simulation profile'}</button></div></div>
    </form>}
    {profiles === null && !catalogError ? <div className="empty-models"><div className="empty-illustration"><Database size={22} /></div><div><strong>Profile catalog is waiting</strong><p>Connect to a host to read its registered profiles from the server.</p></div></div> : profiles?.length === 0 ? <div className="empty-models"><div className="empty-illustration"><Database size={22} /></div><div><strong>No registered profiles</strong><p>Register an explicit memory profile to try the test worker.</p></div><div className="empty-status">EMPTY CATALOG</div></div> : <div className="profile-list">{(profiles ?? []).map((profile) => {
      const model = models?.find((item) => item.id === profile.model_id)
      const requiredGpuIds = Object.keys(profile.gpu_vram_bytes_by_id)
      const missingGpu = requiredGpuIds.find((id) => !gpus.some((gpu) => gpu.id === id))
      const selectedGpusValid = requiredGpuIds.every((id) => {
        const gpu = gpus.find((item) => item.id === id)
        return !!gpu?.memory && !gpu.error
      })
      const canLoad = !!operatingHost && !!host?.ram && !!model?.loading_enabled && selectedGpusValid && ['unloaded', 'error'].includes(model.state) && pendingModelId !== model.id
      const canUnload = !!operatingHost && model?.state === 'simulation_ready' && pendingModelId !== model.id
      const disabledReason = !fresh ? 'A fresh telemetry sample is required.'
        : !host?.loading_enabled ? host?.loading_reason ?? 'The host has not confirmed lifecycle eligibility.'
        : !operatingHost ? 'Lifecycle testing requires a desktop host measured directly in host scope.'
          : !host?.ram ? 'System RAM telemetry is unavailable.'
        : ['unloaded', 'error'].includes(model?.state ?? '') && missingGpu ? `Required GPU UUID is not present: ${missingGpu}`
          : ['unloaded', 'error'].includes(model?.state ?? '') && !selectedGpusValid ? 'Required GPU memory telemetry is unavailable.'
                : model?.loading_reason ?? `Action unavailable while state is ${model?.state ?? 'unknown'}.`
      return <article className="profile-card" key={profile.model_id}>
        <div className="profile-card-main"><div className="model-icon"><Cpu size={18} /></div><div className="profile-card-title"><div><strong>{profile.name}</strong><span className="profile-id">{profile.model_id} · {profile.workload}</span></div><span className={`model-state state-${model?.state ?? 'unknown'}`}>{pendingModelId === model?.id ? 'Working…' : stateLabel(model?.state ?? 'unknown')}</span></div></div>
        <div className="profile-data-grid"><div><span>PEAK SYSTEM RAM</span><strong>{formatBytes(profile.ram_peak_bytes)}</strong></div><div><span>GPU MEMORY TARGETS</span><strong>{requiredGpuIds.length || 'None'}</strong></div><div><span>EXECUTION</span><strong className="sim-execution">Fake worker · no inference</strong></div></div>
        {requiredGpuIds.length > 0 && <div className="profile-gpu-list">{requiredGpuIds.map((id) => { const gpu = gpus.find((item) => item.id === id); return <div key={id}><span>{gpu?.name ?? 'Unreported GPU'}</span><code>{id}</code><strong>{formatBytes(profile.gpu_vram_bytes_by_id[id])}</strong></div> })}</div>}
        {!model && <p className="profile-warning">The host profile exists, but its model lifecycle state is not in the model catalog.</p>}
        {refusals[profile.model_id] && <RefusalDetails refusal={refusals[profile.model_id]} />}
        <div className="profile-card-footer"><span className="worker-caption"><span className="simulation-badge">SIMULATION</span> No model weights or outputs are used.</span>{model && <div className="profile-actions">{['unloaded', 'error'].includes(model.state) ? <button className="button button-primary" disabled={!canLoad} title={!canLoad ? disabledReason : 'Server checks capacity before starting the fake worker.'} onClick={() => void onLifecycle(model, 'load', profile)}><ArrowUpRight size={14} />{model.state === 'error' ? 'Retry simulation' : 'Load simulation'}</button> : model.state === 'simulation_ready' ? <button className="button button-secondary" disabled={!canUnload} title={!canUnload ? disabledReason : 'Stop the fake worker.'} onClick={() => void onLifecycle(model, 'unload', profile)}><X size={14} />Unload simulation</button> : <button className="button button-secondary" disabled title={disabledReason}>{stateLabel(model.state)}</button>}</div>}</div>
      </article>
    })}</div>}
    <div className="model-footnote"><CircleHelp size={14} /><span>Load requests are checked again by the host. Browser state is never the capacity authority.</span></div>
    {operations.length > 0 && <section className="operations-section" aria-labelledby="operations-heading"><div className="section-heading"><div><h3 id="operations-heading">Recent worker operations</h3><p>Status is polled from the host; no progress percentage is invented.</p></div></div><div className="operation-list">{operations.map((operation) => <div className="operation-row" key={operation.id}><span className={`operation-mark op-${operation.status}`}><Activity size={15} /></span><div className="operation-copy"><strong>{operation.simulation ? (operation.action === 'load' ? 'Load simulation' : 'Unload simulation') : (operation.action === 'load' ? 'Start' : 'Stop')} · {operation.status.replaceAll('_', ' ')}</strong><small>{operation.model_id} · operation {operation.id}</small>{operation.error_message && <small className="operation-error">{operation.error_code ? `${operation.error_code}: ` : ''}{operation.error_message}</small>}</div><span className="simulation-badge">{operation.simulation ? 'NO INFERENCE' : 'MODEL SERVER'}</span></div>)}</div></section>}
  </section>
}

