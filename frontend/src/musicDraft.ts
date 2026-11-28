import type { MusicInfo } from './types'
import type { Kit } from './roleDraft'

/** The song model's capabilities as the page's role kit: the song to start from is its file, and its tabs are the ways of
 * starting (a new song, a new version of a song, a redone section). */
export const musicKit = (music: MusicInfo): Kit => ({
  roles: music.roles, fileRoles: ['source'],
  sources: { create: music.create, ...(music.cover !== null ? { cover: music.cover } : {}), ...(music.repaint !== null ? { repaint: music.repaint } : {}) },
  droppable: { length: 'the length', language: 'the language', tempo: 'the tempo', key: 'the key', time_signature: 'the time signature', steps: 'the steps',
    source: 'the song to start from', strength: 'how closely it follows the song', start: 'the start of the section', end: 'the end of the section' },
})

/** The tags a lyric is divided by, which every song model reads. */
export const LYRIC_TAGS = ['[Intro]', '[Verse]', '[Pre-Chorus]', '[Chorus]', '[Bridge]', '[Instrumental Break]', '[Outro]']
