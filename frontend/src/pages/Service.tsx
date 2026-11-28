import { useState, type ReactNode } from 'react'
import { Activity, ArrowDown, ArrowUp, ArrowUpRight, ChevronDown, MemoryStick } from 'lucide-react'
import { ConnectLink } from '../components/Connect'
import { StatePill } from '../components/StatePill'
import { groupByWorkload, WorkloadIcon } from '../components/WorkloadIcon'
import { chosenChart, QualityChart, qualityCharts, scoresOn } from '../components/QualityChart'
import { ConnectionBanner, hostName, stateText } from '../components/HostBits'
import { estimateFit, GpuCard, isUnified, modelColor, modelUsage, type Preview, ramSegments, ResourceCard } from '../components/Resources'
import { fieldsFor, type FormHooks, type FormStart, GenerateForm, JobDetail, JobModal, jobTitle, ResultsRail, RuntimeCard } from '../components/Runtime'
import type { FileItem } from '../components/FilePicker'
import type { SavedHost } from '../hosts'
import { lastFrame } from '../videoFrame'
import { soundtrackToWav, takeHandOff } from '../voiceSample'
import { href, modelRoute } from '../routes'
import { type HostStore, useHostView, useSession } from '../store'
import type { Job, JobFile, Operation, ReferenceModel, Runtime, RuntimeEstimate } from '../types'

/** The Models page's licence filter: everything, what is fine for work, or what is personal use only. */
const USE_FILTERS = [['', 'All'], ['work', 'Work use'], ['personal', 'Personal use only']] as const
/** The uses a model's versions allow: a model with several versions counts under each use one of them allows. */
const usesOf = (runtime: Runtime) => new Set(Object.values(runtime.presets).map((preset) => (preset.license ?? runtime.license)?.use))
const usable = (filter: string, runtime: Runtime) => {
  const uses = usesOf(runtime)
  return !filter || (filter === 'work' ? uses.has('work') || uses.has('conditions') : uses.has('personal'))
}

type SortKey = 'name' | 'quality'

/** One section of the Models page: its heading, a sort control, its quality ranking and its cards. Sorting by quality uses the
 * ranking chosen in the chart; models without a score on it come last in either direction. */
function ModelGroup({ id, label, items, references, children }: { id: string; label: string; items: Runtime[]; references: ReferenceModel[]; children: (runtime: Runtime) => React.ReactNode }) {
  const [metric, setMetric] = useState<string | null>(null)
  const [sort, setSort] = useState<SortKey>('name')
  const [descending, setDescending] = useState(false)
  const charts = qualityCharts(items, references)
  const chart = charts.length > 0 ? chosenChart(charts, metric) : null
  const scores = chart ? scoresOn(chart[1]) : new Map<string, number>()
  const key: SortKey = sort === 'quality' && !chart ? 'name' : sort
  const direction = descending ? -1 : 1
  const sorted = [...items].sort((a, b) => {
    if (key === 'name') return direction * a.name.localeCompare(b.name, undefined, { sensitivity: 'base' })
    const x = scores.get(a.id), y = scores.get(b.id)
    if (x === undefined || y === undefined) return x === y ? 0 : x === undefined ? 1 : -1
    return direction * (x - y)
  })
  const choose = (next: SortKey) => { setSort(next); setDescending(next === 'quality') }
  const ascendingWord = key === 'quality' ? 'lowest first' : 'A to Z'
  const descendingWord = key === 'quality' ? 'highest first' : 'Z to A'
  return <section className="models-group" aria-labelledby={`models-group-${id}`}>
    <div className="models-group-bar">
      <h2 className="models-group-heading" id={`models-group-${id}`}><WorkloadIcon workload={id} size={20} /><span>{label}</span><span className="models-group-count">{items.length}</span></h2>
    </div>
    {items.length > 1 && <div className="models-sort">
      <label>Sort <select value={key} onChange={(event) => choose(event.target.value as SortKey)}>
        <option value="default">Default order</option>
        <option value="name">Name</option>
        {chart && <option value="quality">Quality ({chart[0]})</option>}
      </select></label>
      {<button type="button" className="button button-small button-secondary" aria-label={`Order: ${descending ? descendingWord : ascendingWord}. Reverse it`} title="Reverse the order" onClick={() => setDescending(!descending)}>
        {descending ? <ArrowDown size={14} aria-hidden="true" /> : <ArrowUp size={14} aria-hidden="true" />}{descending ? descendingWord : ascendingWord}
      </button>}
    </div>}
    {sorted.map(children)}
    <QualityChart runtimes={items} references={references} metric={metric} onMetric={setMetric} />
  </section>
}

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
  const [useFilter, setUseFilter] = useState('')
  if (!host || !session) return <Missing title="Host not found" text="This host is no longer saved on this device." />
  // The sidebar's order: text models first, then speech, pictures, video and music.
  const allRuntimes = groupByWorkload(state.runtimes ?? [], (runtime) => runtime.workload).flatMap((group) => group.items)
  const runtimes = allRuntimes.filter((runtime) => usable(useFilter, runtime))
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
    {allRuntimes.some((runtime) => runtime.license) && <div className="models-filter" role="group" aria-label="Show models by licence">
      {USE_FILTERS.map(([key, label]) => <button key={key || 'all'} type="button" className={`button button-small ${useFilter === key ? 'button-primary' : 'button-secondary'}`} aria-pressed={useFilter === key} onClick={() => setUseFilter(key)}>{label}</button>)}
      <span className="models-filter-note">Work use includes models with limits to check. A model with several versions shows under each use its versions allow.</span>
    </div>}
    {state.runtimes && allRuntimes.length === 0 && <div className="empty-models"><div><strong>No model servers</strong><p>This host does not list any model servers.</p></div></div>}
    {allRuntimes.length > 0 && runtimes.length === 0 && <div className="empty-models"><div><strong>No models match</strong><p>None of this host's models are marked for that use.</p></div></div>}
    {groupByWorkload(runtimes, (runtime) => runtime.workload).map((group) => <ModelGroup key={group.key} id={group.key} label={group.label} items={group.items} references={state.references.filter((reference) => reference.workload === group.key)}>
      {(runtime: Runtime) => {
      const model = state.models?.find((item) => item.id === runtime.id)
      return <section className="model-server" key={runtime.id} aria-label={runtime.name} onMouseEnter={() => setFocusId(runtime.id)} onFocus={() => setFocusId(runtime.id)}>
        <RuntimeCard key={`${host.id}:${runtime.id}`} runtime={runtime} model={model} host={view.host} fresh={view.fresh} pending={state.pendingModelId === runtime.id}
          refusal={state.refusals[runtime.id]} message={state.runtimeMessages[runtime.id]} onRun={(r, action, launch) => session.runRuntime(r, action, launch)}
          openHref={runtime.generation ? href(modelRoute(host.id, runtime.id, state.runtimes)) : undefined}
          usage={modelUsage(view.host, runtime.id)} color={modelColor(state.runtimes, runtime.id)}
          estimate={(r, launch, signal) => session.estimateRuntime(r, launch, signal)}
          onEstimate={(estimate) => setEstimates((current) => current[runtime.id] === estimate ? current : { ...current, [runtime.id]: estimate })}
          aside={<OperationHistory id={`history-${runtime.id}`} operations={state.operations.filter((operation) => operation.model_id === runtime.id && !operation.simulation)} title="History" text="Starts and stops of this model server." empty="No starts or stops yet." />} />
      </section>
      }}
    </ModelGroup>)}
    </div>
    {!!state.snapshot && state.connection !== 'idle' && <aside className="models-rail"><section className="resource-grid models-resources" aria-label={`${hostName(host, state)} resource usage`}>
      <ResourceCard title="System memory" icon={<MemoryStick size={20} />} iconClass="icon-violet" memory={view.host?.ram} age={view.age} isCurrent error={view.host?.ram_error ?? undefined} kind="RAM" unified={isUnified(view.host)} stale={view.stale} segments={ramSegments(view.host, state.runtimes)} preview={ramPreview} legend />
      <GpuCard host={view.host} age={view.age} stale={view.stale} isCurrent runtimes={state.runtimes} previews={gpuPreviews} legend />
    </section></aside>}
    </div>
  </>
}

/** One page for every decision model, like Chat is for text models: the model answering is picked from those running. */
export function DecidePage({ store, host, modelId }: { store: HostStore; host?: SavedHost; modelId?: string }) {
  const state = useSession(host ? store.session(host.id) : undefined)
  const [pickedId, setPickedId] = useState<string | null>(modelId ?? null)
  const decide = (state.runtimes ?? []).filter((runtime) => runtime.workload === 'decision' && runtime.generation)
  const running = decide.filter((runtime) => state.models?.find((model) => model.id === runtime.id)?.state === 'ready')
  const chosen = running.find((runtime) => runtime.id === pickedId) ?? running[0] ?? decide.find((runtime) => runtime.id === pickedId) ?? decide[0]
  const picker = running.length > 1
    ? <label className="decide-picker"><span>Model answering</span>
      <select aria-label="Model answering" value={chosen?.id} onChange={(event) => setPickedId(event.target.value)}>{running.map((runtime) => <option key={runtime.id} value={runtime.id}>{runtime.name}</option>)}</select></label>
    : null
  return <ServicePage store={store} host={host} modelId={chosen?.id ?? ''}
    group={{ title: 'Decide', description: 'Ask a question about a situation and get a probability for each answer, from whichever decision model is running.', ids: decide.map((runtime) => runtime.id), picker, connect: true, none: decide.length > 0 && running.length === 0 }} />
}

/** A page that serves several models as one (Decide, Speech): which models, the control to pick one, and what it adds around the form. */
export type Group = {
  title: string; description: string; ids: string[]; picker: ReactNode; none: boolean; noun?: string; connect?: boolean
  /** The form is remounted when `key` changes; `start` is where it opens; `hooks` let the page follow and change it. */
  form?: { key: string; start?: FormStart; hooks?: FormHooks }
  above?: ReactNode
  /** Which of the group's models' results belong on the page (a model that serves two pages has results for each). */
  keepJob?: (job: Job) => boolean
  /** Called instead of refilling the form when "Use these settings" is chosen on a result from another model of the group. */
  reuseElsewhere?: (job: Job) => void
  /** A voice was added to the library from a result. */
  onVoiceSaved?: () => void
  /** A finished song was chosen as the song to start from (set only while the chosen model can). */
  useSong?: (file: FileItem) => void
  /** The last frame of a finished clip was chosen as the first picture, and a clip as the clip to continue (set only while the chosen model can). */
  useFrame?: (file: FileItem) => void
  useClip?: (file: FileItem) => void
}

/** Generation: the plugin's form and the results. Starting and stopping happen on the Models page. */
export function ServicePage({ store, host, modelId, group }: { store: HostStore; host?: SavedHost; modelId: string; group?: Group }) {
  const session = host ? store.session(host.id) : undefined
  const state = useSession(session)
  // The result open in the modal, picked in the sidebar.
  const [selectedId, setSelectedId] = useState<string | null>(null)
  // "Use these settings" refills the form by remounting it with that result's inputs.
  // A voice sample sent from another model's result arrives as this page's first form start.
  const [reuse, setReuse] = useState<{ n: number; start?: FormStart }>(() => ({ n: 0, start: host && !group ? takeHandOff(host.id, modelId) : undefined }))
  if (!host || !session) return <Missing title="Host not found" text="This host is no longer saved on this device." />
  const runtime = state.runtimes?.find((item) => item.id === modelId)
  const model = state.models?.find((item) => item.id === modelId)
  const modelsHref = href({ page: 'models', hostId: host.id })
  // A model that makes pictures and clips keeps its picture tabs and results on the Images page, and the rest here.
  const imageTabs = !group ? Object.keys(runtime?.generation?.image?.roles ?? {}).filter(Boolean) : []
  const ownHooks: FormHooks | undefined = imageTabs.length ? { showModes: (key) => !imageTabs.includes(key) } : undefined
  const jobs = state.jobs.filter((job) => group ? group.ids.includes(job.model_id) && (group.keepJob?.(job) ?? true)
    : job.model_id === modelId && !imageTabs.includes(String(job.inputs.mode)))
  const selected = jobs.find((job) => job.id === selectedId)
  const modelState = model?.state ?? 'unknown'
  const ready = modelState === 'ready'
  const status = ready ? `${group && runtime ? `${runtime.name} is running` : 'Running'} on ${runtime ? gpuNames(runtime) : 'this host'}.`
    : ['loading', 'unloading'].includes(modelState) ? `${stateText[modelState]}. This can take several minutes.`
      : group ? `No ${group.noun ?? 'decision'} model is running. Start one on the Models page first.` : `${runtime?.name ?? modelId} is not running. Start it on the Models page first.`
  return <>
    <section className="page-heading"><div><div className="eyebrow"><span className="eyebrow-dot" /> {hostName(host, state)}</div><h1>{group?.title ?? runtime?.name ?? modelId}</h1><p>{group ? group.description : runtime ? runtime.description || `${runtime.workload} · runs on ${hostName(host, state)}` : 'Waiting for this host’s model list.'}</p></div></section>
    {state.connection !== 'connected' && <div className="overview-connect"><ConnectionBanner state={state} /><a className="button button-primary" href={href({ page: 'connections' })}>Open Connections <ArrowUpRight size={16} /></a></div>}
    {runtime && !runtime.generation && <Missing title="Nothing to make here" text={`${runtime.name} is started and stopped on the Models page.`} />}
    {runtime?.generation && <div className="service-layout"><div className="service-main"><article className="profile-card service-panel">
      <div className="service-status" aria-live="polite"><StatePill state={modelState}>{stateText[modelState] ?? 'Unknown'}</StatePill><span>{status}</span><a className="text-button" href={modelsHref}>{ready ? 'Model settings' : 'Go to Models'} <ArrowUpRight size={16} /></a></div>
      {group && ready && <div className="decide-bar">{group.connect && <ConnectLink kind="decide" runtime={runtime} host={host} session={session} />}{group.picker}</div>}
      {ready && group?.above}
      {ready && <GenerateForm key={`${group?.form?.key ?? ''}:${reuse.n}`} runtime={runtime} generation={runtime.generation} initial={reuse.n ? reuse.start : reuse.start ?? group?.form?.start} hooks={group?.form?.hooks ?? ownHooks} error={state.jobErrors[runtime.id]}
        upload={(file) => session.uploadFile(file)}
        ahead={jobs.filter((job) => job.status === 'queued' || job.status === 'running').length}
        onGenerate={(r, inputs) => session.runJob(r, inputs)} />}
    </article>
    </div>
    <ResultsRail jobs={jobs} generation={runtime.generation} selectedId={selected?.id} onSelect={(job) => setSelectedId(job.id)} fileUrl={(job, output) => session.fileUrl(job, output)}
      onCancel={(job) => session.cancelJob(job)} />
    <JobModal open={!!selected} onClose={() => setSelectedId(null)} title={selected ? jobTitle(selected) : ''}>
      {selected && <JobDetail job={selected} runtime={state.runtimes?.find((item) => item.id === selected.model_id) ?? runtime} generation={(state.runtimes?.find((item) => item.id === selected.model_id) ?? runtime).generation ?? runtime.generation} fileUrl={(job, output) => session.fileUrl(job, output)}
        inputUrl={(job, name) => session.inputUrl(job, name)}
        onReuse={async (job) => {
          if (group?.reuseElsewhere && job.model_id !== modelId) { group.reuseElsewhere(job); setSelectedId(null); window.scrollTo({ top: 0, behavior: 'smooth' }); return }
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
        onEditTranscript={(job, edit) => session.editTranscript(job, edit)}
        onEditNotes={(job, edit) => session.editNotes(job, edit)}
        onUseFrame={group?.useFrame ? async (job, url) => {
          try {
            const frame = await lastFrame(await (await fetch(url)).blob())
            const name = `${job.id.slice(0, 8)}-last-frame.png`
            const record = await session.uploadFile(new File([frame], name, { type: 'image/png' }))
            group.useFrame?.({ key: `frame-${job.id}-${record.id}`, name, kind: 'image', url: URL.createObjectURL(frame), status: 'ready', id: record.id })
            setSelectedId(null); window.scrollTo({ top: 0, behavior: 'smooth' })
            return ''
          } catch (reason) { return reason instanceof Error ? reason.message : 'The last frame could not be used.' }
        } : undefined}
        onUseClip={group?.useClip ? async (job, url) => {
          try {
            const blob = await (await fetch(url)).blob()
            const name = `${job.id.slice(0, 8)}-clip.mp4`
            const record = await session.uploadFile(new File([blob], name, { type: blob.type || 'video/mp4' }))
            group.useClip?.({ key: `clip-${job.id}-${record.id}`, name, kind: 'video', url: URL.createObjectURL(blob), status: 'ready', id: record.id })
            setSelectedId(null); window.scrollTo({ top: 0, behavior: 'smooth' })
            return ''
          } catch (reason) { return reason instanceof Error ? reason.message : 'The clip could not be used.' }
        } : undefined}
        onUseSong={group?.useSong ? async (job, url) => {
          try {
            const blob = await (await fetch(url)).blob()
            const name = `${job.id.slice(0, 8)}-song${blob.type.includes('flac') ? '.flac' : blob.type.includes('wav') ? '.wav' : '.mp3'}`
            const record = await session.uploadFile(new File([blob], name, { type: blob.type }))
            group.useSong?.({ key: `song-${job.id}-${record.id}`, name, kind: 'audio', url: URL.createObjectURL(blob), status: 'ready', id: record.id })
            setSelectedId(null); window.scrollTo({ top: 0, behavior: 'smooth' })
            return ''
          } catch (reason) { return reason instanceof Error ? reason.message : 'The song could not be used.' }
        } : undefined}
        onSaveVoice={state.runtimes?.some((item) => item.generation?.speech?.voices.clone) ? async (job, url, name, text) => {
          try {
            const wav = await soundtrackToWav(await (await fetch(url)).blob())
            const record = await session.uploadFile(new File([wav], `voice-${job.id.slice(0, 8)}.wav`, { type: 'audio/wav' }))
            await session.saveVoice(name, text, record.id)
            group?.onVoiceSaved?.()
            return ''
          } catch (reason) { return reason instanceof Error ? reason.message : 'The voice could not be saved.' }
        } : undefined} />}
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
