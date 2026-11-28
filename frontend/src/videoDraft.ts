import type { Runtime, VideoInfo } from './types'
import type { Kit } from './roleDraft'

const firstWord = (text: string) => text.toLowerCase().split(/[\s:]/)[0]

/** The video model's capabilities as the page's role kit: its tabs are the ways of starting (a description, a first picture,
 * references, a clip to continue), the pictures and clips given are its files, a length is kept in seconds and a shape by its
 * first word ("landscape"), so both carry from one model to another whatever each calls its choices. */
export function videoKit(runtime: Runtime, video: VideoInfo): Kit {
  const options = (mode: string, role: string): string[] => {
    const key = video.roles[mode]?.[role]
    const fields = mode ? runtime.generation?.modes?.find((item) => item.key === mode)?.inputs : runtime.generation?.inputs
    return fields?.find((field) => field.key === key)?.options ?? []
  }
  return {
    roles: video.roles, fileRoles: ['first', 'last', 'source', 'references', 'videos', 'audio'],
    sources: { create: video.create, ...(video.picture !== null ? { picture: video.picture } : {}), ...(video.references !== null ? { references: video.references } : {}), ...(video.extend !== null ? { extend: video.extend } : {}) },
    droppable: { negative: 'the things to avoid', sounds: 'the sounds', music: 'the music', resolution: 'the resolution', quality: 'the quality', speed: 'the speed',
      first: 'the first picture', last: 'the last picture', source: 'the clip to continue', references: 'the reference pictures', videos: 'the reference clips',
      audio: 'the reference audio', notes: 'the notes on the references' },
    encode: (role, value) => role === 'length' && value in video.seconds ? String(video.seconds[value]) : role === 'shape' ? firstWord(value) : value,
    decode: (role, value, mode) => {
      const choices = options(mode, role)
      if (!choices.length || choices.includes(value)) return value
      if (role === 'length') {
        const wanted = Number(value)
        if (!Number.isFinite(wanted)) return value
        const known = choices.filter((choice) => choice in video.seconds)
        return known.length ? known.reduce((best, choice) => Math.abs(video.seconds[choice] - wanted) < Math.abs(video.seconds[best] - wanted) ? choice : best) : value
      }
      if (role === 'shape') return choices.find((choice) => firstWord(choice) === value) ?? value
      return value
    },
  }
}
