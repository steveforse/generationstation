import type { FileItem } from '../components/FilePicker'
import { LICENSE_WORD } from '../components/Runtime'
import type { SavedHost } from '../hosts'
import { dropped } from '../roleDraft'
import type { HostStore } from '../store'
import type { Job, Runtime } from '../types'
import { videoKit } from '../videoDraft'
import { ServicePage } from './Service'
import { type Member, useConsolidated } from './useConsolidated'

/** A video model's clip tabs on this page (a model that also makes pictures keeps its picture tabs on the Images page). */
const memberOf = (runtime: Runtime): Member | undefined => {
  const video = runtime.generation?.video
  if (!video) return undefined
  const tabs = Object.keys(video.roles)
  return { kit: videoKit(runtime, video), modes: (runtime.generation?.modes ?? []).map((item) => item.key).filter((key) => tabs.includes(key)).concat(runtime.generation?.modes?.length ? [] : tabs) }
}

const SOUND = {
  none: 'This model makes silent clips.',
  automatic: 'The clip comes with sound the model makes itself: say what it sounds like in the description.',
  prompted: 'The sound comes from the sounds and music fields.',
}

/** One page for every video model, like Music for song models: what is typed (description, shape, length, pictures to start from) is kept
 * by role, so changing the model carries it over; only what the new model has no place for is left out. */
export function VideoPage({ store, host, modelId }: { store: HostStore; host?: SavedHost; modelId?: string }) {
  const { start, runtimes, running, chosen, chosenId, member, draft, draftRef, update, form, hooks, setPickedId, rebuild, reuseElsewhere } = useConsolidated(store, host, modelId, memberOf)
  const video = chosen?.generation?.video ?? undefined
  const mode = member?.modes.includes(form.mode ?? '') ? form.mode ?? '' : member?.modes[0] ?? ''
  const left = member ? dropped(draft, member.kit, mode) : ''
  const picker = <div className="decide-picker-row">
    {running.length > 1 && <label className="decide-picker"><span>Model filming</span>
      <select aria-label="Model filming" value={chosenId} onChange={(event) => setPickedId(event.target.value)}>
        {running.map((runtime) => <option key={runtime.id} value={runtime.id}>{runtime.name} ({runtime.license ? LICENSE_WORD[runtime.license.use] : 'Licence not reviewed'})</option>)}</select></label>}
  </div>
  const above = video && chosen ? <div className="speech-guidance" aria-label="Describing a clip">
    <p>{video.guidance}</p>
    <p>{SOUND[video.sound]}</p>
    {left && <p className="speech-notice" role="status">{chosen.name} has no place for {left}, so {left.includes(' and ') || left.includes(',') ? 'they are' : 'it is'} left out here and kept for when you switch back.</p>}
  </div> : null
  /** A result belongs here when it made a clip: any result of a clip-only model, and the clip tabs of one that also makes pictures. */
  const keepJob = (job: Job) => {
    const info = runtimes.find((runtime) => runtime.id === job.model_id)?.generation?.video
    if (!info) return false
    const tab = typeof job.inputs.mode === 'string' ? job.inputs.mode : info.create
    return Object.keys(info.roles).includes(tab)
  }
  // A finished clip can become the next one's first picture (its last frame) or the clip to continue, on the models that take them.
  const useFrame = video?.picture != null ? (file: FileItem) => { update({ values: draftRef.current.values, files: { ...draftRef.current.files, first: [file] } }); rebuild(chosen, 'picture') } : undefined
  const useClip = video?.extend != null ? (file: FileItem) => { update({ values: draftRef.current.values, files: { ...draftRef.current.files, source: [file] } }); rebuild(chosen, 'extend') } : undefined
  return <ServicePage store={store} host={host} modelId={chosen?.id ?? ''}
    group={{
      title: 'Video', noun: 'clip', description: 'Make clips with whichever video model is running. What you type carries over when you change the model.',
      ids: runtimes.map((runtime) => runtime.id), picker, above, keepJob, reuseElsewhere, useFrame, useClip, none: runtimes.length > 0 && running.length === 0,
      form: { key: `${chosenId}:${form.n}`, start, hooks },
    }} />
}
