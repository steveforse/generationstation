import { useEffect, useId, useRef, useState } from 'react'
import { AlertCircle, AlertTriangle, ArrowUpRight, Ban, Check, CheckCircle2, ChevronDown, Clock, Download, Film, HelpCircle, Hourglass, Image as ImageIcon, Loader2, Lock, MessageCircleMore, Music, RotateCcw, Sparkles, Trash2, Unlock, X } from 'lucide-react'
import { formatBytes } from '../api'
import type { Generation, Host, InputField, Job, JobFile, JobOutput, Launch, Model, ModelMemory, Refusal, Runtime, RuntimeEstimate, RuntimeSetting, SettingValue, UploadRecord } from '../types'
import { FilePicker, type FileItem } from './FilePicker'
import { CropEditor, shapeAspect } from './CropEditor'
import { estimateFit } from './Resources'
import { WorkloadIcon } from './WorkloadIcon'
import { RefusalDetails } from './Refusal'
import { StatePill } from './StatePill'
import type { VoiceTarget } from '../voiceSample'

/**
 * How a dropdown option reads: the plugin's own name for it, else the value with a capital first letter.
 * Codes such as "q8_0" or "f16" are shown in capitals.
 */
export function optionLabel(value: string, labels?: Record<string, string> | null) {
  if (labels?.[value]) return labels[value]
  if (/^[a-z]+\d/.test(value)) return value.toUpperCase()
  return value.charAt(0).toUpperCase() + value.slice(1)
}

/** A "?" beside a setting's label: its explanation shows on hover or keyboard focus, and toggles on tap. */
export function HelpTip({ label, text }: { label: string; text: string }) {
  const id = useId()
  const [open, setOpen] = useState(false)
  return <span className="help-tip" onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
    <button type="button" className="help-tip-button" aria-label={`What ${label} does`} aria-describedby={id} aria-expanded={open}
      onClick={() => setOpen((current) => !current)} onFocus={() => setOpen(true)} onBlur={() => setOpen(false)}
      onKeyDown={(event) => { if (event.key === 'Escape') setOpen(false) }}><HelpCircle size={18} /></button>
    <span role="tooltip" id={id} className={`help-tip-text ${open ? 'help-tip-open' : ''}`}>{text}</span>
  </span>
}

/** A setting's label row: the label (tied to its control) and, when there is help, a "?" with the explanation. */
function FieldLabel({ htmlFor, label, suffix = '', help }: { htmlFor: string; label: string; suffix?: string; help?: string }) {
  return <span className="field-label"><label htmlFor={htmlFor}>{label}{suffix && <span className="field-label-suffix">{suffix}</span>}</label>{help && <HelpTip label={label} text={help} />}</span>
}

export function defaultLaunch(runtime: Runtime, presetKey: string): Launch {
  const preset = runtime.presets[presetKey]
  const settings: Record<string, SettingValue> = {}
  for (const setting of preset?.settings ?? []) settings[setting.key] = setting.default
  // Reuse the last start's choices when it used the same preset.
  if (runtime.last_launch?.preset === presetKey) {
    for (const [key, value] of Object.entries(runtime.last_launch.settings)) if (key in settings) settings[key] = value
    return { preset: presetKey, settings, gpus: [...runtime.last_launch.gpus] }
  }
  return { preset: presetKey, settings, gpus: [...(preset?.gpus ?? [])] }
}

export function settingProblem(setting: RuntimeSetting, value: SettingValue) {
  if (setting.kind === 'bool' || setting.kind === 'choice') return ''
  if (value === null) return setting.kind === 'optional_int' ? '' : 'Required.'
  if (typeof value !== 'number' || !Number.isInteger(value)) return 'Enter a whole number.'
  if (setting.minimum !== null && value < setting.minimum) return `At least ${setting.minimum}.`
  if (setting.maximum !== null && value > setting.maximum) return `At most ${setting.maximum}.`
  return ''
}

export type GenerateHandlers = {
  jobs: Job[]; jobErrors: Record<string, string>
  onGenerate: (runtime: Runtime, inputs: Record<string, string | number | string[] | null>) => Promise<boolean>
  fileUrl: (job: Job, output: JobOutput) => Promise<string>
  inputUrl: (job: Job, name: string) => Promise<string>
}

export const makeLabel: Record<string, string> = { audio: 'Make a song', image: 'Make a picture', video: 'Make a video' }
const resultWord: Record<string, string> = { audio: 'song', image: 'picture', video: 'video' }
const runningWord: Record<string, string> = { audio: 'Composing', image: 'Painting', video: 'Rendering' }
/** The button, the word for one result, and the word for making one: the plugin's own, else its output kind's. */
const labelOf = (generation: Generation) => generation.make_label ?? makeLabel[generation.output_kind] ?? 'Make something'
const nounOf = (generation: Generation) => generation.result_noun ?? resultWord[generation.output_kind] ?? 'result'
const makingOf = (generation: Generation) => generation.result_noun ? 'Working' : runningWord[generation.output_kind] ?? 'Working'

/** "39 s", "2 min 25 s". */
export function formatSeconds(seconds: number) {
  if (seconds < 90) return `${Math.round(seconds)} s`
  const minutes = Math.floor(seconds / 60)
  const rest = Math.round(seconds - minutes * 60)
  return rest ? `${minutes} min ${rest} s` : `${minutes} min`
}

/** The measured time for these choices on the card the model is running on, from the plugin's timings. */
export function expectedTime(runtime: Runtime, generation: Generation, values: Record<string, string>) {
  const launch = runtime.last_launch
  const gpu = launch?.gpus[0]
  const timing = (generation.timings ?? []).find((item) =>
    (item.preset == null || item.preset === launch?.preset)
    && (item.gpu == null || item.gpu === gpu)
    && Object.entries(item.when).every(([key, value]) => values[key] === value))
  if (!timing) return ''
  const card = gpu == null ? undefined : launch ? runtime.presets[launch.preset]?.allowed_gpus.find((item) => item.index === gpu)?.name : undefined
  let text = `Usually about ${formatSeconds(timing.seconds)}${card ? ` on the ${card}` : ''}${timing.note ? `, ${timing.note}` : ''}.`
  if (timing.first_seconds) text += ` The first one after a start takes about ${formatSeconds(timing.first_seconds)} while it prepares.`
  return text
}

/** The fields of the form a job was made with: its mode's, or the only form's. */
export function fieldsFor(generation: Generation, mode?: unknown) {
  const modes = generation.modes ?? []
  return modes.length ? (modes.find((item) => item.key === mode) ?? modes[0]).inputs : generation.inputs
}

export type FormStart = { mode?: string; inputs?: Job['inputs']; files?: Record<string, FileItem[]> }

/** The generation form; with several modes, one tab per mode, each keeping its own entries. */
export function GenerateForm({ runtime, generation, onGenerate, error, initial, ahead = 0, upload }: {
  runtime: Runtime; generation: Generation; error?: string; onGenerate: GenerateHandlers['onGenerate']
  initial?: FormStart; ahead?: number; upload: (file: File) => Promise<UploadRecord>
}) {
  const modes = generation.modes ?? []
  const [mode, setMode] = useState(() => modes.find((item) => item.key === initial?.mode)?.key ?? modes[0]?.key ?? '')
  const label = labelOf(generation)
  if (!modes.length) return <ModeForm runtime={runtime} generation={generation} fields={generation.inputs} onGenerate={onGenerate} error={error} initial={initial} ahead={ahead} upload={upload} label={label} />
  const current = modes.find((item) => item.key === mode) ?? modes[0]
  return <div className="generate-modes">
    <div className="mode-tabs" role="tablist" aria-label="How to make it">
      {modes.map((item) => <button key={item.key} type="button" role="tab" id={`${runtime.id}-tab-${item.key}`} aria-selected={item.key === current.key}
        aria-controls={`${runtime.id}-panel-${item.key}`} className={`mode-tab ${item.key === current.key ? 'mode-tab-on' : ''}`} onClick={() => setMode(item.key)}>{item.label}</button>)}
    </div>
    {modes.map((item) => <div key={item.key} role="tabpanel" id={`${runtime.id}-panel-${item.key}`} aria-labelledby={`${runtime.id}-tab-${item.key}`} hidden={item.key !== current.key}>
      <p className="mode-help">{item.help}</p>
      <ModeForm runtime={runtime} generation={generation} fields={item.inputs} mode={item.key} onGenerate={onGenerate} error={item.key === current.key ? error : undefined}
        initial={initial?.mode === item.key || (!initial?.mode && item.key === modes[0].key) ? initial : undefined} ahead={ahead} upload={upload} label={label} />
    </div>)}
  </div>
}

function ModeForm({ runtime, generation, fields, mode, onGenerate, error, initial, ahead, upload, label }: {
  runtime: Runtime; generation: Generation; fields: InputField[]; mode?: string; onGenerate: GenerateHandlers['onGenerate']; error?: string
  initial?: FormStart; ahead: number; upload: (file: File) => Promise<UploadRecord>; label: string
}) {
  const [values, setValues] = useState<Record<string, string>>(() => Object.fromEntries(fields.filter((field) => field.kind !== 'files').map((field) => {
    let start = initial?.inputs?.[field.key] ?? field.default
    if (field.kind === 'choice' && !field.options.includes(String(start))) start = field.default  // an option since renamed
    return [field.key, start == null || Array.isArray(start) ? '' : String(start)]
  })))
  const [files, setFiles] = useState<Record<string, FileItem[]>>(() => initial?.files ?? {})
  const [advanced, setAdvanced] = useState(() => fields.some((field) => field.advanced && initial?.inputs?.[field.key] != null && initial.inputs[field.key] !== field.default))
  const [sending, setSending] = useState(false)
  // Width and height pairs stay in the clip's proportions unless unlocked.
  const [locked, setLocked] = useState(true)
  const firstPicture = fields.filter((field) => field.kind === 'files').flatMap((field) => files[field.key] ?? []).find((item) => item.kind === 'image' && item.url)
  const [pictureAspect, setPictureAspect] = useState<number | null>(null)
  useEffect(() => {
    if (!firstPicture) { setPictureAspect(null); return }
    const image = new Image()
    image.onload = () => setPictureAspect(image.naturalWidth / image.naturalHeight)
    image.src = firstPicture.url
  }, [firstPicture?.url])
  const pairRatio = (field: InputField) => shapeAspect(values[field.shape_field ?? 'shape'] ?? '') ?? pictureAspect ?? 16 / 9
  const widthField = fields.find((field) => field.ratio_role === 'width' && field.ratio_partner)
  const ratioNow = widthField ? pairRatio(widthField) : null
  useEffect(() => {
    // A new shape (or picture) re-derives the height from the width while locked.
    if (!widthField || !locked || ratioNow === null) return
    const width = Number(values[widthField.key])
    if (width > 0) setValues((current) => ({ ...current, [widthField.ratio_partner!]: String(Math.round(width / ratioNow)) }))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ratioNow, locked])
  const problem = (field: InputField) => {
    if (field.kind === 'files') return (files[field.key] ?? []).some((item) => item.status === 'error') ? 'Remove the files that could not be added.' : ''
    const raw = values[field.key] ?? ''
    if (!raw.trim()) return field.required ? 'Required.' : ''
    if ((field.kind === 'text' || field.kind === 'textarea') && field.max_length && raw.length > field.max_length) return `At most ${field.max_length} characters.`
    if (field.kind === 'int' || field.kind === 'seed') {
      const number = Number(raw)
      if (!Number.isInteger(number)) return 'Enter a whole number.'
      if ((field.minimum !== null && number < field.minimum) || (field.maximum !== null && number > field.maximum)) return `Between ${field.minimum} and ${field.maximum}.`
    }
    return ''
  }
  const uploading = Object.values(files).some((items) => items.some((item) => item.status === 'uploading'))
  const valid = fields.every((field) => !Object.entries(field.show_when ?? {}).every(([key, value]) => values[key] === value) || !problem(field)) && !uploading
  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!valid) return
    const inputs: Record<string, string | number | string[] | null> = mode ? { mode } : {}
    for (const field of fields) {
      if (!Object.entries(field.show_when ?? {}).every(([key, value]) => values[key] === value)) continue  // hidden: not sent
      if (field.kind === 'crop') {
        const raw = values[field.key] ?? ''
        if (raw && cropAspect(field) !== null && (files[field.target ?? ''] ?? []).length) inputs[field.key] = raw
        continue
      }
      if (field.kind === 'files') {
        const ids = (files[field.key] ?? []).map((item) => item.id).filter((id): id is string => !!id)
        if (ids.length) inputs[field.key] = ids
        continue
      }
      const raw = (values[field.key] ?? '').trim()
      if (!raw) continue
      inputs[field.key] = field.kind === 'int' || field.kind === 'seed' ? Number(raw) : raw
    }
    setSending(true)
    await onGenerate(runtime, inputs)
    setSending(false)
  }
  // The clip's proportions when a framing box applies: a shape other than "match picture", or a custom size.
  const cropAspect = (crop: InputField) => {
    const shape = values[crop.shape_field ?? 'shape'] ?? ''
    const custom = values.resolution === 'custom'
    return shapeAspect(shape, custom ? values.width : undefined, custom ? values.height : undefined)
  }
  const framing = (field: InputField) => fields.filter((crop) => crop.kind === 'crop' && crop.target === field.key).map((crop) => {
    const aspect = cropAspect(crop)
    const picture = (files[field.key] ?? []).find((item) => item.kind === 'image' && item.url)
    if (aspect === null || !picture) return null
    return <div className="framing" key={crop.key}><small>Framing: the box is what the clip shows.</small>
      <CropEditor src={picture.url} label={field.label} aspect={aspect} value={values[crop.key] ?? ''}
        onChange={(next) => setValues((current) => ({ ...current, [crop.key]: next }))} /></div>
  })
  const renderField = (field: InputField) => {
    const id = `${runtime.id}-${mode ?? 'input'}-${field.key}`
    const value = values[field.key] ?? ''
    const set = (next: string) => setValues((current) => {
      const updated = { ...current, [field.key]: next }
      const number = Number(next)
      if (locked && field.ratio_partner && next.trim() && number > 0) {
        const ratio = pairRatio(field)
        updated[field.ratio_partner] = String(Math.round(field.ratio_role === 'width' ? number / ratio : number * ratio))
      }
      return updated
    })
    const shown = field.kind === 'files' ? problem(field) : value && problem(field)
    return <div className={`field ${field.kind === 'textarea' ? 'field-wide' : ''} ${field.kind === 'files' ? 'field-files' : ''}`} key={field.key}>
      <FieldLabel htmlFor={id} label={field.label} suffix={field.required || field.kind === 'files' ? '' : ' (optional)'} help={field.help} />
      {field.kind === 'files' ? <><FilePicker id={id} field={field} items={files[field.key] ?? []} upload={upload}
          onChange={(update) => setFiles((current) => ({ ...current, [field.key]: update(current[field.key] ?? []) }))} />{framing(field)}</>
        : field.kind === 'textarea' ? <textarea id={id} className="text-input generate-textarea" rows={10} maxLength={field.max_length ?? undefined} placeholder={field.placeholder ?? undefined} value={value} onChange={(event) => set(event.target.value)} />
        : field.kind === 'choice' ? <select id={id} className="text-input" value={value} onChange={(event) => set(event.target.value)}>{field.options.map((option) => <option key={option} value={option}>{optionLabel(option, field.option_labels)}</option>)}</select>
          : <input id={id} className="text-input" type={field.kind === 'text' ? 'text' : 'number'} step={field.kind === 'text' ? undefined : 1} maxLength={field.max_length ?? undefined} placeholder={field.placeholder ?? (field.kind === 'seed' ? 'Random' : undefined)} value={value} onChange={(event) => set(event.target.value)} />}
      {field.guide && field.guide.length > 0 && <details className="field-guide disclosure"><summary><ChevronDown size={16} aria-hidden="true" className="disclosure-chevron" />Writing guide</summary><ul>
        {field.guide.map((tip) => { const [head, ...rest] = tip.split(': '); return <li key={tip}>{rest.length ? <><strong>{head}:</strong> {rest.join(': ')}</> : tip}</li> })}
      </ul></details>}
      {field.ratio_role === 'width' && field.ratio_partner && <button type="button" className="text-button ratio-lock" aria-pressed={locked}
        onClick={() => setLocked(!locked)}>{locked ? <Lock size={16} /> : <Unlock size={16} />}{locked ? 'Locked to the shape’s proportions' : 'Proportions unlocked'}</button>}
      {shown && <small className="field-problem"><AlertCircle size={16} aria-hidden="true" />{shown}</small>}
    </div>
  }
  // Fields such as the custom size appear only while they apply (resolution "custom").
  const shown = (field: InputField) => Object.entries(field.show_when ?? {}).every(([key, value]) => values[key] === value)
  const basic = fields.filter((field) => !field.advanced && field.kind !== 'crop' && shown(field))
  const extra = fields.filter((field) => field.advanced && field.kind !== 'crop' && shown(field))
  const fileFields = basic.filter((field) => field.kind === 'files')
  const otherFields = basic.filter((field) => field.kind !== 'files')
  const expected = expectedTime(runtime, generation, mode ? { ...values, mode } : values)
  // Why the Make button is off, from the same checks that switch it off.
  const lower = (text: string) => text.charAt(0).toLowerCase() + text.slice(1)
  const blocking = fields.find((field) => shown(field) && problem(field))
  const missing = sending ? '' : uploading ? 'Wait for the upload to finish.'
    : blocking ? (problem(blocking) === 'Required.' ? `Add ${lower(blocking.label)} first.` : `${blocking.label}: ${lower(problem(blocking))}`) : ''
  const missingId = `${runtime.id}-${mode ?? 'input'}-missing`
  return <form className="generate-form" onSubmit={submit} aria-label={label}>
    {fileFields.length > 0 && <div className="generate-files">{fileFields.map(renderField)}</div>}
    <div className="generate-fields">{otherFields.map(renderField)}</div>
    {extra.length > 0 && <><button type="button" className="text-button" aria-expanded={advanced} onClick={() => setAdvanced(!advanced)}><ChevronDown size={16} className={advanced ? 'chevron-open' : ''} /> More options</button>
      {advanced && <div className="generate-fields">{extra.map(renderField)}</div>}</>}
    {error && <div className="form-error" role="alert"><AlertCircle size={16} />{error}</div>}
    <div className="generate-actions">{(expected || ahead > 0) && <span className="generate-expected"><Clock size={16} /><span>{expected}{ahead > 0 && <> {ahead === 1 ? 'One is' : `${ahead} are`} ahead in the queue; this one starts after {ahead === 1 ? 'it' : 'them'}.</>}</span></span>}<span className="generate-submit">{!valid && missing && <span className="generate-missing" id={missingId}>{missing}</span>}<button className="button button-primary button-lg" type="submit" disabled={!valid || sending} aria-describedby={!valid && missing ? missingId : undefined}><Sparkles size={16} />{sending ? 'Sending…' : uploading ? 'Uploading…' : ahead > 0 ? 'Add to queue' : label}</button></span></div>
  </form>
}

export function jobTitle(job: Job) {
  const text = typeof job.inputs.prompt === 'string' ? job.inputs.prompt : typeof job.inputs.style === 'string' ? job.inputs.style : ''
  return text.trim() || 'Untitled'
}

/** Seconds the worker took, or the wall-clock time from request to finish for results made before it reported that. */
export function jobSeconds(job: Job) {
  const reported = job.details?.seconds
  if (typeof reported === 'number') return reported
  if (!job.finished_at) return null
  const seconds = (Date.parse(job.finished_at) - Date.parse(job.created_at)) / 1000
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : null
}

const statusLabel = (job: Job) => ({ queued: 'Queued', running: job.progress ?? 'Working', done: 'Done', failed: 'Did not work', cancelled: 'Cancelled' }[job.status] ?? job.status)
const active = (job: Job) => job.status === 'queued' || job.status === 'running'
const ordinal = (n: number) => n === 1 ? 'next' : `${n}${n === 2 ? 'nd' : n === 3 ? 'rd' : 'th'} in line`

/** Each queued job's place in line (1 = starts next), from oldest to newest. */
export function queuePositions(jobs: Job[]) {
  const queued = jobs.filter((job) => job.status === 'queued').sort((a, b) => a.created_at.localeCompare(b.created_at))
  return Object.fromEntries(queued.map((job, index) => [job.id, index + 1]))
}
export const when = (iso: string) => new Date(iso).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })

const THUMBNAIL = 'thumbnail.jpg'
const isThumbnail = (job: Job, output: JobOutput) => output.name === (typeof job.details?.thumbnail === 'string' ? job.details.thumbnail : THUMBNAIL)

/** A result's preview: the worker's thumbnail, else a picture itself, else an icon for its kind. */
export function ResultThumb({ job, kind, fileUrl }: { job: Job; kind: string; fileUrl: GenerateHandlers['fileUrl'] }) {
  const [url, setUrl] = useState('')
  const source = job.status === 'done' ? job.outputs.find((output) => isThumbnail(job, output)) ?? job.outputs.find((output) => output.mime.startsWith('image/')) : undefined
  useEffect(() => {
    if (!source) return
    let cancelled = false
    let made = ''
    fileUrl(job, source).then((next) => { made = next; if (!cancelled) setUrl(next) }).catch(() => undefined)
    return () => { cancelled = true; if (made) URL.revokeObjectURL(made); setUrl('') }
    // Fetch each result's preview once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job.id, source?.name])
  const Icon = job.status === 'cancelled' ? Ban : kind === 'audio' ? Music : kind === 'image' ? ImageIcon : Film
  return <span className={`result-thumb ${url ? '' : 'result-thumb-empty'} thumb-${job.status}`} aria-hidden="true">
    {url ? <img src={url} alt="" /> : job.status === 'running' ? <Loader2 size={24} className="spin" /> : job.status === 'queued' ? <Hourglass size={22} /> : <Icon size={22} />}
    {job.status === 'done' && kind === 'video' && url && <span className="result-thumb-play" />}
  </span>
}

/** The results sidebar: every result of this model, newest first, with a preview. */
export function ResultsRail({ jobs, generation, selectedId, onSelect, fileUrl, onCancel }: {
  jobs: Job[]; generation: Generation; selectedId?: string; onSelect: (job: Job) => void; fileUrl: GenerateHandlers['fileUrl']
  onCancel: (job: Job) => Promise<string>
}) {
  const word = nounOf(generation)
  const modeLabel = (job: Job) => (generation.modes ?? []).length > 1 ? generation.modes?.find((item) => item.key === job.inputs.mode)?.label : undefined
  const choices = (job: Job) => fieldsFor(generation, job.inputs.mode).filter((field) => field.kind === 'choice' && !field.advanced)
  const places = queuePositions(jobs)
  const working = jobs.filter((job) => job.status === 'running').length
  const waiting = Object.keys(places).length
  const [problems, setProblems] = useState<Record<string, string>>({})
  const [cancelling, setCancelling] = useState<Record<string, boolean>>({})
  const cancel = async (job: Job) => {
    setCancelling((current) => ({ ...current, [job.id]: true }))
    const problem = await onCancel(job)
    setCancelling((current) => ({ ...current, [job.id]: false }))
    setProblems((current) => ({ ...current, [job.id]: problem }))
  }
  return <aside className="results-rail" aria-label={`Your ${word}s`}>
    <div className="results-rail-head"><h2>Your {word}s</h2><span>{[working ? `${working} ${makingOf(generation).toLowerCase()}` : '', waiting ? `${waiting} queued` : ''].filter(Boolean).join(' · ') || jobs.length}</span></div>
    {jobs.length === 0 ? <p className="results-empty">Nothing yet. What you make appears here.</p>
      : <ul className="results-list">{jobs.map((job) => {
        const seconds = jobSeconds(job)
        const settings = [modeLabel(job) ?? '', ...choices(job).filter((field) => job.inputs[field.key] != null).map((field) => optionLabel(String(job.inputs[field.key]), field.option_labels))].filter(Boolean).join(' · ')
        const time = [when(job.created_at), job.status === 'done' && seconds != null ? formatSeconds(seconds) : ''].filter(Boolean).join(' · ')
        const status = job.status === 'queued' ? `Queued · ${ordinal(places[job.id] ?? 1)}`
          : job.status === 'running' ? `${makingOf(generation)} · ${job.progress ?? 'starting'}`
            : job.status === 'done' ? '' : statusLabel(job)
        const StatusIcon = job.status === 'running' ? Loader2 : job.status === 'queued' ? Hourglass : job.status === 'failed' ? AlertCircle : job.status === 'cancelled' ? Ban : CheckCircle2
        return <li key={job.id} className={`result-row ${job.id === selectedId ? 'result-item-on' : ''} row-${job.status}`}>
          <button type="button" className="result-item" aria-current={job.id === selectedId} onClick={() => onSelect(job)}>
            <ResultThumb job={job} kind={generation.output_kind} fileUrl={fileUrl} />
            <span className="result-text"><strong>{jobTitle(job)}</strong>
              {status && <small className={`result-status status-${job.status}`}><StatusIcon size={14} aria-hidden="true" className={job.status === 'running' ? 'spin' : undefined} />{status}</small>}
              {job.status === 'done' && settings && <small className="result-meta" title={settings}>{settings}</small>}
              <small className="result-time">{time}</small>
              {problems[job.id] && <small className="operation-error">{problems[job.id]}</small>}</span>
          </button>
          {active(job) && <button type="button" className="icon-button result-cancel" aria-label={`Cancel ${jobTitle(job)}`} title="Cancel"
            disabled={cancelling[job.id] || job.progress === 'Cancelling'} onClick={() => void cancel(job)}><X size={16} /></button>}
        </li>
      })}</ul>}
  </aside>
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return <><dt>{label}</dt><dd>{children}</dd></>
}

/** One result: the file, how it was made (everything typed, what the model actually used, the model settings), and its actions. */
/** A job's reference file, fetched with the access token. */
function InputThumb({ job, file, inputUrl }: { job: Job; file: JobFile; inputUrl: GenerateHandlers['inputUrl'] }) {
  const [url, setUrl] = useState('')
  useEffect(() => {
    let cancelled = false
    let made = ''
    inputUrl(job, file.name).then((next) => { made = next; if (!cancelled) setUrl(next) }).catch(() => undefined)
    return () => { cancelled = true; if (made) URL.revokeObjectURL(made) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job.id, file.name])
  return <a className="input-thumb" href={url || undefined} download={file.original} title={file.original}>
    {file.kind === 'image' && url ? <img src={url} alt={file.original} /> : file.kind === 'video' && url ? <video src={url} muted preload="metadata" aria-label={file.original} />
      : <span className="file-icon">{file.kind === 'audio' ? <Music size={22} /> : <Film size={22} />}</span>}
    <small>{file.original}</small>
  </a>
}

export function JobDetail({ job, runtime, generation, fileUrl, inputUrl, onReuse, onDelete, onCancel, voiceTargets = [], onUseVoice }: {
  job: Job; runtime: Runtime; generation: Generation; fileUrl: GenerateHandlers['fileUrl']; inputUrl: GenerateHandlers['inputUrl']
  onReuse: (job: Job) => void | Promise<void>; onDelete: (job: Job) => Promise<string>; onCancel: (job: Job) => Promise<string>
  /** Speech models that can clone a voice; a finished clip's soundtrack can be sent to one as its voice sample. */
  voiceTargets?: VoiceTarget[]; onUseVoice?: (job: Job, url: string, target: VoiceTarget) => Promise<string>
}) {
  const [voiceBusy, setVoiceBusy] = useState('')
  const [urls, setUrls] = useState<Record<string, string>>({})
  const [error, setError] = useState('')
  const [confirming, setConfirming] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const files = job.outputs.filter((output) => !isThumbnail(job, output))
  const media = files.filter((output) => /^(audio|image|video)\//.test(output.mime))
  const others = files.filter((output) => !media.includes(output))
  useEffect(() => {
    setConfirming(false); setError('')
    if (job.status !== 'done') return
    let cancelled = false
    const made: string[] = []
    void Promise.all(files.map(async (output) => {
      const url = await fileUrl(job, output)
      made.push(url)
      if (!cancelled) setUrls((current) => ({ ...current, [output.name]: url }))
    })).catch((reason) => { if (!cancelled) setError(reason instanceof Error ? reason.message : 'The file could not be loaded.') })
    return () => { cancelled = true; made.forEach((url) => URL.revokeObjectURL(url)); setUrls({}) }
    // Load each finished job's files once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job.id, job.status])
  const title = jobTitle(job)
  const details = job.details ?? {}
  const seconds = jobSeconds(job)
  const prompt = typeof job.inputs.prompt === 'string' ? job.inputs.prompt : null
  const sentPrompt = typeof details.prompt === 'string' && details.prompt !== prompt ? details.prompt : null
  const jobFields = fieldsFor(generation, job.inputs.mode)
  const applies = (field: InputField) => Object.entries(field.show_when ?? {}).every(([key, value]) => job.inputs[key] === value)
  const fields = jobFields.filter((field) => field.key !== 'prompt' && field.kind !== 'files' && field.kind !== 'crop' && applies(field) && job.inputs[field.key] != null && job.inputs[field.key] !== '')
  const framed = jobFields.filter((field) => field.kind === 'crop' && typeof job.inputs[field.key] === 'string').map((field) => field.target).join(' and ')
  const fileFields = jobFields.filter((field) => field.kind === 'files' && Array.isArray(job.inputs[field.key]) && (job.inputs[field.key] as JobFile[]).length)
  const mode = (generation.modes ?? []).length > 1 ? generation.modes?.find((item) => item.key === job.inputs.mode) : undefined
  const launch = job.launch
  const preset = launch ? runtime.presets[launch.preset] : undefined
  const gpus = launch?.gpus.map((index) => preset?.allowed_gpus.find((gpu) => gpu.index === index)?.name ?? `GPU ${index}`).join(' and ')
  const startSettings = launch ? Object.entries(launch.settings).map(([key, value]) => {
    const setting = preset?.settings.find((item) => item.key === key)
    return [setting?.label ?? key, typeof value === 'boolean' ? (value ? 'on' : 'off') : value == null ? 'automatic' : String(value)]
  }) : []
  const size = typeof details.width === 'number' && typeof details.height === 'number' ? `${details.width} × ${details.height}` : null
  const remove = async () => {
    setDeleting(true)
    const problem = await onDelete(job)
    setDeleting(false)
    if (problem) { setError(problem); setConfirming(false) }
  }
  return <article className="job-detail" aria-label={`${nounOf(generation)}: ${title}`}>
    <div className="job-head"><StatePill state={job.status}>{statusLabel(job)}</StatePill>
      <small>{when(job.created_at)}{job.status === 'done' && seconds != null ? ` · took ${formatSeconds(seconds)}` : ''}</small></div>
    {job.status === 'failed' && job.error_message && <small className="operation-error">{job.error_message}</small>}
    {error && <small className="operation-error" role="alert">{error}</small>}
    {media.map((output) => <div className="job-media" key={output.name}>
      {urls[output.name] ? (output.mime.startsWith('audio/') ? <audio controls src={urls[output.name]} aria-label={`Play ${title}`} />
        : output.mime.startsWith('image/') ? <img src={urls[output.name]} alt={title} />
          : <video controls src={urls[output.name]} aria-label={`Play ${title}`} />) : <div className="job-media-loading"><small>Loading…</small></div>}
    </div>)}
    <div className="job-actions">
      <button type="button" className="button button-secondary" onClick={() => void onReuse(job)}><RotateCcw size={16} />Use these settings</button>
      {job.status === 'done' && onUseVoice && media.filter((output) => output.mime.startsWith('video/')).slice(0, 1).flatMap((output) => voiceTargets.map((target) =>
        <button key={target.runtime.id} type="button" className="button button-secondary" disabled={!urls[output.name] || !!voiceBusy}
          title={`Send this clip's sound to ${target.runtime.name} as the voice to speak in${target.ready ? '' : ` (${target.runtime.name} is not running: start it on the Models page)`}`}
          onClick={async () => { setVoiceBusy(target.runtime.id); setError(''); const problem = await onUseVoice(job, urls[output.name], target); setVoiceBusy(''); if (problem) setError(problem) }}>
          {voiceBusy === target.runtime.id ? <Loader2 size={16} className="spin" /> : <MessageCircleMore size={16} />}Use voice in {target.runtime.name}</button>))}
      {[...media, ...others].map((output) => urls[output.name] && <a key={output.name} className="button button-secondary" href={urls[output.name]} download={output.name}><Download size={16} />{output.name}</a>)}
      {active(job) && <button type="button" className="button button-secondary job-delete" disabled={deleting || job.progress === 'Cancelling'}
        onClick={async () => { setDeleting(true); setError(await onCancel(job)); setDeleting(false) }}><X size={16} />{job.progress === 'Cancelling' ? 'Cancelling…' : 'Cancel'}</button>}
      {!active(job)
        ? confirming ? <span className="job-confirm"><span>Delete this {nounOf(generation)} and its files?</span>
            <button type="button" className="button button-danger" disabled={deleting} onClick={() => void remove()}><Trash2 size={16} />{deleting ? 'Deleting…' : 'Delete'}</button>
            <button type="button" className="button button-secondary" disabled={deleting} onClick={() => setConfirming(false)}>Keep</button></span>
          : <button type="button" className="button button-secondary button-danger-outline job-delete" onClick={() => setConfirming(true)}><Trash2 size={16} />Delete</button>
        : null}
    </div>
    {fileFields.length > 0 && <section className="job-section"><h4>Pictures and references</h4><div className="input-thumbs">
      {fileFields.map((field) => (job.inputs[field.key] as JobFile[]).map((file) => <div key={file.name} className="input-group"><span>{field.label}</span><InputThumb job={job} file={file} inputUrl={inputUrl} /></div>))}
    </div></section>}
    {prompt && <section className="job-section"><h4>{jobFields.find((field) => field.key === 'prompt')?.label ?? 'Description'}</h4><p className="job-prompt">{prompt}</p></section>}
    <section className="job-section"><h4>Settings</h4><dl className="job-facts">
      {mode && <Row label="Made">{mode.label}</Row>}
      {framed && <Row label="Framing">chosen on the preview ({framed} frame)</Row>}
      {fields.map((field) => <Row key={field.key} label={field.label}>{field.kind === 'textarea' ? <span className="job-prompt">{String(job.inputs[field.key])}</span>
        : field.kind === 'choice' ? optionLabel(String(job.inputs[field.key]), field.option_labels) : String(job.inputs[field.key])}</Row>)}
      {typeof details.seed === 'number' && job.inputs.seed == null && <Row label="Seed used">{details.seed}</Row>}
      {typeof details.steps === 'number' && <Row label="Steps">{details.steps}</Row>}
      {size && <Row label="Size">{size}</Row>}
      {typeof details.clip_seconds === 'number' && <Row label="Length">{details.clip_seconds} s{typeof details.fps === 'number' ? ` at ${details.fps} fps` : ''}</Row>}
      {typeof details.audio_seconds === 'number' && <Row label="Length">{formatSeconds(details.audio_seconds)}</Row>}
      {seconds != null && job.status === 'done' && <Row label="Time to make">{formatSeconds(seconds)}</Row>}
    </dl></section>
    {launch && <section className="job-section"><h4>Model</h4><dl className="job-facts">
      <Row label="Model">{preset?.name ?? launch.preset}</Row>
      {gpus && <Row label="Card">{gpus}</Row>}
      {startSettings.map(([label, value]) => <Row key={label} label={label}>{value}</Row>)}
    </dl></section>}
    {sentPrompt && <details className="job-section job-sent disclosure"><summary><ChevronDown size={16} aria-hidden="true" className="disclosure-chevron" />Full prompt sent to the model</summary><pre>{sentPrompt}</pre></details>}
  </article>
}

/** A result in a modal dialog over the page: Escape, the close button or a click outside closes it. */
export function JobModal({ open, onClose, title, children }: { open: boolean; onClose: () => void; title: string; children: React.ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open && !dialog.open) dialog.showModal()
    if (!open && dialog.open) dialog.close()
  }, [open])
  return <dialog ref={ref} className="job-modal" aria-label={title} onClose={onClose} onClick={(event) => { if (event.target === ref.current) onClose() }}>
    {open && <div className="job-modal-body">
      <div className="job-modal-head"><strong>{title}</strong><button type="button" className="icon-button" aria-label="Close" onClick={onClose}><X size={18} /></button></div>
      {children}
    </div>}
  </dialog>
}

export function RuntimeCard({ runtime, model, host, fresh, pending, refusal, message, onRun, openHref, aside, usage, color, estimate, onEstimate }: {
  runtime: Runtime; model?: Model; host?: Host; fresh: boolean; pending: boolean; refusal?: Refusal; message?: string
  onRun: (runtime: Runtime, action: 'start' | 'stop', launch?: Launch) => Promise<void>
  /** Link to this service's generation page, for services that make something. */
  openHref?: string
  /** Shown beside the controls, inside the card (the Models page puts start/stop history here). */
  aside?: React.ReactNode
  /** Measured RAM/VRAM of this model's processes, and its color in the memory bars. */
  usage?: ModelMemory; color?: string
  /** Ask the host what a start with the current choices would need; the card reports it through onEstimate. */
  estimate?: (runtime: Runtime, launch: Launch, signal: AbortSignal) => Promise<RuntimeEstimate>
  onEstimate?: (estimate: RuntimeEstimate | null) => void
}) {
  const initialPreset = runtime.last_launch?.preset && runtime.presets[runtime.last_launch.preset] ? runtime.last_launch.preset : runtime.default_preset
  const [launch, setLaunch] = useState<Launch>(() => defaultLaunch(runtime, initialPreset))
  const [advanced, setAdvanced] = useState(false)
  // Cards start folded to one row; a fresh refusal or message opens it so the reason is in view. An old error
  // state does not: its badge in the row already says so.
  const [open, setOpen] = useState(false)
  const needsAttention = !!refusal || !!message
  useEffect(() => { if (needsAttention) setOpen(true) }, [needsAttention])
  const preset = runtime.presets[launch.preset]
  const state = model?.state ?? 'unknown'
  const stopped = ['unloaded', 'error'].includes(state)
  const running = ['ready', 'cleanup_failed'].includes(state)
  const problems = Object.fromEntries((preset?.settings ?? []).map((setting) => [setting.key, settingProblem(setting, launch.settings[setting.key] ?? null)]))
  const valid = !!preset && launch.gpus.length > 0 && Object.values(problems).every((problem) => !problem)
  const canStart = fresh && host?.loading_enabled === true && stopped && valid && !pending
  const [need, setNeed] = useState<RuntimeEstimate | null>(null)
  const [needError, setNeedError] = useState('')
  const wantEstimate = !!estimate && stopped && valid && !pending
  const launchKey = JSON.stringify(launch)
  useEffect(() => {
    if (!wantEstimate || !estimate) { setNeed(null); setNeedError(''); onEstimate?.(null); return }
    const controller = new AbortController()
    const timer = window.setTimeout(() => {
      estimate(runtime, launch, controller.signal)
        .then((result) => { setNeed(result); setNeedError(''); onEstimate?.(result) })
        .catch((reason) => { if (!controller.signal.aborted) { setNeed(null); setNeedError(reason instanceof Error ? reason.message : 'The estimate is unavailable.'); onEstimate?.(null) } })
    }, 250)
    return () => { window.clearTimeout(timer); controller.abort() }
    // Re-ask when the choices change; the callbacks are recreated on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [wantEstimate, launchKey, runtime.id])
  const fits = need ? estimateFit(host, need, fresh) : []
  const stateText = ({ unloaded: 'Stopped', loading: 'Loading', ready: 'Running', unloading: 'Stopping', error: 'Stopped after an error', cleanup_failed: 'Stop did not finish' } as Record<string, string>)[state] ?? state
  const setValue = (key: string, value: SettingValue) => setLaunch((current) => ({ ...current, settings: { ...current.settings, [key]: value } }))
  const choosePreset = (key: string) => setLaunch(defaultLaunch(runtime, key))
  const reset = () => setLaunch(defaultLaunch({ ...runtime, last_launch: null }, launch.preset))

  const cardNote = preset?.card_notes?.[[...launch.gpus].sort((a, b) => a - b).join(',')]
  // Settings marked advanced fold away; a plugin that marks none keeps all of them folded, as before.
  const anyAdvanced = !!preset?.settings.some((setting) => setting.advanced)
  const essentials = anyAdvanced ? preset!.settings.filter((setting) => !setting.advanced) : []
  const advancedSettings = anyAdvanced ? preset!.settings.filter((setting) => setting.advanced) : (preset?.settings ?? [])
  const settingField = (setting: RuntimeSetting) => {
          const value = launch.settings[setting.key] ?? null
          const id = `${runtime.id}-${setting.key}`
          return <div className="field" key={setting.key}>
            <FieldLabel htmlFor={id} label={setting.label} suffix={setting.unit ? ` (${setting.unit})` : ''} help={setting.help} />
            {setting.kind === 'bool' ? <input id={id} type="checkbox" disabled={!stopped || pending} checked={value === true} onChange={(event) => setValue(setting.key, event.target.checked)} />
              : setting.kind === 'choice' ? <select id={id} className="text-input" disabled={!stopped || pending} value={String(value ?? '')} onChange={(event) => setValue(setting.key, event.target.value)}>{(setting.options ?? []).map((option) => <option key={option} value={option}>{optionLabel(option, setting.option_labels)}</option>)}</select>
              : <input id={id} className="text-input" type="number" step={1} min={setting.minimum ?? undefined} max={setting.maximum ?? undefined} disabled={!stopped || pending}
                  placeholder={setting.kind === 'optional_int' ? 'Automatic' : undefined} value={value === null ? '' : String(value)}
                  onChange={(event) => setValue(setting.key, event.target.value === '' ? null : Number(event.target.value))} />}
            {problems[setting.key] && <small className="field-problem"><AlertCircle size={16} aria-hidden="true" />{problems[setting.key]}</small>}
            {setting.key === 'ram_reserve_mib' && value === 0 && <small className="field-warning"><AlertTriangle size={16} aria-hidden="true" />The RAM guard is off. Fine when this model is the only thing running; risky when other models need RAM.</small>}
          </div>
  }
  const detailsId = `${runtime.id}-details`
  const shortName = (name: string) => name.replace(/^NVIDIA (GeForce )?/, '')
  const gpuLimit = preset?.max_gpus ?? runtime.max_gpus
  // The cards in the folded row: choosable while stopped, the ones in use while running.
  const shownGpus = running || !stopped ? (runtime.last_launch?.gpus ?? launch.gpus) : launch.gpus
  const shortFall = fits.find((fit) => fit.fits === false)
  const fitWord = !stopped ? null
    : launch.gpus.length === 0 ? { kind: 'no', text: 'Choose a card' }
      : !valid ? { kind: 'no', text: 'Check settings' }
        : needError ? null
          : !need ? { kind: 'wait', text: 'Checking…' }
            : shortFall ? { kind: 'no', text: `${shortFall.label === 'RAM' ? 'RAM' : shortName(shortFall.label)}: ${formatBytes(shortFall.need - (shortFall.free ?? 0))} short` }
              : fits.every((fit) => fit.fits === true) ? { kind: 'yes', text: 'Fits' } : { kind: 'wait', text: 'Fit unknown' }
  const usedVram = usage ? Object.values(usage.gpus).reduce((sum, bytes) => sum + bytes, 0) : 0
  const summary = preset && <div className="runtime-summary">
    <fieldset className="runtime-chips" disabled={!stopped || pending}>
      <legend className="sr-only">GPUs</legend>
      {preset.allowed_gpus.filter((gpu) => stopped || shownGpus.includes(gpu.index)).map((gpu) => {
        const on = shownGpus.includes(gpu.index)
        return <label key={gpu.index} title={gpu.name} className={`runtime-chip ${on ? 'runtime-chip-on' : ''}`}>
          {gpuLimit === 1
            ? <input type="radio" name={`${runtime.id}-gpu`} aria-label={gpu.name} checked={on} onChange={() => setLaunch((current) => ({ ...current, gpus: [gpu.index] }))} />
            : <input type="checkbox" aria-label={gpu.name} checked={on} onChange={(event) => setLaunch((current) => ({ ...current, gpus: event.target.checked ? [...current.gpus, gpu.index].sort() : current.gpus.filter((item) => item !== gpu.index) }))} />}
          <span>{shortName(gpu.name)}</span></label>
      })}
    </fieldset>
    {fitWord && <span className={`runtime-fitword fitword-${fitWord.kind}`}>{fitWord.kind === 'yes' ? <Check size={14} aria-hidden="true" /> : fitWord.kind === 'no' ? <X size={14} aria-hidden="true" /> : null}{fitWord.text}</span>}
    {running && usage && <span className="runtime-fitword">{formatBytes(usedVram)} VRAM · {formatBytes(usage.ram_bytes)} RAM</span>}
  </div>
  return <article className={`profile-card runtime-card ${open ? 'runtime-card-open' : ''}`}>
    <div className="profile-card-main"><div className="model-icon" style={color ? { color, background: `${color}1f` } : undefined}><WorkloadIcon workload={runtime.workload} size={20} /></div><div className="profile-card-title"><div><strong>{runtime.name}</strong><span className="profile-id">{runtime.workload}</span></div>
      {summary}
      <div className="profile-actions runtime-head-actions">
        {!stopped && <StatePill state={pending ? 'loading' : state}>{pending ? 'Working…' : stateText}</StatePill>}
        {stopped && <button className="button button-primary" disabled={!canStart} title={!fresh ? 'A fresh telemetry sample is required.' : !host?.loading_enabled ? host?.loading_reason : !valid ? 'Fix the highlighted settings first.' : undefined} onClick={() => void onRun(runtime, 'start', launch)}><ArrowUpRight size={16} />Start</button>}
        {running && <button className="button button-secondary" disabled={pending || !fresh} onClick={() => void onRun(runtime, 'stop')}><X size={16} />Stop</button>}
        <button type="button" className="icon-button runtime-toggle" aria-expanded={open} aria-controls={detailsId} aria-label={`${open ? 'Hide' : 'Show'} details for ${runtime.name}`} title={open ? 'Hide details' : 'Details and settings'} onClick={() => setOpen(!open)}><ChevronDown size={18} className={open ? 'chevron-open' : ''} /></button>
      </div></div></div>
    {open && <div className="runtime-details" id={detailsId}>
    {runtime.description && <p className="runtime-description">{runtime.description}</p>}

    <div className={`runtime-body ${aside ? 'runtime-body-split' : ''}`}><div className="runtime-controls">
    {Object.keys(runtime.presets).length > 1 && <fieldset className="runtime-choice" disabled={!stopped || pending}>
      <legend>Model</legend>
      {Object.entries(runtime.presets).map(([key, item]) => <label key={key} title={item.name} className={`runtime-option ${launch.preset === key ? 'runtime-option-on' : ''}`}><input type="radio" name={`${runtime.id}-preset`} checked={launch.preset === key} onChange={() => choosePreset(key)} /><span>{item.name}</span></label>)}
      {preset?.description && <p className="runtime-preset-description">{preset.description}</p>}
    </fieldset>}

    {cardNote && <p className="runtime-preset-description">{cardNote}</p>}

    {stopped && need && <div className="runtime-fit" aria-label={`${runtime.name} if started`}>
      <span className="runtime-fit-head">If you start it</span>
      {fits.map((fit) => <div className="runtime-fit-row" key={fit.key}>
        <strong>{fit.label === 'RAM' ? 'RAM' : `${fit.label} VRAM`}</strong>
        <span>needs {formatBytes(fit.need)}, {fit.free == null ? 'free amount unknown' : `${formatBytes(fit.free)} free after ${formatBytes(fit.headroom)} headroom`}</span>
        {fit.fits === true ? <span className="fit-yes"><Check size={16} />Fits</span>
          : fit.fits === false ? <span className="fit-no"><X size={16} />{formatBytes(fit.need - (fit.free ?? 0))} short</span>
            : <span className="fit-unknown"><HelpCircle size={16} />Unknown</span>}
      </div>)}
      <p className="runtime-fit-note">These are estimates. The host checks again when you press Start.{runtime.chat ? ' A text model then uses whatever VRAM is free beyond what you leave free.' : ''}</p>
    </div>}
    {stopped && needError && <p className="runtime-fit-error" role="status"><AlertCircle size={16} />{needError}</p>}

    {preset && essentials.length > 0 && <div className="runtime-settings runtime-settings-main">{essentials.map(settingField)}</div>}
    {preset && advancedSettings.length > 0 && <div className="runtime-advanced">
      <button type="button" className="text-button" aria-expanded={advanced} onClick={() => setAdvanced(!advanced)}><ChevronDown size={16} className={advanced ? 'chevron-open' : ''} /> Advanced settings</button>
      {advanced && <div className="runtime-settings">
        {advancedSettings.map(settingField)}
        <div className="runtime-settings-actions"><button type="button" className="button button-secondary" disabled={!stopped || pending} onClick={reset}>Reset to defaults</button></div>
      </div>}
    </div>}

    {usage && !stopped && <p className="runtime-usage" aria-label={`${runtime.name} memory use`}>
      <span className="usage-swatch" style={{ background: color }} />
      <span>Using {formatBytes(usage.ram_bytes)} of RAM{Object.entries(usage.gpus).filter(([, bytes]) => bytes > 0).map(([id, bytes]) => ` · ${formatBytes(bytes)} on the ${host?.gpus.find((gpu) => gpu.id === id)?.name ?? 'GPU'}`).join('')}</span>
      {usage.error && <small>{usage.error}</small>}
    </p>}
    {refusal && <RefusalDetails refusal={refusal} gpus={host?.gpus} />}
    {message && <p className="runtime-message" aria-live="polite">{message}</p>}
    </div>{aside && <div className="runtime-aside">{aside}</div>}</div>
    <div className="profile-card-footer"><span className="worker-caption">{running && model ? 'Running. Stop it to free its RAM and VRAM.' : stopped ? 'Stopped. Nothing is using memory.' : 'Working. This can take several minutes.'}</span><div className="profile-actions">
      {openHref && state === 'ready' && <a className="button button-secondary" href={openHref}>Open {runtime.name}</a>}
    </div></div>
    </div>}
  </article>
}

