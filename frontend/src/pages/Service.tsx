import { useState } from 'react'
import { Activity, ArrowUpRight, ChevronDown, MemoryStick } from 'lucide-react'
import { StatePill } from '../components/StatePill'
import { groupByWorkload } from '../components/WorkloadIcon'
import { ConnectionBanner, hostName, stateText } from '../components/HostBits'
import { estimateFit, GpuCard, modelColor, modelUsage, type Preview, ramSegments, ResourceCard } from '../components/Resources'
import { fieldsFor, type FormStart, GenerateForm, JobDetail, JobModal, jobTitle, ResultsRail, RuntimeCard } from '../components/Runtime'
import type { FileItem } from '../components/FilePicker'
import type { SavedHost } from '../hosts'
import { handOff, soundtrackToWav, spokenLine, takeHandOff, voiceTargets } from '../voiceSample'
import { href } from '../routes'
import { type HostStore, useHostView, useSession } from '../store'
import type { JobFile, Operation, Runtime, RuntimeEstimate } from '../types'

function Missing({ title, text }: { title: string; text: string }) {
  return <div className="empty-models"><div><strong>{title}</strong><p>{text}</p></div><a className="button button-secondary" href={href({ page: 'overview' })}>Back to Overview</a></div>
}

function OperationHistory({ id, operations, title, text, empty }: { id: string; operations: Operation[]; title: string; text: string; empty?: string }) {
  if (operations.length === 0 && !empty) return null
  const list = operations.length === 0 ? <p className="operation-empty">{empty}</p> : <OperationList operations={operations} />
  // A short history stays folded away so an empty or near-empty list does not take half the card.
  if (operations.length <= 2) return <details className="operations-section disclosure history-disclosure" aria-labelledby={id}>
    <summary><ChevronDown size={16} aria-hidden="true" className="disclosure-chevron" /><span id={id}>{title} ({operations.length})</span></summary><p className="history-text">{text}</p>{list}</details>
  return <section className="operations-section" aria-labelledby={id}><div className="section-heading"><div><h3 id={id}>{title} ({operations.length})</h3><p>{text}</p></div></div>{list}</section>
}

function OperationList({ operations }: { operations: Operation[] }) {
  return <div className="operation-list">{operations.map((operation) => <div className="operation-row" key={operation.id}><span className={`operation-mark op-${operation.status}`}><Activity size={16} /></span><div className="operation-copy"><strong>{operation.action === 'load' ? 'Start' : 'Stop'} · {operation.status.replaceAll('_', ' ')}</strong><small>operation {operation.id}</small>{operation.error_message && <small className="operation-error">{operation.error_code ? `${operation.error_code}: ` : ''}{operation.error_message}</small>}</div><span className="simulation-badge">Model server</span></div>)}</div>
}

/** Loading and unloading: every model server on the host, with its model, GPU and advanced settings. */
export function ModelsPage({ store, host }: { store: HostStore; host?: SavedHost }) {
  const session = host ? store.session(host.id) : undefined
  const state = useSession(session)
  const view = useHostView(state)
  const [estimates, setEstimates] = useState<Record<string, RuntimeEstimate | null>>({})
  const [focusId, setFocusId] = useState<string | null>(null)
  if (!host || !session) return <Missing title="Host not found" text="This host is no longer saved on this device." />
  // The sidebar's order: text models first, then speech, pictures, video and music.
  const runtimes = groupByWorkload(state.runtimes ?? [], (runtime) => runtime.workload).flatMap((group) => group.items)
  // Preview the model being worked on: the card last hovered or focused, else the first with an estimate.
  const previewId = focusId && estimates[focusId] ? focusId : runtimes.find((runtime) => estimates[runtime.id])?.id
  const previewEstimate = previewId ? estimates[previewId] : null
  const previewName = runtimes.find((runtime) => runtime.id === previewId)?.name ?? ''
  const previewFits = previewEstimate ? estimateFit(view.host, previewEstimate, view.fresh) : []
  const preview = (key: string, bytes: number): Preview => ({ label: previewName, bytes, color: modelColor(state.runtimes, previewId ?? ''), fits: previewFits.find((fit) => fit.key === key)?.fits ?? null })
  const ramPreview = previewEstimate ? preview('ram', previewEstimate.ram_bytes) : undefined
  const gpuPreviews = Object.fromEntries(Object.entries(previewEstimate?.gpu_vram_bytes_by_id ?? {}).map(([id, bytes]) => [id, preview(id, bytes)]))
  return <>
    <section className="page-heading"><div><div className="eyebrow"><span className="eyebrow-dot" /> {hostName(host, state)}</div><h1>Models</h1><p>Start and stop the model servers on {hostName(host, state)}. Each one holds RAM and VRAM while it runs.</p></div></section>
    {state.connection !== 'connected' && <div className="overview-connect"><ConnectionBanner state={state} /><a className="button button-primary" href={href({ page: 'connections' })}>Open Connections <ArrowUpRight size={16} /></a></div>}
    <div className="models-layout"><div className="models-main">
    {state.runtimes && runtimes.length === 0 && <div className="empty-models"><div><strong>No model servers</strong><p>This host does not list any model servers.</p></div></div>}
    {runtimes.map((runtime) => {
      const model = state.models?.find((item) => item.id === runtime.id)
      return <section className="model-server" key={runtime.id} aria-label={runtime.name} onMouseEnter={() => setFocusId(runtime.id)} onFocus={() => setFocusId(runtime.id)}>
        <RuntimeCard key={`${host.id}:${runtime.id}`} runtime={runtime} model={model} host={view.host} fresh={view.fresh} pending={state.pendingModelId === runtime.id}
          refusal={state.refusals[runtime.id]} message={state.runtimeMessages[runtime.id]} onRun={(r, action, launch) => session.runRuntime(r, action, launch)}
          openHref={runtime.generation ? href({ page: 'service', hostId: host.id, modelId: runtime.id }) : undefined}
          usage={modelUsage(view.host, runtime.id)} color={modelColor(state.runtimes, runtime.id)}
          estimate={(r, launch, signal) => session.estimateRuntime(r, launch, signal)}
          onEstimate={(estimate) => setEstimates((current) => current[runtime.id] === estimate ? current : { ...current, [runtime.id]: estimate })}
          aside={<OperationHistory id={`history-${runtime.id}`} operations={state.operations.filter((operation) => operation.model_id === runtime.id && !operation.simulation)} title="History" text="Starts and stops of this model server." empty="No starts or stops yet." />} />
      </section>
    })}
    </div>
    {!!state.snapshot && state.connection !== 'idle' && <aside className="models-rail"><section className="resource-grid models-resources" aria-label={`${hostName(host, state)} resource usage`}>
      <ResourceCard title="System memory" icon={<MemoryStick size={20} />} iconClass="icon-violet" memory={view.host?.ram} age={view.age} isCurrent error={view.host?.ram_error ?? undefined} kind="RAM" stale={view.stale} segments={ramSegments(view.host, state.runtimes)} preview={ramPreview} legend />
      <GpuCard host={view.host} age={view.age} stale={view.stale} isCurrent runtimes={state.runtimes} previews={gpuPreviews} legend />
    </section></aside>}
    </div>
  </>
}

/** Generation: the plugin's form and the results. Starting and stopping happen on the Models page. */
export function ServicePage({ store, host, modelId }: { store: HostStore; host?: SavedHost; modelId: string }) {
  const session = host ? store.session(host.id) : undefined
  const state = useSession(session)
  // The result open in the modal, picked in the sidebar.
  const [selectedId, setSelectedId] = useState<string | null>(null)
  // "Use these settings" refills the form by remounting it with that result's inputs.
  // A voice sample sent from another model's result arrives as this page's first form start.
  const [reuse, setReuse] = useState<{ n: number; start?: FormStart }>(() => ({ n: 0, start: host ? takeHandOff(host.id, modelId) : undefined }))
  if (!host || !session) return <Missing title="Host not found" text="This host is no longer saved on this device." />
  const runtime = state.runtimes?.find((item) => item.id === modelId)
  const model = state.models?.find((item) => item.id === modelId)
  const modelsHref = href({ page: 'models', hostId: host.id })
  const jobs = state.jobs.filter((job) => job.model_id === modelId)
  const selected = jobs.find((job) => job.id === selectedId)
  const modelState = model?.state ?? 'unknown'
  const ready = modelState === 'ready'
  const status = ready ? `Running on ${runtime ? gpuNames(runtime) : 'this host'}.`
    : ['loading', 'unloading'].includes(modelState) ? `${stateText[modelState]}. This can take several minutes.`
      : `${runtime?.name ?? modelId} is not running. Start it on the Models page first.`
  return <>
    <section className="page-heading"><div><div className="eyebrow"><span className="eyebrow-dot" /> {hostName(host, state)}</div><h1>{runtime?.name ?? modelId}</h1><p>{runtime ? runtime.description || `${runtime.workload} · runs on ${hostName(host, state)}` : 'Waiting for this host’s model list.'}</p></div></section>
    {state.connection !== 'connected' && <div className="overview-connect"><ConnectionBanner state={state} /><a className="button button-primary" href={href({ page: 'connections' })}>Open Connections <ArrowUpRight size={16} /></a></div>}
    {runtime && !runtime.generation && <Missing title="Nothing to make here" text={`${runtime.name} is started and stopped on the Models page.`} />}
    {runtime?.generation && <div className="service-layout"><div className="service-main"><article className="profile-card service-panel">
      <div className="service-status" aria-live="polite"><StatePill state={modelState}>{stateText[modelState] ?? 'Unknown'}</StatePill><span>{status}</span><a className="text-button" href={modelsHref}>{ready ? 'Model settings' : 'Go to Models'} <ArrowUpRight size={16} /></a></div>
      {ready && <GenerateForm key={reuse.n} runtime={runtime} generation={runtime.generation} initial={reuse.start} error={state.jobErrors[runtime.id]}
        upload={(file) => session.uploadFile(file)}
        ahead={jobs.filter((job) => job.status === 'queued' || job.status === 'running').length}
        onGenerate={(r, inputs) => session.runJob(r, inputs)} />}
    </article>
    </div>
    <ResultsRail jobs={jobs} generation={runtime.generation} selectedId={selected?.id} onSelect={(job) => setSelectedId(job.id)} fileUrl={(job, output) => session.fileUrl(job, output)}
      onCancel={(job) => session.cancelJob(job)} />
    <JobModal open={!!selected} onClose={() => setSelectedId(null)} title={selected ? jobTitle(selected) : ''}>
      {selected && <JobDetail job={selected} runtime={runtime} generation={runtime.generation} fileUrl={(job, output) => session.fileUrl(job, output)}
        inputUrl={(job, name) => session.inputUrl(job, name)}
        onReuse={async (job) => {
          // Pictures and other references go back into the form: fetched from the job and uploaded again.
          const files: Record<string, FileItem[]> = {}
          for (const field of fieldsFor(runtime.generation!, job.inputs.mode).filter((item) => item.kind === 'files')) {
            const entries = Array.isArray(job.inputs[field.key]) ? job.inputs[field.key] as JobFile[] : []
            files[field.key] = await Promise.all(entries.map(async (entry, index) => {
              const item: FileItem = { key: `${job.id}-${index}-${entry.name}`, name: entry.original, kind: entry.kind, url: '', status: 'error', error: 'Could not be added again.' }
              try {
                const blob = await session.inputBlob(job, entry.name)
                const record = await session.uploadFile(new File([blob], entry.original, { type: entry.mime }))
                return { ...item, url: URL.createObjectURL(blob), status: 'ready' as const, id: record.id, error: undefined }
              } catch { return item }
            }))
          }
          setReuse((current) => ({ n: current.n + 1, start: { mode: typeof job.inputs.mode === 'string' ? job.inputs.mode : undefined, inputs: job.inputs, files } }))
          setSelectedId(null); window.scrollTo({ top: 0, behavior: 'smooth' })
        }}
        onDelete={async (job) => { const problem = await session.deleteJob(job); if (!problem) setSelectedId(null); return problem }}
        onCancel={(job) => session.cancelJob(job)}
        voiceTargets={voiceTargets(state.runtimes, state.models).filter((target) => target.runtime.id !== modelId)}
        onUseVoice={async (job, url, target) => {
          try {
            const wav = await soundtrackToWav(await (await fetch(url)).blob())
            const name = `voice-${job.id.slice(0, 8)}.wav`
            const record = await session.uploadFile(new File([wav], name, { type: 'audio/wav' }))
            const sample: FileItem = { key: `voice-${job.id}`, name, kind: 'audio', url: URL.createObjectURL(wav), status: 'ready', id: record.id }
            const line = spokenLine(job.inputs.prompt)
            handOff(host.id, target.runtime.id, { mode: target.mode, inputs: { mode: target.mode, ...(target.textKey && line ? { [target.textKey]: line } : {}) }, files: { [target.sampleKey]: [sample] } })
            window.location.hash = href({ page: 'service', hostId: host.id, modelId: target.runtime.id })
            return ''
          } catch (reason) { return reason instanceof Error ? reason.message : 'The sound could not be taken from this clip.' }
        }} />}
    </JobModal>
    </div>}
    {state.runtimes && !runtime && <Missing title="Service not found" text="This host does not list this service any more." />}
  </>
}

function gpuNames(runtime: Runtime) {
  const launch = runtime.last_launch
  const preset = launch ? runtime.presets[launch.preset] : undefined
  if (!launch || !preset) return 'this host'
  return launch.gpus.map((index) => preset.allowed_gpus.find((gpu) => gpu.index === index)?.name ?? `GPU ${index}`).join(' and ')
}
