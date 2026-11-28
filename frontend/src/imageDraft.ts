import type { ImageInfo } from './types'
import type { Kit } from './roleDraft'

/** The picture model's capabilities as the page's role kit: the pictures given to edit are its files, and its tabs are
 * the ways of starting (from a description, or from pictures). */
export const imageKit = (image: ImageInfo): Kit => ({
  roles: image.roles, fileRoles: ['pictures', 'start'],
  sources: { ...(image.create !== null ? { create: image.create } : {}), ...(image.edit !== null ? { edit: image.edit } : {}) },
  droppable: { negative: 'the things to avoid', quality: 'the quality', size: 'the size', pictures: 'the pictures', notes: 'the notes on the pictures',
    start: 'the starting picture', strength: 'how closely it follows the picture', steps: 'the steps' },
})
