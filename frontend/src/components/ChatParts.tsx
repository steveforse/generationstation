import { useCallback, useEffect, useRef, useState } from 'react'
import { Bot, ChevronDown, Loader2 } from 'lucide-react'
import { Markdown } from './Markdown'
import { jobTitle, ResultThumb } from './Runtime'
import { StatePill } from './StatePill'
import type { HostSession } from '../session'
import type { ChatAttachment, ChatMessage, Job, JobOutput, Runtime } from '../types'

/** What the model is writing right now, before it is saved. */
export type Draft = { content: string; reasoning: string; tool: string }
/** thinking: a level the model takes, "off", or true for the model's default. */
export type MessageBody = { text: string; attachments: ChatAttachment[]; thinking: boolean | string; where?: string }

const THUMBNAIL = 'thumbnail.jpg'
export const mainOutput = (job: Job): JobOutput | undefined => job.outputs.find((output) => output.name !== THUMBNAIL && output.name !== job.details?.thumbnail)
export const kindOf = (mime?: string | null) => mime?.split('/')[0] ?? ''
export const KIND_WORD: Record<string, string> = { image: 'Picture', video: 'Video', audio: 'Sound' }

/**
 * Sending a message and following the answer as it is written: the draft, what a tool is doing, and the
 * sending and stopping states. Used by the Chat page and the assistant bubble. `onSaved` gets each saved
 * message; the result is '' when the answer finished, else the problem (also shown as `error`).
 */
export function useChatTurn(session?: HostSession) {
  const [draft, setDraft] = useState<Draft | null>(null)
  // What a tool is doing between answers ("Starting Qwen Image on the RTX 4080…").
  const [activity, setActivity] = useState('')
  const [sending, setSending] = useState(false)
  const [stopping, setStopping] = useState(false)
  const [error, setError] = useState('')
  const abort = useRef<AbortController | null>(null)
  // Leaving drops the stream; the host still finishes and saves the answer.
  useEffect(() => () => abort.current?.abort(), [])

  const send = useCallback(async (id: string, body: MessageBody, onSaved: (message: ChatMessage) => void) => {
    if (!session) return 'Not connected to the host.'
    setError(''); setSending(true)
    abort.current = new AbortController()
    let problem = ''
    try {
      await session.sendMessage(id, body, (event, data) => {
        if (event === 'message') {
          const saved = data as ChatMessage & { job?: Job }
          if (saved.job) session.trackJob(saved.job)
          onSaved(saved)
          if (saved.role === 'assistant') setDraft(null)
          if (saved.role === 'tool') setActivity('')
        } else if (event === 'status') setActivity((data as { text?: string }).text ?? '')
        else if (event === 'start') { setActivity(''); setDraft({ content: '', reasoning: '', tool: '' }) }
        else if (event === 'delta') {
          const piece = data as Partial<Draft>
          setDraft((current) => {
            const base = current ?? { content: '', reasoning: '', tool: '' }
            return { content: base.content + (piece.content ?? ''), reasoning: base.reasoning + (piece.reasoning ?? ''), tool: piece.tool ?? base.tool }
          })
        } else if (event === 'error') { problem = (data as { message?: string }).message ?? 'The answer stopped unexpectedly.'; setError(problem) }
      }, abort.current.signal)
    } catch (reason) {
      if (!(reason instanceof DOMException && reason.name === 'AbortError')) {
        problem = reason instanceof Error ? reason.message : 'The message could not be sent.'
        setError(problem)
      }
    } finally {
      abort.current = null
      setSending(false); setStopping(false); setDraft(null); setActivity('')
    }
    return problem
  }, [session])

  const stop = useCallback(async (id: string) => {
    if (!session) return
    setStopping(true)
    try { await session.stopConversation(id) } catch (reason) { setError(reason instanceof Error ? reason.message : 'It could not be stopped.'); setStopping(false) }
  }, [session])

  return { draft, activity, sending, stopping, error, setError, send, stop }
}

/** Keeps the newest message in view as it is written and as pictures load, unless the reader scrolled up. */
export function usePinnedScroll(reset: unknown) {
  const thread = useRef<HTMLDivElement>(null)
  const body = useRef<HTMLDivElement>(null)
  const pinned = useRef(true)
  useEffect(() => {
    const element = thread.current
    const inner = body.current
    if (!element || !inner) return
    const onScroll = () => { pinned.current = element.scrollHeight - element.scrollTop - element.clientHeight < 80 }
    const observer = new ResizeObserver(() => { if (pinned.current) element.scrollTop = element.scrollHeight })
    element.addEventListener('scroll', onScroll, { passive: true })
    observer.observe(inner)
    return () => { element.removeEventListener('scroll', onScroll); observer.disconnect() }
  })
  useEffect(() => { pinned.current = true }, [reset])
  return { thread, body }
}

export function MessageView({ message, session, jobs, runtimes, onOpenJob }: { message: ChatMessage; session: HostSession; jobs: Job[]; runtimes: Runtime[]; onOpenJob: (id: string) => void }) {
  if (message.role === 'user') return <div className="chat-msg from-user">
    <div className="chat-bubble">
      {message.attachments.length > 0 && <div className="chat-attachments">{message.attachments.map((item) => <AttachmentChip key={`${item.job_id}/${item.name}`} item={item} jobs={jobs} session={session} onOpen={onOpenJob} />)}</div>}
      {message.content && <p className="chat-user-text">{message.content}</p>}
    </div>
  </div>
  if (message.role === 'tool' && message.attachments.length > 0) return <div className="chat-shown" aria-label={message.note ?? 'Results'}>
    {message.attachments.map((item) => <JobCard key={item.job_id} jobId={item.job_id} jobs={jobs} runtimes={runtimes} session={session} onOpen={onOpenJob} />)}
  </div>
  if (message.role === 'tool') return message.job_id
    ? <JobCard jobId={message.job_id} jobs={jobs} runtimes={runtimes} session={session} onOpen={onOpenJob} />
    : <p className={`chat-tool-note ${message.status === 'error' ? 'chat-tool-note-problem' : ''}`}>{message.note || message.content}</p>
  if (!message.content && !message.reasoning && message.tool_calls.length && message.status === 'done') return null
  return <div className="chat-msg from-model">
    <span className="chat-avatar" aria-hidden="true"><Bot size={18} /></span>
    <div className="chat-answer">
      {message.reasoning && <Thinking text={message.reasoning} />}
      {message.content && <Markdown text={message.content} />}
      {message.status === 'stopped' && <small className="chat-stopped">Stopped</small>}
      {message.status === 'error' && message.error_message && <p className="chat-error">{message.error_message}</p>}
    </div>
  </div>
}

export function DraftView({ draft }: { draft: Draft }) {
  return <div className="chat-msg from-model">
    <span className="chat-avatar" aria-hidden="true"><Bot size={18} /></span>
    <div className="chat-answer">
      {draft.reasoning && <Thinking text={draft.reasoning} live={!draft.content} />}
      {draft.content ? <Markdown text={draft.content} /> : !draft.reasoning && !draft.tool && <span className="chat-typing"><Loader2 size={16} className="spin" aria-hidden="true" /> Writing…</span>}
      {draft.tool && <span className="chat-typing"><Loader2 size={16} className="spin" aria-hidden="true" /> Working…</span>}
    </div>
  </div>
}

function Thinking({ text, live = false }: { text: string; live?: boolean }) {
  return <details className="chat-thinking disclosure" open={live || undefined}>
    <summary><ChevronDown size={16} aria-hidden="true" className="disclosure-chevron" />{live ? <><Loader2 size={14} className="spin" aria-hidden="true" /> Thinking…</> : 'Thinking'}</summary>
    <p>{text}</p>
  </details>
}

/** A job started from the chat: its state while it runs, and the result itself when it is done. */
export function JobCard({ jobId, jobs, runtimes, session, onOpen }: { jobId: string; jobs: Job[]; runtimes: Runtime[]; session: HostSession; onOpen: (id: string) => void }) {
  const known = jobs.find((job) => job.id === jobId)
  const [fetched, setFetched] = useState<Job | null | undefined>(undefined)
  useEffect(() => {
    if (known || fetched !== undefined) return
    session.call(`/api/jobs/${encodeURIComponent(jobId)}`).then((job) => { setFetched(job as Job); session.trackJob(job as Job) }).catch(() => setFetched(null))
  }, [known, fetched, jobId, session])
  const job = known ?? fetched
  if (job === null) return <p className="chat-tool-note">This result has been deleted.</p>
  if (!job) return <p className="chat-tool-note"><Loader2 size={14} className="spin" aria-hidden="true" /> Loading a result…</p>
  const runtime = runtimes.find((item) => item.id === job.model_id)
  const output = mainOutput(job)
  return <div className="chat-job">
    <div className="chat-job-head">
      <StatePill state={job.status}>{job.status === 'running' ? job.progress ?? 'Working' : job.status === 'queued' ? 'Queued' : job.status === 'done' ? 'Done' : job.status === 'failed' ? 'Did not work' : 'Cancelled'}</StatePill>
      <span>{runtime?.name ?? job.model_id}</span>
      <button type="button" className="text-button" onClick={() => onOpen(job.id)}>Details</button>
    </div>
    <p className="chat-job-prompt">{jobTitle(job)}</p>
    {job.status === 'done' && output && <InlineMedia job={job} output={output} session={session} />}
    {job.status === 'failed' && job.error_message && <small className="operation-error">{job.error_message}</small>}
    {(job.status === 'queued' || job.status === 'running') && <button type="button" className="button button-secondary button-small" onClick={() => void session.cancelJob(job)}>Cancel</button>}
  </div>
}

function InlineMedia({ job, output, session }: { job: Job; output: JobOutput; session: HostSession }) {
  const [url, setUrl] = useState('')
  useEffect(() => {
    let made = ''
    let cancelled = false
    session.fileUrl(job, output).then((next) => { made = next; if (!cancelled) setUrl(next) }).catch(() => undefined)
    return () => { cancelled = true; if (made) URL.revokeObjectURL(made) }
  }, [job, output, session])
  if (!url) return <div className="chat-media chat-media-loading"><Loader2 size={18} className="spin" aria-hidden="true" /></div>
  const kind = kindOf(output.mime)
  const label = jobTitle(job)
  return <div className="chat-media">
    {kind === 'image' ? <img src={url} alt={label} /> : kind === 'video' ? <video controls src={url} aria-label={`Play ${label}`} /> : <audio controls src={url} aria-label={`Play ${label}`} />}
  </div>
}

function AttachmentChip({ item, jobs, session, onOpen }: { item: ChatAttachment; jobs: Job[]; session: HostSession; onOpen: (id: string) => void }) {
  const job = jobs.find((other) => other.id === item.job_id)
  const kind = kindOf(item.mime)
  return <button type="button" className="chat-chip" onClick={() => job && onOpen(job.id)} disabled={!job} title={job ? jobTitle(job) : 'An earlier result'}>
    {job ? <ResultThumb job={job} kind={kind} fileUrl={(j, o) => session.fileUrl(j, o)} /> : <span className="result-thumb result-thumb-empty" />}
    <span>{KIND_WORD[kind] ?? 'Result'} · {item.job_id.slice(0, 8)}</span>
  </button>
}

