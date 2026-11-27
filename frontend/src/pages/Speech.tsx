import { useEffect, useRef, useState } from 'react'
import type { FormHooks, FormStart } from '../components/Runtime'
import { LICENSE_WORD } from '../components/Runtime'
import type { SavedHost } from '../hosts'
import { absorb, dropped, emptyDraft, modeFor, removeCues, sourceOf, startFor, strayCues, unknownCues, type Draft } from '../speechDraft'
import { type HostStore, useSession } from '../store'
import type { Job, Runtime } from '../types'
import { takeHandOff } from '../voiceSample'
import { ServicePage, usable } from './Service'

const insert = (cue: string) => (current: string, start: number | null, end: number | null) => {
  const at = start ?? current.length
  const before = current.slice(0, at)
  return `${before}${before && !/\s$/.test(before) ? ' ' : ''}${cue} ${current.slice(end ?? at)}`.replace(/ $/, '')
}

/** One page for every speech model, like Chat for text models. What is typed (text, language, voice, direction) is kept
 * by role, so changing the model or the voice source carries it over; only what the new model has no place for is left out. */
export function SpeechPage({ store, host, modelId }: { store: HostStore; host?: SavedHost; modelId?: string }) {
  const state = useSession(host ? store.session(host.id) : undefined)
  const [pickedId, setPickedId] = useState<string | null>(modelId ?? null)
  const [workOnly, setWorkOnly] = useState(false)
  const [draft, setDraft] = useState<Draft>(emptyDraft)
  const draftRef = useRef(draft)
  const [form, setForm] = useState<{ n: number; mode?: string }>({ n: 0 })
  const modeRef = useRef('')
  const [picked, setMode] = useState('')
  const [command, setCommand] = useState<FormHooks['command']>()
  const speechRuntimes = (state.runtimes ?? []).filter((runtime) => runtime.workload === 'speech' && runtime.generation?.speech)
  const running = speechRuntimes.filter((runtime) => state.models?.find((model) => model.id === runtime.id)?.state === 'ready')
  const offered = running.filter((runtime) => !workOnly || usable('work', runtime))
  const chosen = offered.find((runtime) => runtime.id === pickedId) ?? offered[0] ?? speechRuntimes.find((runtime) => runtime.id === pickedId) ?? speechRuntimes[0]
  const speech = chosen?.generation?.speech ?? undefined
  const chosenId = chosen?.id
  const mode = chosen?.generation?.modes?.some((item) => item.key === picked) ? picked : chosen?.generation?.modes?.[0]?.key ?? ''
  modeRef.current = mode

  const update = (next: Draft) => { draftRef.current = next; setDraft(next) }
  // A model chosen or a tab opened carries the draft over: the form is rebuilt from it, on the tab for the voice source in use.
  const rebuild = (runtime: Runtime | undefined, fromSource: string | undefined, fallbackMode?: string) => {
    const info = runtime?.generation?.speech
    if (!info) return
    const first = runtime!.generation!.modes?.[0]?.key ?? ''
    modeRef.current = modeFor(info, fromSource, fallbackMode ?? first)
    setMode(modeRef.current)
    setForm((current) => ({ n: current.n + 1, mode: modeRef.current }))
  }
  const previous = useRef<string | undefined>(undefined)
  const lastMode = useRef('')  // the tab open at the last render, which is the old model's when the model changes
  useEffect(() => {
    if (!chosenId || previous.current === chosenId) { previous.current = chosenId; return }
    const had = previous.current
    previous.current = chosenId
    if (!had) return
    const before = speechRuntimes.find((runtime) => runtime.id === had)?.generation?.speech
    rebuild(chosen, before ? sourceOf(before, lastMode.current) : undefined)
  }, [chosenId]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { lastMode.current = mode })

  // A voice sent from another page (a clip's soundtrack, "use these settings" in Chat) arrives once the models are listed.
  const taken = useRef(false)
  useEffect(() => {
    if (!host || taken.current || !speechRuntimes.length) return
    taken.current = true
    for (const runtime of speechRuntimes) {
      const start = takeHandOff(host.id, runtime.id)
      const info = runtime.generation?.speech
      if (!start || !info) continue
      const mode = start.mode ?? runtime.generation!.modes?.[0]?.key ?? ''
      const values = Object.fromEntries(Object.entries(start.inputs ?? {}).map(([key, value]) => [key, Array.isArray(value) || value == null ? '' : String(value)]))
      update(absorb(draftRef.current, info, mode, values, start.files ?? {}))
      setPickedId(runtime.id)
      modeRef.current = mode; setMode(mode)
      setForm((current) => ({ n: current.n + 1, mode }))
      break
    }
  }, [speechRuntimes.length, host?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  const starts: Record<string, FormStart> = {}
  if (speech && chosen) for (const key of Object.keys(speech.roles)) starts[key] = startFor(draft, speech, key)
  const hooks: FormHooks = {
    starts,
    onValues: (formMode, values, files) => { if (speech) update(absorb(draftRef.current, speech, formMode, values, files)) },
    // A tab was opened by hand: rebuild so it starts from what the other tab held.
    onMode: (next) => { modeRef.current = next; setMode(next); setForm((current) => ({ n: current.n + 1, mode: next })) },
    command,
  }
  const textField = speech?.roles[mode]?.text
  const text = draft.values.text ?? ''
  const stray = speech ? strayCues(text, speech) : []
  const unknown = speech ? unknownCues(text, speech) : []
  const left = speech && mode ? dropped(draft, speech, mode) : ''
  const cues = speech?.direction.cues
  const send = (apply: (current: string, start: number | null, end: number | null) => string) => textField && setCommand((current) => ({ n: (current?.n ?? 0) + 1, mode, field: textField, apply }))

  const picker = <div className="decide-picker-row">
    {offered.length > 1 && <label className="decide-picker"><span>Model speaking</span>
      <select aria-label="Model speaking" value={chosen?.id} onChange={(event) => setPickedId(event.target.value)}>
        {offered.map((runtime) => <option key={runtime.id} value={runtime.id}>{runtime.name} ({LICENSE_WORD[runtime.license?.use ?? 'personal'] ?? 'Licence not reviewed'})</option>)}</select></label>}
    {running.some((runtime) => !usable('work', runtime)) && <label className="checkbox-row"><input type="checkbox" checked={workOnly} onChange={(event) => setWorkOnly(event.target.checked)} /> Work use only</label>}
  </div>

  const above = speech && chosen ? <div className="speech-guidance" aria-label="Directing this voice">
    <p>{speech.direction.text}</p>
    {speech.direction.style_fields[mode] && speech.direction.examples.length > 0 && <p className="speech-examples">Examples: {speech.direction.examples.join(' · ')}</p>}
    {cues && textField && <div className="speech-cues"><span>{cues.text}</span>
      {cues.examples.map((cue) => <button key={cue} type="button" className="chip" onClick={() => send(insert(cue))}>{cue}</button>)}</div>}
    {stray.length > 0 && <p className="speech-notice" role="status">{chosen.name} would read {stray.join(' ')} aloud; it has no cues in the text.
      {' '}<button type="button" className="text-button" onClick={() => send((current) => removeCues(current, stray))}>Remove cues</button></p>}
    {unknown.length > 0 && <p className="speech-notice" role="status">{chosen.name} does not know {unknown.join(' ')}.
      {' '}<button type="button" className="text-button" onClick={() => send((current) => removeCues(current, unknown))}>Remove them</button></p>}
    {left && <p className="speech-notice" role="status">This voice source has no place for {left}, so it is left out here and kept for when you switch back.</p>}
  </div> : null

  const reuseElsewhere = (job: Job) => {
    const target = speechRuntimes.find((runtime) => runtime.id === job.model_id)
    const info = target?.generation?.speech
    if (!target || !info) return
    const jobMode = typeof job.inputs.mode === 'string' ? job.inputs.mode : target.generation!.modes?.[0]?.key ?? ''
    const values = Object.fromEntries(Object.entries(job.inputs).map(([key, value]) => [key, Array.isArray(value) || value == null || typeof value === 'object' ? '' : String(value)]))
    update(absorb(draftRef.current, info, jobMode, values, {}))
    setPickedId(target.id)
    if (target.id === chosenId) rebuild(target, sourceOf(info, jobMode), jobMode)
  }

  return <ServicePage store={store} host={host} modelId={chosen?.id ?? ''}
    group={{
      title: 'Speak', noun: 'speech', description: 'Turn text into speech with whichever speech model is running. What you type carries over when you change the model.',
      ids: speechRuntimes.map((runtime) => runtime.id), picker, above, none: speechRuntimes.length > 0 && running.length === 0,
      form: { key: `${chosenId}:${form.n}`, start: { mode: form.mode ?? undefined }, hooks }, reuseElsewhere,
    }} />
}
