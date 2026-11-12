import { useEffect, useState } from 'react'
import { AlertCircle, ArrowUpRight, ChevronDown, Server, Sparkles, X } from 'lucide-react'
import type { Generation, Host, InputField, Job, JobOutput, Launch, Model, Refusal, Runtime, RuntimeSetting, SettingValue } from '../types'
import { RefusalDetails } from './Refusal'

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
  onGenerate: (runtime: Runtime, inputs: Record<string, string | number | null>) => Promise<boolean>
  fileUrl: (job: Job, output: JobOutput) => Promise<string>
}

export const makeLabel: Record<string, string> = { audio: 'Make a song', image: 'Make a picture', video: 'Make a video' }

export function GenerateForm({ runtime, generation, onGenerate, error }: { runtime: Runtime; generation: Generation; error?: string; onGenerate: GenerateHandlers['onGenerate'] }) {
  const [values, setValues] = useState<Record<string, string>>(() => Object.fromEntries(generation.inputs.map((field) => [field.key, field.default == null ? '' : String(field.default)])))
  const [advanced, setAdvanced] = useState(false)
  const [sending, setSending] = useState(false)
  const problem = (field: InputField) => {
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
  const valid = generation.inputs.every((field) => !problem(field))
  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!valid) return
    const inputs: Record<string, string | number | null> = {}
    for (const field of generation.inputs) {
      const raw = (values[field.key] ?? '').trim()
      if (!raw) continue
      inputs[field.key] = field.kind === 'int' || field.kind === 'seed' ? Number(raw) : raw
    }
    setSending(true)
    await onGenerate(runtime, inputs)
    setSending(false)
  }
  const renderField = (field: InputField) => {
    const id = `${runtime.id}-input-${field.key}`
    const value = values[field.key] ?? ''
    const set = (next: string) => setValues((current) => ({ ...current, [field.key]: next }))
    return <label className={`field ${field.kind === 'textarea' ? 'field-wide' : ''}`} key={field.key} htmlFor={id}>
      <span>{field.label.toUpperCase()}{field.required ? '' : ' (OPTIONAL)'}</span>
      {field.kind === 'textarea' ? <textarea id={id} className="text-input generate-textarea" rows={10} maxLength={field.max_length ?? undefined} placeholder={field.placeholder ?? undefined} value={value} onChange={(event) => set(event.target.value)} />
        : field.kind === 'choice' ? <select id={id} className="text-input" value={value} onChange={(event) => set(event.target.value)}>{field.options.map((option) => <option key={option} value={option}>{option}</option>)}</select>
          : <input id={id} className="text-input" type={field.kind === 'text' ? 'text' : 'number'} step={field.kind === 'text' ? undefined : 1} maxLength={field.max_length ?? undefined} placeholder={field.placeholder ?? (field.kind === 'seed' ? 'Random' : undefined)} value={value} onChange={(event) => set(event.target.value)} />}
      <small className={problem(field) && value ? 'field-problem' : ''}>{(value && problem(field)) || field.help}</small>
    </label>
  }
  const basic = generation.inputs.filter((field) => !field.advanced)
  const extra = generation.inputs.filter((field) => field.advanced)
  return <form className="generate-form" onSubmit={submit} aria-label={makeLabel[generation.output_kind] ?? 'Make something'}>
    <div className="generate-fields">{basic.map(renderField)}</div>
    {extra.length > 0 && <><button type="button" className="text-button" aria-expanded={advanced} onClick={() => setAdvanced(!advanced)}><ChevronDown size={14} className={advanced ? 'chevron-open' : ''} /> More options</button>
      {advanced && <div className="generate-fields">{extra.map(renderField)}</div>}</>}
    {error && <div className="form-error" role="alert"><AlertCircle size={15} />{error}</div>}
    <div className="generate-actions"><button className="button button-primary" type="submit" disabled={!valid || sending}><Sparkles size={15} />{sending ? 'Sending…' : makeLabel[generation.output_kind] ?? 'Make it'}</button></div>
  </form>
}

export function JobList({ jobs, fileUrl }: { jobs: Job[]; fileUrl: GenerateHandlers['fileUrl'] }) {
  if (jobs.length === 0) return null
  return <div className="job-list" aria-label="Results">{jobs.map((job) => <JobRow key={job.id} job={job} fileUrl={fileUrl} />)}</div>
}

export function JobRow({ job, fileUrl }: { job: Job; fileUrl: GenerateHandlers['fileUrl'] }) {
  const [urls, setUrls] = useState<Record<string, string>>({})
  const [error, setError] = useState('')
  const media = job.outputs.filter((output) => /^(audio|image|video)\//.test(output.mime))
  useEffect(() => {
    if (job.status !== 'done') return
    let cancelled = false
    const made: string[] = []
    void Promise.all(media.map(async (output) => {
      const url = await fileUrl(job, output)
      made.push(url)
      if (!cancelled) setUrls((current) => ({ ...current, [output.name]: url }))
    })).catch((reason) => { if (!cancelled) setError(reason instanceof Error ? reason.message : 'The file could not be loaded.') })
    return () => { cancelled = true; made.forEach((url) => URL.revokeObjectURL(url)) }
    // Load each finished job's files once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job.id, job.status])
  const title = typeof job.inputs.style === 'string' ? job.inputs.style : typeof job.inputs.prompt === 'string' ? job.inputs.prompt : 'Untitled'
  const statusText = { queued: 'Waiting its turn', running: job.progress ?? 'Working', done: job.progress ?? 'Done', failed: 'Did not work' }[job.status] ?? job.status
  return <article className={`job-row job-${job.status}`}>
    <div className="job-head"><strong>{title}</strong><span className={`model-state state-${job.status === 'done' ? 'ready' : job.status === 'failed' ? 'error' : 'loading'}`}>{statusText}</span></div>
    {job.status === 'failed' && job.error_message && <small className="operation-error">{job.error_message}</small>}
    {error && <small className="operation-error">{error}</small>}
    {media.map((output) => <div className="job-media" key={output.name}>
      {urls[output.name] ? (output.mime.startsWith('audio/') ? <audio controls src={urls[output.name]} aria-label={`Play ${title}`} />
        : output.mime.startsWith('image/') ? <img src={urls[output.name]} alt={title} />
          : <video controls src={urls[output.name]} />) : <small>Loading…</small>}
      {urls[output.name] && <a className="text-button" href={urls[output.name]} download={output.name}>Download {output.name}</a>}
    </div>)}
  </article>
}

export function RuntimeCard({ runtime, model, host, fresh, pending, refusal, message, onRun, jobs, jobErrors, onGenerate, fileUrl }: {
  runtime: Runtime; model?: Model; host?: Host; fresh: boolean; pending: boolean; refusal?: Refusal; message?: string
  onRun: (runtime: Runtime, action: 'start' | 'stop', launch?: Launch) => Promise<void>
} & GenerateHandlers) {
  const initialPreset = runtime.last_launch?.preset && runtime.presets[runtime.last_launch.preset] ? runtime.last_launch.preset : runtime.default_preset
  const [launch, setLaunch] = useState<Launch>(() => defaultLaunch(runtime, initialPreset))
  const [advanced, setAdvanced] = useState(false)
  const preset = runtime.presets[launch.preset]
  const state = model?.state ?? 'unknown'
  const stopped = ['unloaded', 'error'].includes(state)
  const running = ['ready', 'cleanup_failed'].includes(state)
  const problems = Object.fromEntries((preset?.settings ?? []).map((setting) => [setting.key, settingProblem(setting, launch.settings[setting.key] ?? null)]))
  const valid = !!preset && launch.gpus.length > 0 && Object.values(problems).every((problem) => !problem)
  const canStart = fresh && host?.loading_enabled === true && stopped && valid && !pending
  const gpuName = (index: number) => preset?.allowed_gpus.find((gpu) => gpu.index === index)?.name ?? `GPU ${index}`
  const budget = launch.settings.resident_budget_gib
  const ramNeed = (preset?.estimate.ram_gib ?? 0) + (typeof budget === 'number' ? budget : 0)
  const stateText = ({ unloaded: 'Stopped', loading: 'Loading', ready: 'Running', unloading: 'Stopping', error: 'Stopped after an error', cleanup_failed: 'Stop did not finish' } as Record<string, string>)[state] ?? state
  const setValue = (key: string, value: SettingValue) => setLaunch((current) => ({ ...current, settings: { ...current.settings, [key]: value } }))
  const choosePreset = (key: string) => setLaunch(defaultLaunch(runtime, key))
  const reset = () => setLaunch(defaultLaunch({ ...runtime, last_launch: null }, launch.preset))

  return <article className="profile-card runtime-card">
    <div className="profile-card-main"><div className="model-icon"><Server size={18} /></div><div className="profile-card-title"><div><strong>{runtime.name}</strong><span className="profile-id">{runtime.workload} · port {runtime.port}</span></div><span className={`model-state state-${state}`}>{pending ? 'Working…' : stateText}</span></div></div>

    <fieldset className="runtime-choice" disabled={!stopped || pending}>
      <legend>Model</legend>
      {Object.entries(runtime.presets).map(([key, item]) => <label key={key} className={`runtime-option ${launch.preset === key ? 'runtime-option-on' : ''}`}><input type="radio" name={`${runtime.id}-preset`} checked={launch.preset === key} onChange={() => choosePreset(key)} /><span>{item.name}</span></label>)}
    </fieldset>

    {preset && <fieldset className="runtime-choice" disabled={!stopped || pending}>
      <legend>GPUs</legend>
      {preset.allowed_gpus.map((gpu) => <label key={gpu.index} className={`runtime-option ${launch.gpus.includes(gpu.index) ? 'runtime-option-on' : ''}`}>{runtime.max_gpus === 1
        ? <input type="radio" name={`${runtime.id}-gpu`} checked={launch.gpus.includes(gpu.index)} onChange={() => setLaunch((current) => ({ ...current, gpus: [gpu.index] }))} />
        : <input type="checkbox" checked={launch.gpus.includes(gpu.index)} onChange={(event) => setLaunch((current) => ({ ...current, gpus: event.target.checked ? [...current.gpus, gpu.index].sort() : current.gpus.filter((item) => item !== gpu.index) }))} />}<span>{gpu.name}</span></label>)}
      {launch.gpus.length === 0 && <small className="field-problem">Choose at least one GPU.</small>}
    </fieldset>}

    {preset && <p className="runtime-estimate">Needs about {launch.gpus.map((index) => `${preset.estimate.gpu_min_free_gib[String(index)] ?? 0} GiB free on the ${gpuName(index)}`).join(', ')} and {ramNeed} GiB of RAM. These are estimates; Basalt uses whatever VRAM is free beyond its reserve.</p>}

    {preset && <div className="runtime-advanced">
      <button type="button" className="text-button" aria-expanded={advanced} onClick={() => setAdvanced(!advanced)}><ChevronDown size={14} className={advanced ? 'chevron-open' : ''} /> Advanced settings</button>
      {advanced && <div className="runtime-settings">
        {preset.settings.map((setting) => {
          const value = launch.settings[setting.key] ?? null
          const id = `${runtime.id}-${setting.key}`
          return <label className="field" key={setting.key} htmlFor={id}>
            <span>{setting.label.toUpperCase()}{setting.unit ? ` (${setting.unit})` : ''}</span>
            {setting.kind === 'bool' ? <input id={id} type="checkbox" disabled={!stopped || pending} checked={value === true} onChange={(event) => setValue(setting.key, event.target.checked)} />
              : setting.kind === 'choice' ? <select id={id} className="text-input" disabled={!stopped || pending} value={String(value ?? '')} onChange={(event) => setValue(setting.key, event.target.value)}>{(setting.options ?? []).map((option) => <option key={option} value={option}>{option}</option>)}</select>
              : <input id={id} className="text-input" type="number" step={1} min={setting.minimum ?? undefined} max={setting.maximum ?? undefined} disabled={!stopped || pending}
                  placeholder={setting.kind === 'optional_int' ? 'Automatic' : undefined} value={value === null ? '' : String(value)}
                  onChange={(event) => setValue(setting.key, event.target.value === '' ? null : Number(event.target.value))} />}
            <small className={problems[setting.key] ? 'field-problem' : ''}>{problems[setting.key] || setting.help}</small>
            {setting.key === 'ram_reserve_mib' && value === 0 && <small className="field-warning">The RAM guard is off. Fine when Basalt is the only thing running; risky when other models or games need RAM.</small>}
          </label>
        })}
        <div className="runtime-settings-actions"><button type="button" className="button button-secondary" disabled={!stopped || pending} onClick={reset}>Reset to defaults</button></div>
      </div>}
    </div>}

    {refusal && <RefusalDetails refusal={refusal} gpus={host?.gpus} />}
    {message && <p className="runtime-message" aria-live="polite">{message}</p>}
    {runtime.generation && state === 'ready' && <GenerateForm runtime={runtime} generation={runtime.generation} onGenerate={onGenerate} error={jobErrors[runtime.id]} />}
    {runtime.generation && <JobList jobs={jobs.filter((job) => job.model_id === runtime.id)} fileUrl={fileUrl} />}
    <div className="profile-card-footer"><span className="worker-caption">{running && model ? 'Running. Stop it to free its RAM and VRAM.' : stopped ? 'Stopped. Nothing is using memory.' : 'Working. This can take several minutes.'}</span><div className="profile-actions">
      {stopped && <button className="button button-primary" disabled={!canStart} title={!fresh ? 'A fresh telemetry sample is required.' : !host?.loading_enabled ? host?.loading_reason : !valid ? 'Fix the highlighted settings first.' : undefined} onClick={() => void onRun(runtime, 'start', launch)}><ArrowUpRight size={14} />{state === 'error' ? 'Start again' : 'Start'}</button>}
      {running && <button className="button button-secondary" disabled={pending || !fresh} onClick={() => void onRun(runtime, 'stop')}><X size={14} />Stop</button>}
      {!stopped && !running && <button className="button button-secondary" disabled>{stateText}…</button>}
    </div></div>
  </article>
}

