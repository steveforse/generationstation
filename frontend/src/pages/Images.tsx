import type { SavedHost } from '../hosts'
import { LICENSE_WORD } from '../components/Runtime'
import { imageKit } from '../imageDraft'
import { dropped } from '../roleDraft'
import type { HostStore } from '../store'
import type { Job, Runtime } from '../types'
import { ServicePage } from './Service'
import { type Member, useConsolidated } from './useConsolidated'

/** A picture model's tabs on this page: the ones that make a picture (a model that is also a video model keeps its clip tabs on its own page). */
const memberOf = (runtime: Runtime): Member | undefined => {
  const image = runtime.generation?.image
  if (!image) return undefined
  const tabs = Object.keys(image.roles)
  return { kit: imageKit(image), modes: (runtime.generation?.modes ?? []).map((item) => item.key).filter((key) => tabs.includes(key)).concat(runtime.generation?.modes?.length ? [] : tabs) }
}

/** One page for every picture model, like Speech for speech models: what is typed (description, shape, things to avoid, pictures to start from)
 * is kept by role, so changing the model carries it over; only what the new model has no place for is left out. */
export function ImagesPage({ store, host, modelId }: { store: HostStore; host?: SavedHost; modelId?: string }) {
  const { start, runtimes, running, chosen, chosenId, member, mode, draft, form, hooks, setPickedId, reuseElsewhere } = useConsolidated(store, host, modelId, memberOf)
  const image = chosen?.generation?.image ?? undefined
  const left = member ? dropped(draft, member.kit, mode) : ''
  const picker = <div className="decide-picker-row">
    {running.length > 1 && <label className="decide-picker"><span>Model drawing</span>
      <select aria-label="Model drawing" value={chosenId} onChange={(event) => setPickedId(event.target.value)}>
        {running.map((runtime) => <option key={runtime.id} value={runtime.id}>{runtime.name} ({runtime.license ? LICENSE_WORD[runtime.license.use] : 'Licence not reviewed'})</option>)}</select></label>}
  </div>
  const above = image && chosen ? <div className="speech-guidance" aria-label="Describing a picture">
    <p>{image.guidance}</p>
    {left && <p className="speech-notice" role="status">{chosen.name} has no place for {left}, so {left.includes(' and ') || left.startsWith('the things') ? 'they are' : 'it is'} left out here and kept for when you switch back.</p>}
  </div> : null
  /** A result belongs here when it made a picture: any result of a picture-only model, and the picture tabs of one that also makes clips. */
  const keepJob = (job: Job) => {
    const info = runtimes.find((runtime) => runtime.id === job.model_id)?.generation?.image
    return !!info && (info.create === '' || Object.keys(info.roles).includes(String(job.inputs.mode)))
  }
  return <ServicePage store={store} host={host} modelId={chosen?.id ?? ''}
    group={{
      title: 'Images', noun: 'image', description: 'Make pictures with whichever picture model is running. What you type carries over when you change the model.',
      ids: runtimes.map((runtime) => runtime.id), picker, above, keepJob, reuseElsewhere, none: runtimes.length > 0 && running.length === 0,
      form: { key: `${chosenId}:${form.n}`, start, hooks },
    }} />
}
