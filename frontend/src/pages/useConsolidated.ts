import { useEffect, useRef, useState } from 'react'
import type { FormHooks, FormStart } from '../components/Runtime'
import type { SavedHost } from '../hosts'
import { absorb, emptyDraft, modeFor, sourceOf, startFor, type Draft, type Kit } from '../roleDraft'
import type { HostStore } from '../store'
import { useSession } from '../store'
import type { Job, Runtime } from '../types'
import { takeHandOff } from '../voiceSample'

/** What a page that serves several models as one needs from each: its role kit, and the tabs the page offers. */
export type Member = { kit: Kit; modes: string[] }

/**
 * The state behind a page that serves several models of one kind (Speech, Images) as one: which models are running and which is chosen,
 * what has been typed (kept by role, so it moves with the person from model to model and tab to tab), the form's start for each tab,
 * and what to do when a result from another model of the page is reused. The page adds its own guidance and tools around the form.
 */
export function useConsolidated(store: HostStore, host: SavedHost | undefined, modelId: string | undefined, memberOf: (runtime: Runtime) => Member | undefined) {
  const state = useSession(host ? store.session(host.id) : undefined)
  const [pickedId, setPickedId] = useState<string | null>(modelId ?? null)
  const [draft, setDraft] = useState<Draft>(emptyDraft)
  const draftRef = useRef(draft)
  const [form, setForm] = useState<{ n: number; mode?: string }>({ n: 0 })
  const modeRef = useRef('')
  const [pickedMode, setMode] = useState('')
  const lastMode = useRef('')  // the tab open at the last render, which is the old model's when the model changes
  const previous = useRef<string | undefined>(undefined)

  const runtimes = (state.runtimes ?? []).filter((runtime) => memberOf(runtime))
  const running = runtimes.filter((runtime) => state.models?.find((model) => model.id === runtime.id)?.state === 'ready')
  const chosen = running.find((runtime) => runtime.id === pickedId) ?? running[0] ?? runtimes.find((runtime) => runtime.id === pickedId) ?? runtimes[0]
  const member = chosen ? memberOf(chosen) : undefined
  const chosenId = chosen?.id
  const mode = member?.modes.includes(pickedMode) ? pickedMode : member?.modes[0] ?? ''
  modeRef.current = mode

  const update = (next: Draft) => { draftRef.current = next; setDraft(next) }
  const open = (next: string) => { modeRef.current = next; setMode(next); setForm((current) => ({ n: current.n + 1, mode: next })) }
  /** Rebuild the form from the draft, on the tab for the way of starting the person was using (or the fallback). */
  const rebuild = (runtime: Runtime | undefined, fromSource: string | undefined, fallbackMode?: string) => {
    const next = runtime ? memberOf(runtime) : undefined
    if (!runtime || !next) return
    open(modeFor(next.kit, fromSource, fallbackMode ?? next.modes[0] ?? ''))
  }

  // Choosing another model carries the draft over, on the tab for the same way of starting.
  useEffect(() => {
    if (!chosenId || previous.current === chosenId) { previous.current = chosenId; return }
    const had = previous.current
    previous.current = chosenId
    if (!had) return
    const before = runtimes.find((runtime) => runtime.id === had)
    const kit = before ? memberOf(before)?.kit : undefined
    rebuild(chosen, kit ? sourceOf(kit, lastMode.current) : undefined)
  }, [chosenId]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { lastMode.current = mode })

  // Something sent from another page ("use these settings" in Chat, a clip's soundtrack) arrives once the models are listed.
  const taken = useRef(false)
  useEffect(() => {
    if (!host || taken.current || !runtimes.length) return
    taken.current = true
    for (const runtime of runtimes) {
      const start = takeHandOff(host.id, runtime.id)
      const next = memberOf(runtime)
      if (!start || !next) continue
      const startMode = start.mode ?? next.modes[0] ?? ''
      const values = Object.fromEntries(Object.entries(start.inputs ?? {}).map(([key, value]) => [key, Array.isArray(value) || value == null ? '' : String(value)]))
      update(absorb(draftRef.current, next.kit, startMode, values, start.files ?? {}))
      setPickedId(runtime.id)
      open(startMode)
      break
    }
  }, [runtimes.length, host?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  const starts: Record<string, FormStart> = {}
  if (member) for (const key of member.modes) starts[key] = startFor(draft, member.kit, key)
  const hooks: FormHooks = {
    starts,
    showModes: (key) => !member || member.modes.includes(key),
    onValues: (formMode, values, files) => { if (member) update(absorb(draftRef.current, member.kit, formMode, values, files)) },
    // A tab was opened by hand: rebuild so it starts from what the other tab held.
    onMode: (next) => open(next),
  }

  /** "Use these settings" on a result from another model of the page: that model is chosen and the result's values carry over. */
  const reuseElsewhere = (job: Job) => {
    const target = runtimes.find((runtime) => runtime.id === job.model_id)
    const next = target ? memberOf(target) : undefined
    if (!target || !next) return
    const jobMode = typeof job.inputs.mode === 'string' ? job.inputs.mode : next.modes[0] ?? ''
    const values = Object.fromEntries(Object.entries(job.inputs).map(([key, value]) => [key, Array.isArray(value) || value == null || typeof value === 'object' ? '' : String(value)]))
    update(absorb(draftRef.current, next.kit, jobMode, values, {}))
    setPickedId(target.id)
    if (target.id === chosenId) rebuild(target, sourceOf(next.kit, jobMode), jobMode)
  }

  // Where the form opens: on the tab in use, with the draft's values (a model with no tabs gets its values here too).
  // (A tab the new model does not have is the old model's, left over until the rebuild: open on this model's own first tab, so the form
  // does not start blank and report its blank fields over the draft.)
  const openTab = form.mode !== undefined && member?.modes.includes(form.mode) ? form.mode : mode
  const start: FormStart = { ...(starts[openTab] ?? {}), mode: openTab || undefined }

  return { start, state, runtimes, running, chosen, chosenId, member, mode, draft, draftRef, update, form, hooks, setPickedId, rebuild, reuseElsewhere }
}
