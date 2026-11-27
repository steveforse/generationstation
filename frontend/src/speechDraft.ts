import type { FormStart } from './components/Runtime'
import type { FileItem } from './components/FilePicker'
import type { Job, SpeechInfo } from './types'

/** What the person has typed, by role instead of by each model's field names, so it moves between speech models. */
export type Draft = { values: Record<string, string>; sample: FileItem[] }
export const emptyDraft: Draft = { values: {}, sample: [] }

/** Roles a model may lack, and the words used when telling the person they were left out. */
const DROPPABLE: Record<string, string> = { direction: 'the direction', voice_description: 'the voice description', speed: 'the speed' }

/** The draft after this tab's values: the roles the tab has take its values, the others keep what they were. */
export function absorb(draft: Draft, speech: SpeechInfo, mode: string, values: Record<string, string>, files: Record<string, FileItem[]>): Draft {
  const next = { ...draft.values }
  let sample = draft.sample
  for (const [role, field] of Object.entries(speech.roles[mode] ?? {})) {
    if (role === 'sample') sample = (files[field] ?? []).filter((item) => item.status === 'ready')
    else if (field in values) next[role] = values[field]
  }
  return { values: next, sample }
}

/** The form start for a tab: the draft's values under that tab's own field names. A scene tab takes the text only,
 * because its samples are several voices, not the one the draft holds. */
export function startFor(draft: Draft, speech: SpeechInfo, mode: string): FormStart {
  const inputs: Job['inputs'] = { mode }
  const files: Record<string, FileItem[]> = {}
  for (const [role, field] of Object.entries(speech.roles[mode] ?? {})) {
    if (role === 'sample') { if (mode !== speech.scene && draft.sample.length) files[field] = draft.sample }
    else if (role === 'sample_text' && mode === speech.scene) continue
    else if (draft.values[role]) inputs[field] = draft.values[role]
  }
  return { mode, inputs, files }
}

/** The tab that serves a voice source on this model, else the fallback. */
export function modeFor(speech: SpeechInfo, source: string | undefined, fallback: string): string {
  return (source && speech.voices[source]) || fallback
}

/** The voice source ("builtin", "design", "clone", "own") a tab serves, if it is a voice tab. */
export function sourceOf(speech: SpeechInfo, mode: string): string | undefined {
  return Object.entries(speech.voices).find(([, served]) => served === mode)?.[0]
}

/** What the draft holds that this tab has no place for, in words ("the direction and the speed"), or ''. */
export function dropped(draft: Draft, speech: SpeechInfo, mode: string): string {
  const has = Object.keys(speech.roles[mode] ?? {})
  const lost = Object.entries(DROPPABLE).filter(([role]) => draft.values[role] && !has.includes(role)).map(([, words]) => words)
  return lost.length < 2 ? lost.join('') : `${lost.slice(0, -1).join(', ')} and ${lost[lost.length - 1]}`
}

function span(open: string, close: string) {
  const escape = (text: string) => text.replace(/[\\^$.*+?()[\]{}|-]/g, '\\$&')
  return new RegExp(`${escape(open)}[^${escape(open)}${escape(close)}]*${escape(close)}`, 'g')
}

/** Cues this model's text takes that it does not know (only for a closed vocabulary, where an unknown one is refused). */
export function unknownCues(text: string, speech: SpeechInfo): string[] {
  const cues = speech.direction.cues
  if (!cues || cues.open_vocabulary) return []
  const known = new Set(cues.examples.map((example) => example.toLowerCase()))
  return (text.match(span(cues.open, cues.close)) ?? []).filter((found) => !known.has(found.toLowerCase()))
}

/** Square-bracket cues in text going to a model that has none: it would read them aloud. */
export function strayCues(text: string, speech: SpeechInfo): string[] {
  return speech.direction.cues?.open === '[' ? [] : text.match(span('[', ']')) ?? []
}

/** The text without the given cues and the extra spaces they leave. */
export function removeCues(text: string, found: string[]): string {
  return found.reduce((rest, cue) => rest.split(cue).join(''), text).replace(/[ \t]{2,}/g, ' ').replace(/ +([,.!?])/g, '$1').trim()
}
