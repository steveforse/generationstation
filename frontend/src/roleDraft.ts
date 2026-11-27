import type { FormStart } from './components/Runtime'
import type { FileItem } from './components/FilePicker'
import type { Job } from './types'

/** What the person has typed on a page that serves several models (Speech, Images), by role instead of by each model's field names,
 * so it moves between models and between a model's tabs. */
export type Draft = { values: Record<string, string>; files: Record<string, FileItem[]> }
export const emptyDraft: Draft = { values: {}, files: {} }

/** How one model maps the roles: tab -> role -> its own field, the roles that are files, and what to call what it may have to leave out. */
export type Kit = {
  roles: Record<string, Record<string, string>>
  fileRoles: string[]
  /** The model's ways of starting (a voice source, create or edit) -> the tab that serves each. */
  sources: Record<string, string>
  /** A role the model may lack -> the words used when telling the person it was left out. */
  droppable: Record<string, string>
  /** A tab that takes no carried files (speech scenes have several voices of their own). */
  withoutFiles?: string | null
}

/** The draft after this tab's values: the roles the tab has take its values, the others keep what they were. */
export function absorb(draft: Draft, kit: Kit, mode: string, values: Record<string, string>, files: Record<string, FileItem[]>): Draft {
  const next = { ...draft.values }
  const kept = { ...draft.files }
  for (const [role, field] of Object.entries(kit.roles[mode] ?? {})) {
    if (kit.fileRoles.includes(role)) kept[role] = (files[field] ?? []).filter((item) => item.status === 'ready')
    else if (field in values) next[role] = values[field]
  }
  return { values: next, files: kept }
}

/** The form start for a tab: the draft's values and files under that tab's own field names. */
export function startFor(draft: Draft, kit: Kit, mode: string): FormStart {
  const inputs: Job['inputs'] = mode ? { mode } : {}
  const files: Record<string, FileItem[]> = {}
  for (const [role, field] of Object.entries(kit.roles[mode] ?? {})) {
    if (kit.fileRoles.includes(role)) { if (mode !== kit.withoutFiles && draft.files[role]?.length) files[field] = draft.files[role] }
    else if (role === 'sample_text' && mode === kit.withoutFiles) continue
    else if (draft.values[role]) inputs[field] = draft.values[role]
  }
  return { mode: mode || undefined, inputs, files }
}

/** The tab that serves a way of starting on this model, else the fallback. */
export function modeFor(kit: Kit, source: string | undefined, fallback: string): string {
  const found = source ? kit.sources[source] : undefined
  return found !== undefined ? found : fallback
}

/** The way of starting a tab serves ("builtin", "clone", "create", "edit"...), if it is one. */
export function sourceOf(kit: Kit, mode: string): string | undefined {
  return Object.entries(kit.sources).find(([, served]) => served === mode)?.[0]
}

/** What the draft holds that this tab has no place for, in words ("the avoid list and the pictures"), or ''. */
export function dropped(draft: Draft, kit: Kit, mode: string): string {
  const has = Object.keys(kit.roles[mode] ?? {})
  const lost = Object.entries(kit.droppable).filter(([role]) => (draft.values[role] || draft.files[role]?.length) && !has.includes(role)).map(([, words]) => words)
  return lost.length < 2 ? lost.join('') : `${lost.slice(0, -1).join(', ')} and ${lost[lost.length - 1]}`
}
