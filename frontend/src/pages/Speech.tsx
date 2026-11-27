import { useCallback, useEffect, useState } from 'react'
import type { FormHooks } from '../components/Runtime'
import { LICENSE_WORD } from '../components/Runtime'
import type { SavedHost } from '../hosts'
import { dropped } from '../roleDraft'
import { removeCues, speechKit, strayCues, unknownCues } from '../speechDraft'
import type { HostStore } from '../store'
import type { Runtime, Voice } from '../types'
import type { FileItem } from '../components/FilePicker'
import { VoiceLibrary } from '../components/VoiceLibrary'
import { ServicePage } from './Service'
import { type Member, useConsolidated } from './useConsolidated'

const insert = (cue: string) => (current: string, start: number | null, end: number | null) => {
  const at = start ?? current.length
  const before = current.slice(0, at)
  return `${before}${before && !/\s$/.test(before) ? ' ' : ''}${cue} ${current.slice(end ?? at)}`.replace(/ $/, '')
}

const memberOf = (runtime: Runtime): Member | undefined => {
  const speech = runtime.generation?.speech
  return runtime.workload === 'speech' && speech ? { kit: speechKit(speech), modes: (runtime.generation?.modes ?? []).map((item) => item.key) } : undefined
}

/** One page for every speech model, like Chat for text models. What is typed (text, language, voice, direction) is kept
 * by role, so changing the model or the voice source carries it over; only what the new model has no place for is left out. */
export function SpeechPage({ store, host, modelId }: { store: HostStore; host?: SavedHost; modelId?: string }) {
  const { start, state, runtimes, running, chosen, chosenId, member, mode, draft, draftRef, update, form, hooks: shared, setPickedId, rebuild, reuseElsewhere } = useConsolidated(store, host, modelId, memberOf)
  const [command, setCommand] = useState<FormHooks['command']>()
  const session = host ? store.session(host.id) : undefined
  const [voices, setVoices] = useState<Voice[]>([])
  const loadVoices = useCallback(() => { void session?.listVoices().then(setVoices, () => undefined) }, [session])
  useEffect(() => { if (state.connection === 'connected') loadVoices() }, [state.connection, loadVoices])
  const speech = chosen?.generation?.speech ?? undefined
  const hooks: FormHooks = { ...shared, command, transcribe: session && chosenId ? (uploadId) => session.transcribe(chosenId, uploadId) : undefined }

  const textField = speech?.roles[mode]?.text
  const text = draft.values.text ?? ''
  const stray = speech ? strayCues(text, speech) : []
  const unknown = speech ? unknownCues(text, speech) : []
  const left = member && mode ? dropped(draft, member.kit, mode) : ''
  const cues = speech?.direction.cues
  const send = (apply: (current: string, start: number | null, end: number | null) => string) => textField && setCommand((current) => ({ n: (current?.n ?? 0) + 1, mode, field: textField, apply }))

  const picker = <div className="decide-picker-row">
    {running.length > 1 && <label className="decide-picker"><span>Model speaking</span>
      <select aria-label="Model speaking" value={chosen?.id} onChange={(event) => setPickedId(event.target.value)}>
        {running.map((runtime) => <option key={runtime.id} value={runtime.id}>{runtime.name} ({runtime.license ? LICENSE_WORD[runtime.license.use] : 'Licence not reviewed'})</option>)}</select></label>}
  </div>

  const canClone = !!speech?.voices.clone
  const extension: Record<string, string> = { 'audio/wav': '.wav', 'audio/mpeg': '.mp3', 'audio/flac': '.flac', 'audio/mp4': '.m4a', 'audio/ogg': '.ogg' }
  const library = session && speech ? <VoiceLibrary voices={voices} canClone={canClone} modelName={chosen?.name ?? ''} sampleReady={(draft.files.sample ?? []).some((item) => item.id)}
    onUse={async (voice) => {
      try {
        const blob = await session.voiceBlob(voice.id)
        const name = `${voice.name}${extension[voice.mime] ?? '.wav'}`
        const record = await session.uploadFile(new File([blob], name, { type: voice.mime }))
        const sample: FileItem = { key: `voice-${voice.id}-${record.id}`, name, kind: 'audio', url: URL.createObjectURL(blob), status: 'ready', id: record.id }
        update({ values: { ...draftRef.current.values, sample_text: voice.sample_text }, files: { ...draftRef.current.files, sample: [sample] } })
        rebuild(chosen, 'clone')
        return ''
      } catch (reason) { return reason instanceof Error ? reason.message : 'The voice could not be used.' }
    }}
    onSaveSample={async (name) => {
      const sample = (draftRef.current.files.sample ?? []).find((item) => item.id)
      if (!sample?.id) return 'There is no sample on the form.'
      try { await session.saveVoice(name, draftRef.current.values.sample_text ?? '', sample.id); loadVoices(); return '' } catch (reason) { return reason instanceof Error ? reason.message : 'The voice could not be saved.' }
    }}
    onUpdate={async (voice, name, text) => { try { await session.updateVoice(voice.id, name, text); loadVoices(); return '' } catch (reason) { return reason instanceof Error ? reason.message : 'The voice could not be changed.' } }}
    onDelete={async (voice) => { try { await session.deleteVoice(voice.id); loadVoices(); return '' } catch (reason) { return reason instanceof Error ? reason.message : 'The voice could not be deleted.' } }} /> : null

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
    {library}
  </div> : null

  return <ServicePage store={store} host={host} modelId={chosen?.id ?? ''}
    group={{
      title: 'Speech', noun: 'speech', description: 'Turn text into speech with whichever speech model is running. What you type carries over when you change the model.',
      ids: runtimes.map((runtime) => runtime.id), picker, above, onVoiceSaved: loadVoices, none: runtimes.length > 0 && running.length === 0,
      form: { key: `${chosenId}:${form.n}`, start, hooks }, reuseElsewhere,
    }} />
}
