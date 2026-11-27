import { useEffect, useRef, useState } from 'react'
import { AlertCircle, Film, FileText, Loader2, Mic, Music, Plus, Square, X } from 'lucide-react'
import type { InputField, UploadRecord } from '../types'
import { soundtrackToWav } from '../voiceSample'

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
export function FilePicker({ id, field, items, onChange, upload, record = false }: {
  id: string; field: InputField; /** Offer recording from the microphone (voice samples). */ record?: boolean; items: FileItem[]; onChange: (update: (items: FileItem[]) => FileItem[]) => void
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
    {room > 0 && record && <MicRecorder label={field.label} onRecorded={(file) => add([file])} />}
    <input ref={input} type="file" hidden accept={kinds.map((kind) => ACCEPT[kind]).join(',')} multiple={room > 1}
      onChange={(event) => { add([...(event.target.files ?? [])]); event.target.value = '' }} />
  </div>
}

const MAX_RECORDING = 30  // seconds: a voice sample of 5 to 20 seconds works best

/** Record a voice sample from the microphone. The browser's recording (WebM or MP4) is turned into a WAV, then added like any chosen file. */
function MicRecorder({ label, onRecorded }: { label: string; onRecorded: (file: File) => void }) {
  const [state, setState] = useState<'idle' | 'recording' | 'working'>('idle')
  const [seconds, setSeconds] = useState(0)
  const [problem, setProblem] = useState('')
  const recorder = useRef<MediaRecorder | null>(null)
  const tracks = useRef<MediaStreamTrack[]>([])
  const timer = useRef<number | undefined>(undefined)
  const stopTimer = () => { window.clearInterval(timer.current); timer.current = undefined }
  useEffect(() => () => { stopTimer(); tracks.current.forEach((track) => track.stop()) }, [])
  const stop = () => { if (recorder.current?.state === 'recording') recorder.current.stop() }
  const start = async () => {
    setProblem('')
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      setProblem('This page cannot use the microphone. Browsers allow it only on https pages or on this computer (localhost).')
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      tracks.current = stream.getTracks()
      const chunks: Blob[] = []
      const next = new MediaRecorder(stream)
      recorder.current = next
      next.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data) }
      next.onstop = async () => {
        stopTimer(); tracks.current.forEach((track) => track.stop()); tracks.current = []
        setState('working')
        try {
          const wav = await soundtrackToWav(new Blob(chunks, { type: next.mimeType || 'audio/webm' }))
          onRecorded(new File([wav], `recording-${new Date().toISOString().slice(11, 19).replace(/:/g, '')}.wav`, { type: 'audio/wav' }))
        } catch (reason) { setProblem(reason instanceof Error ? reason.message : 'The recording could not be read.') }
        setState('idle')
      }
      next.start()
      setSeconds(0); setState('recording')
      timer.current = window.setInterval(() => setSeconds((count) => { if (count + 1 >= MAX_RECORDING) stop(); return count + 1 }), 1000)
    } catch (reason) {
      const denied = reason instanceof DOMException && (reason.name === 'NotAllowedError' || reason.name === 'SecurityError')
      setProblem(denied ? 'The microphone is blocked. Allow it for this page in the browser, then try again.' : 'No microphone was found.')
    }
  }
  return <>
    {state === 'recording'
      ? <button type="button" className="file-add file-recording" aria-label={`Stop recording: ${label}`} onClick={stop}><Square size={22} /><span>Stop</span><small>{seconds} s of {MAX_RECORDING}</small></button>
      : <button type="button" className="file-add" aria-label={`Record from the microphone: ${label}`} disabled={state === 'working'} onClick={() => void start()}>
        {state === 'working' ? <Loader2 size={22} className="spin" /> : <Mic size={22} />}<span>Record</span><small>5 to 20 seconds</small></button>}
    {problem && <p className="field-help file-problem" role="alert">{problem}</p>}
  </>
}
