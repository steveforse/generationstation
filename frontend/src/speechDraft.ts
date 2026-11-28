import type { SpeechInfo } from './types'
import type { Kit } from './roleDraft'

/** The speech model's capabilities as the page's role kit: the voice samples are its files, and a scene takes none carried over. */
export const speechKit = (speech: SpeechInfo): Kit => ({
  roles: speech.roles, fileRoles: ['sample'], sources: speech.voices, withoutFiles: speech.scene,
  droppable: { direction: 'the direction', voice_description: 'the voice description', speed: 'the speed' },
})


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
