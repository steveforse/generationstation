import type { Kit } from './roleDraft'
import type { TranscribeInfo } from './types'

/** The transcription model's capabilities as the page's role kit: the recording is its file, and there is one form. */
export const transcribeKit = (transcribe: TranscribeInfo): Kit => ({
  roles: transcribe.roles, fileRoles: ['recording'], sources: { create: '' },
  droppable: { language: 'the language', terms: 'the words to expect', speakers: 'who spoke' },
})
