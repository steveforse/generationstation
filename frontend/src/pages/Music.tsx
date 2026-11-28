import { useState } from 'react'
import type { FormHooks } from '../components/Runtime'
import { LICENSE_WORD } from '../components/Runtime'
import type { SavedHost } from '../hosts'
import { LYRIC_TAGS, musicKit } from '../musicDraft'
import { dropped } from '../roleDraft'
import type { HostStore } from '../store'
import type { Runtime } from '../types'
import type { FileItem } from '../components/FilePicker'
import { ServicePage } from './Service'
import { type Member, useConsolidated } from './useConsolidated'

const insert = (tag: string) => (current: string, start: number | null, end: number | null) => {
  const at = start ?? current.length
  const before = current.slice(0, at)
  const lead = before && !before.endsWith('\n\n') ? (before.endsWith('\n') ? '\n' : '\n\n') : ''
  return `${before}${lead}${tag}\n${current.slice(end ?? at)}`
}

const memberOf = (runtime: Runtime): Member | undefined => {
  const music = runtime.generation?.music
  return music ? { kit: musicKit(music), modes: (runtime.generation?.modes ?? []).map((item) => item.key).concat(runtime.generation?.modes?.length ? [] : Object.keys(music.roles)) } : undefined
}

/** One page for every song model, like Speech for speech models: what is typed (style, lyrics, length, tempo, a song to start from) is kept
 * by role, so changing the model carries it over; only what the new model has no place for is left out. */
export function MusicPage({ store, host, modelId }: { store: HostStore; host?: SavedHost; modelId?: string }) {
  const { start, runtimes, running, chosen, chosenId, member, mode, draft, draftRef, update, form, hooks: shared, setPickedId, rebuild, reuseElsewhere } = useConsolidated(store, host, modelId, memberOf)
  const [command, setCommand] = useState<FormHooks['command']>()
  const music = chosen?.generation?.music ?? undefined
  const hooks: FormHooks = { ...shared, command }
  const lyricsField = music?.roles[mode]?.lyrics
  const left = member ? dropped(draft, member.kit, mode) : ''
  const send = (apply: (current: string, start: number | null, end: number | null) => string) => lyricsField && setCommand((current) => ({ n: (current?.n ?? 0) + 1, mode, field: lyricsField, apply }))
  const picker = <div className="decide-picker-row">
    {running.length > 1 && <label className="decide-picker"><span>Model composing</span>
      <select aria-label="Model composing" value={chosenId} onChange={(event) => setPickedId(event.target.value)}>
        {running.map((runtime) => <option key={runtime.id} value={runtime.id}>{runtime.name} ({runtime.license ? LICENSE_WORD[runtime.license.use] : 'Licence not reviewed'})</option>)}</select></label>}
  </div>
  const above = music && chosen ? <div className="speech-guidance" aria-label="Describing a song">
    <p>{music.guidance}</p>
    {lyricsField && <div className="speech-cues"><span>Parts of a song:</span>
      {LYRIC_TAGS.map((tag) => <button key={tag} type="button" className="chip" onClick={() => send(insert(tag))}>{tag}</button>)}</div>}
    {left && <p className="speech-notice" role="status">{chosen.name} has no place for {left}, so {left.includes(' and ') ? 'they are' : 'it is'} left out here and kept for when you switch back.</p>}
  </div> : null
  // A finished song can become the song to start from when the chosen model makes new versions or redoes sections.
  const canStart = !!music && (music.cover !== null || music.repaint !== null)
  const useSong = canStart ? (file: FileItem) => { update({ values: draftRef.current.values, files: { ...draftRef.current.files, source: [file] } }); rebuild(chosen, 'cover') } : undefined
  return <ServicePage store={store} host={host} modelId={chosen?.id ?? ''}
    group={{
      title: 'Music', noun: 'song', description: 'Make songs with whichever song model is running. What you type carries over when you change the model.',
      ids: runtimes.map((runtime) => runtime.id), picker, above, reuseElsewhere, useSong, none: runtimes.length > 0 && running.length === 0,
      form: { key: `${chosenId}:${form.n}`, start, hooks },
    }} />
}
