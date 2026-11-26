import { useRef, useState } from 'react'
import { AlertCircle, Film, FileText, Loader2, Music, Plus, X } from 'lucide-react'
import type { InputField, UploadRecord } from '../types'

/** A file chosen for a request: uploading, ready (with the host's upload ID), or refused. */
export type FileItem = { key: string; name: string; kind: string; url: string; status: 'uploading' | 'ready' | 'error'; id?: string; error?: string }

const ACCEPT: Record<string, string> = {
  image: '.png,.jpg,.jpeg,.webp,image/png,image/jpeg,image/webp',
  video: '.mp4,.mov,.webm,.m4v,video/mp4,video/quicktime,video/webm',
  audio: '.wav,.mp3,.flac,.m4a,.ogg,audio/wav,audio/mpeg,audio/flac,audio/mp4,audio/ogg',
  transcript: '.txt,.md,.vtt,.srt,text/plain,text/markdown,text/vtt,application/x-subrip',
}
const NOUN: Record<string, string> = { image: 'picture', video: 'video', audio: 'audio clip', transcript: 'transcript' }

/** The kind of an accepted file, by its name's ending (the host accepts the same types and checks the contents). */
export function kindOfFile(file: File) {
  const suffix = file.name.toLowerCase().split('.').pop() ?? ''
  return ['png', 'jpg', 'jpeg', 'webp'].includes(suffix) ? 'image' : ['mp4', 'mov', 'webm', 'm4v'].includes(suffix) ? 'video'
    : ['wav', 'mp3', 'flac', 'm4a', 'ogg'].includes(suffix) ? 'audio' : ['txt', 'md', 'vtt', 'srt'].includes(suffix) ? 'transcript' : ''
}

/**
 * Pick files for a "files" field: one tile per file, with a preview, and an "Add" tile while there is room
 * (up to the field's maximum). Files upload as soon as they are chosen; drop files on it too.
 */
export function FilePicker({ id, field, items, onChange, upload }: {
  id: string; field: InputField; items: FileItem[]; onChange: (update: (items: FileItem[]) => FileItem[]) => void
  upload: (file: File) => Promise<UploadRecord>
}) {
  const input = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const max = field.max_count ?? 1
  const room = max - items.length
  const kinds = field.accept ?? []
  const noun = kinds.length === 1 ? NOUN[kinds[0]] : 'file'
  const add = (files: File[]) => {
    for (const file of files.slice(0, Math.max(room, 0))) {
      const key = `${Date.now()}-${Math.random().toString(36).slice(2)}`
      const kind = kindOfFile(file)
      const item: FileItem = { key, name: file.name, kind, url: URL.createObjectURL(file), status: 'uploading' }
      if (!kinds.includes(kind as never)) {
        onChange((current) => [...current, { ...item, status: 'error', error: `Not a ${kinds.map((k) => NOUN[k]).join(' or ')} this accepts.` }])
        continue
      }
      onChange((current) => [...current, item])
      upload(file)
        .then((record) => onChange((current) => current.map((other) => other.key === key ? { ...other, status: 'ready', id: record.id } : other)))
        .catch((reason) => onChange((current) => current.map((other) => other.key === key ? { ...other, status: 'error', error: reason instanceof Error ? reason.message : 'Upload failed.' } : other)))
    }
  }
  const remove = (key: string) => onChange((current) => {
    const gone = current.find((item) => item.key === key)
    if (gone) URL.revokeObjectURL(gone.url)
    return current.filter((item) => item.key !== key)
  })
  return <div className={`file-picker ${dragging ? 'file-picker-drag' : ''}`}
    onDragOver={(event) => { if (room > 0) { event.preventDefault(); setDragging(true) } }} onDragLeave={() => setDragging(false)}
    onDrop={(event) => { event.preventDefault(); setDragging(false); add([...event.dataTransfer.files]) }}>
    {items.map((item, index) => <figure key={item.key} className={`file-tile file-${item.status}`}>
      {item.kind === 'image' ? <img src={item.url} alt={item.name} /> : item.kind === 'video' ? <video src={item.url} muted preload="metadata" aria-label={item.name} />
        : <span className="file-icon">{item.kind === 'audio' ? <Music size={28} /> : item.kind === 'transcript' ? <FileText size={28} /> : <Film size={28} />}</span>}
      {max > 1 && <span className="file-index" aria-hidden="true">{index + 1}</span>}
      {item.status === 'uploading' && <span className="file-state"><Loader2 size={20} className="spin" /></span>}
      {item.status === 'error' && <span className="file-state file-state-error" title={item.error}><AlertCircle size={20} /></span>}
      <figcaption title={item.name}>{item.status === 'error' ? item.error : item.name}</figcaption>
      <button type="button" className="file-remove" aria-label={`Remove ${item.name}`} onClick={() => remove(item.key)}><X size={16} /></button>
    </figure>)}
    {room > 0 && <button type="button" id={id} className="file-add" aria-label={`Add ${noun}: ${field.label}`} onClick={() => input.current?.click()}>
      <Plus size={22} /><span>Add {noun}</span><small>{max > 1 ? `${items.length} of ${max}` : 'or drop it here'}</small>
    </button>}
    <input ref={input} type="file" hidden accept={kinds.map((kind) => ACCEPT[kind]).join(',')} multiple={room > 1}
      onChange={(event) => { add([...(event.target.files ?? [])]); event.target.value = '' }} />
  </div>
}
