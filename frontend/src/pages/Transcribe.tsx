import { LICENSE_WORD } from '../components/Runtime'
import type { SavedHost } from '../hosts'
import { dropped } from '../roleDraft'
import type { HostStore } from '../store'
import type { Runtime } from '../types'
import { transcribeKit } from '../transcribeDraft'
import { ServicePage } from './Service'
import { type Member, useConsolidated } from './useConsolidated'

const memberOf = (runtime: Runtime): Member | undefined => {
  const transcribe = runtime.generation?.transcribe
  return transcribe ? { kit: transcribeKit(transcribe), modes: Object.keys(transcribe.roles) } : undefined
}

const SPEAKERS = 'Who spoke is found by a separate step that listens for changes of voice, and the labels are laid over the text.'

/** One page for every speech-to-text model, like Music for song models: the recording, the language, the words to expect and who spoke
 * are kept by role, so changing the model carries them over; only what the new model has no place for is left out. */
export function TranscribePage({ store, host, modelId }: { store: HostStore; host?: SavedHost; modelId?: string }) {
  const { start, runtimes, running, chosen, chosenId, member, mode, draft, form, hooks, setPickedId, reuseElsewhere } = useConsolidated(store, host, modelId, memberOf)
  const transcribe = chosen?.generation?.transcribe ?? undefined
  const left = member ? dropped(draft, member.kit, mode) : ''
  const picker = <div className="decide-picker-row">
    {running.length > 1 && <label className="decide-picker"><span>Model transcribing</span>
      <select aria-label="Model transcribing" value={chosenId} onChange={(event) => setPickedId(event.target.value)}>
        {running.map((runtime) => <option key={runtime.id} value={runtime.id}>{runtime.name} ({runtime.license ? LICENSE_WORD[runtime.license.use] : 'Licence not reviewed'})</option>)}</select></label>}
  </div>
  const above = transcribe && chosen ? <div className="speech-guidance" aria-label="About this model">
    <p>{transcribe.guidance}</p>
    <p>{transcribe.times === 'lines' ? 'Each line has its time, and captions (.srt and .vtt) are written.' : 'There are no times, so no captions are written.'}{' '}{transcribe.speakers === 'turns' ? SPEAKERS : 'This model does not label speakers.'}</p>
    {left && <p className="speech-notice" role="status">{chosen.name} has no place for {left}, so {left.includes(' and ') || left.includes(',') ? 'they are' : 'it is'} left out here and kept for when you switch back.</p>}
  </div> : null
  return <ServicePage store={store} host={host} modelId={chosen?.id ?? ''}
    group={{
      title: 'Transcribe', noun: 'transcript', description: 'Write down a recording with whichever speech-to-text model is running. What you choose carries over when you change the model.',
      ids: runtimes.map((runtime) => runtime.id), picker, above, reuseElsewhere, none: runtimes.length > 0 && running.length === 0,
      form: { key: `${chosenId}:${form.n}`, start, hooks },
    }} />
}
