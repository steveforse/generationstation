import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ArrowLeft, ArrowUp, ArrowUpRight, Bot, Brain, Check, ChevronDown, Loader2, Paperclip, Pencil, Plus, Square, Trash2, X } from 'lucide-react'
import { ConnectionBanner, hostName, stateText } from '../components/HostBits'
import { Markdown } from '../components/Markdown'
import { JobDetail, JobModal, jobTitle, ResultThumb, when } from '../components/Runtime'
import { StatePill } from '../components/StatePill'
import { handOff } from '../voiceSample'
import type { SavedHost } from '../hosts'
import { href } from '../routes'
import type { HostSession } from '../session'
import { type HostStore, useSession } from '../store'
import type { ChatAttachment, ChatMessage, Conversation, Job, JobOutput, Runtime } from '../types'

type Loaded = { conversation: Conversation; messages: ChatMessage[] }
type Draft = { content: string; reasoning: string; tool: string }
type Pick = ChatAttachment & { job: Job }

const MAX_ATTACHMENTS = 6
const THINKING_KEY = 'generation-station.chat-thinking'
const THUMBNAIL = 'thumbnail.jpg'
const mainOutput = (job: Job): JobOutput | undefined => job.outputs.find((output) => output.name !== THUMBNAIL && output.name !== job.details?.thumbnail)
const kindOf = (mime?: string | null) => mime?.split('/')[0] ?? ''
const KIND_WORD: Record<string, string> = { image: 'Picture', video: 'Video', audio: 'Sound' }

function readThinking() {
  try { return localStorage.getItem(THINKING_KEY) !== 'off' } catch { return true }
}

/** Chat with the host's text model, which can also make things with the other running models. */
export function ChatPage({ store, host, conversationId }: { store: HostStore; host?: SavedHost; conversationId?: string }) {
  const session = host ? store.session(host.id) : undefined
  const state = useSession(session)
  const [list, setList] = useState<Conversation[] | null>(null)
  const [listError, setListError] = useState('')
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  const [loadError, setLoadError] = useState('')
  const [draft, setDraft] = useState<Draft | null>(null)
  const [sending, setSending] = useState(false)
  const [stopping, setStopping] = useState(false)
  const [error, setError] = useState('')
  const [text, setText] = useState('')
  const [attached, setAttached] = useState<Pick[]>([])
  const [thinking, setThinking] = useState(readThinking)
  const [picking, setPicking] = useState(false)
  const [openJob, setOpenJob] = useState<string | null>(null)
  const streaming = useRef<string | null>(null)
  const abort = useRef<AbortController | null>(null)
  const thread = useRef<HTMLDivElement>(null)
  const connected = state.connection === 'connected'
  // The conversation's own model; for a new one, a chat model that is running (else the first there is).
  const chatRuntime = state.runtimes?.find((runtime) => runtime.chat && runtime.id === loaded?.conversation.model_id)
    ?? state.runtimes?.find((runtime) => runtime.chat && state.models?.find((model) => model.id === runtime.id)?.state === 'ready')
    ?? state.runtimes?.find((runtime) => runtime.chat)
  const chatModel = state.models?.find((model) => model.id === chatRuntime?.id)
  const ready = chatModel?.state === 'ready'

  const refreshList = useCallback(async () => {
    if (!session) return
    try { setList(await session.conversations()); setListError('') } catch (reason) { setListError(reason instanceof Error ? reason.message : 'The conversations could not be loaded.') }
  }, [session])

  useEffect(() => { if (connected) void refreshList() }, [connected, refreshList])

  // Open the conversation in the address; one being answered elsewhere is followed until it finishes.
  useEffect(() => {
    if (!session || !connected) return
    if (!conversationId) { setLoaded(null); setLoadError(''); return }
    if (streaming.current === conversationId) return
    let cancelled = false
    let timer = 0
    const load = async () => {
      try {
        const next = await session.conversation(conversationId)
        if (cancelled) return
        setLoaded(next); setLoadError('')
        if (next.conversation.busy) timer = window.setTimeout(load, 2000)
      } catch (reason) { if (!cancelled) setLoadError(reason instanceof Error ? reason.message : 'This conversation could not be loaded.') }
    }
    setDraft(null); setError('')
    void load()
    return () => { cancelled = true; window.clearTimeout(timer) }
  }, [session, connected, conversationId])

  // Leaving the page drops the stream; the host still finishes and saves the answer.
  useEffect(() => () => abort.current?.abort(), [])

  // Keep the newest message in view as it is written and as pictures and players load, unless the reader
  // has scrolled up to read something earlier.
  const pinned = useRef(true)
  const threadBody = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const element = thread.current
    const body = threadBody.current
    if (!element || !body) return
    const onScroll = () => { pinned.current = element.scrollHeight - element.scrollTop - element.clientHeight < 80 }
    const observer = new ResizeObserver(() => { if (pinned.current) element.scrollTop = element.scrollHeight })
    element.addEventListener('scroll', onScroll, { passive: true })
    observer.observe(body)
    return () => { element.removeEventListener('scroll', onScroll); observer.disconnect() }
  })
  useEffect(() => { pinned.current = true }, [conversationId])

  if (!host || !session) return <div className="empty-models"><div><strong>Host not found</strong><p>This host is no longer saved on this device.</p></div></div>

  const send = async () => {
    const message = text.trim()
    if ((!message && attached.length === 0) || sending || !ready) return
    setError(''); setSending(true)
    let id = conversationId
    try {
      if (!id) {
        const created = await session.createConversation(chatRuntime?.id)
        id = created.id
        streaming.current = id
        setLoaded({ conversation: created, messages: [] })
        window.location.hash = href({ page: 'chat', hostId: host.id, conversationId: id })
      }
      streaming.current = id
      const body = { text: message, attachments: attached.map(({ job_id, name }) => ({ job_id, name })), thinking }
      setText(''); setAttached([])
      abort.current = new AbortController()
      await session.sendMessage(id, body, (event, data) => {
        if (event === 'message') {
          const saved = data as ChatMessage & { job?: Job }
          if (saved.job) session.trackJob(saved.job)
          setLoaded((current) => current && { ...current, messages: [...current.messages.filter((other) => other.id !== saved.id), saved] })
          if (saved.role === 'assistant') setDraft(null)
        } else if (event === 'start') setDraft({ content: '', reasoning: '', tool: '' })
        else if (event === 'delta') {
          const piece = data as Partial<Draft>
          setDraft((current) => {
            const base = current ?? { content: '', reasoning: '', tool: '' }
            return { content: base.content + (piece.content ?? ''), reasoning: base.reasoning + (piece.reasoning ?? ''), tool: piece.tool ?? base.tool }
          })
        } else if (event === 'error') setError((data as { message?: string }).message ?? 'The answer stopped unexpectedly.')
      }, abort.current.signal)
    } catch (reason) {
      if (!(reason instanceof DOMException && reason.name === 'AbortError')) {
        setError(reason instanceof Error ? reason.message : 'The message could not be sent.')
        if (message && !id) setText(message)
      }
    } finally {
      streaming.current = null
      abort.current = null
      setSending(false); setStopping(false); setDraft(null)
      void refreshList()
      if (id) session.conversation(id).then(setLoaded).catch(() => undefined)
    }
  }

  const stop = async () => {
    if (!conversationId) return
    setStopping(true)
    try { await session.stopConversation(conversationId) } catch (reason) { setError(reason instanceof Error ? reason.message : 'It could not be stopped.'); setStopping(false) }
  }

  const remove = async (conversation: Conversation) => {
    try {
      await session.deleteConversation(conversation.id)
      setList((current) => current?.filter((other) => other.id !== conversation.id) ?? null)
      if (conversation.id === conversationId) window.location.hash = href({ page: 'chat', hostId: host.id })
      return ''
    } catch (reason) { return reason instanceof Error ? reason.message : 'It could not be deleted.' }
  }

  const rename = async (title: string) => {
    if (!loaded) return
    try {
      const renamed = await session.renameConversation(loaded.conversation.id, title)
      setLoaded((current) => current && { ...current, conversation: renamed })
      setList((current) => current?.map((other) => other.id === renamed.id ? renamed : other) ?? null)
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'It could not be renamed.') }
  }

  const busy = sending || !!loaded?.conversation.busy
  const title = conversationId ? loaded?.conversation.title ?? 'Conversation' : 'New conversation'
  const openedJob = openJob ? state.jobs.find((job) => job.id === openJob) : undefined
  const openedRuntime = openedJob ? state.runtimes?.find((runtime) => runtime.id === openedJob.model_id) : undefined

  return <>
    {!connected && <div className="overview-connect"><ConnectionBanner state={state} /><a className="button button-primary" href={href({ page: 'connections' })}>Open Connections <ArrowUpRight size={16} /></a></div>}
    <div className={`chat-layout ${conversationId ? 'chat-open' : ''}`}>
      <aside className="chat-list" aria-label="Conversations">
        <a className="button button-primary chat-new" href={href({ page: 'chat', hostId: host.id })}><Plus size={16} aria-hidden="true" />New conversation</a>
        {listError && <p className="operation-error" role="alert">{listError}</p>}
        {list && list.length === 0 && <p className="chat-list-empty">No conversations yet.</p>}
        <ul>{list?.map((conversation) => <ConversationRow key={conversation.id} hostId={host.id} conversation={conversation} active={conversation.id === conversationId} onDelete={remove} />)}</ul>
      </aside>
      <section className="chat-main" aria-label={title}>
        <header className="chat-head">
          <a className="icon-button chat-back" href={href({ page: 'chat', hostId: host.id })} aria-label="All conversations"><ArrowLeft size={18} /></a>
          <ChatTitle key={loaded?.conversation.id ?? 'new'} title={title} editable={!!loaded && !!conversationId} onRename={rename} />
          {chatRuntime && <span className="chat-model"><span>{chatRuntime.name}</span><StatePill state={chatModel?.state ?? 'unknown'}>{stateText[chatModel?.state ?? ''] ?? 'Unknown'}</StatePill></span>}
        </header>
        {state.runtimes && !chatRuntime && <p className="chat-notice">{hostName(host, state)} has no text model to chat with.</p>}
        {chatRuntime && chatModel && !ready && <p className="chat-notice">{chatRuntime.name} is not running. <a href={href({ page: 'models', hostId: host.id })}>Start it on the Models page</a>, then come back.</p>}
        <div className="chat-thread" ref={thread} aria-live="polite" aria-busy={busy}><div className="chat-thread-body" ref={threadBody}>
          {loadError && <p className="operation-error" role="alert">{loadError}</p>}
          {!conversationId && <ChatWelcome runtimes={state.runtimes ?? []} models={state.models ?? []} />}
          {loaded && conversationId && loaded.messages.map((message) => <MessageView key={message.id} message={message} session={session} jobs={state.jobs} runtimes={state.runtimes ?? []} onOpenJob={setOpenJob} />)}
          {draft && <DraftView draft={draft} />}
          {busy && !draft && <div className="chat-msg from-model chat-waiting"><span className="chat-avatar" aria-hidden="true"><Bot size={18} /></span><span><Loader2 size={16} className="spin" aria-hidden="true" /> {sending ? 'Reading…' : 'Answering in another window…'}</span></div>}
          {error && <p className="chat-error" role="alert">{error}</p>}
        </div></div>
        <Composer text={text} setText={setText} attached={attached} setAttached={setAttached} thinking={thinking}
          setThinking={(on) => { setThinking(on); try { localStorage.setItem(THINKING_KEY, on ? 'on' : 'off') } catch { /* per-device preference only */ } }}
          disabled={!ready || !connected} busy={busy} sending={sending} stopping={stopping} onSend={send} onStop={stop} onAttach={() => setPicking(true)} session={session} />
      </section>
    </div>
    <JobModal open={picking} onClose={() => setPicking(false)} title="Attach results">
      {picking && <ResultPicker jobs={state.jobs} runtimes={state.runtimes ?? []} session={session} chosen={attached}
        onDone={(picks) => { setAttached(picks); setPicking(false) }} />}
    </JobModal>
    <JobModal open={!!openedJob && !!openedRuntime?.generation} onClose={() => setOpenJob(null)} title={openedJob ? jobTitle(openedJob) : ''}>
      {openedJob && openedRuntime?.generation && <JobDetail job={openedJob} runtime={openedRuntime} generation={openedRuntime.generation}
        fileUrl={(job, output) => session.fileUrl(job, output)} inputUrl={(job, name) => session.inputUrl(job, name)}
        onReuse={(job) => {
          handOff(host.id, job.model_id, { mode: typeof job.inputs.mode === 'string' ? job.inputs.mode : undefined, inputs: job.inputs })
          window.location.hash = href({ page: 'service', hostId: host.id, modelId: job.model_id })
        }}
        onDelete={async (job) => { const problem = await session.deleteJob(job); if (!problem) setOpenJob(null); return problem }}
        onCancel={(job) => session.cancelJob(job)} />}
    </JobModal>
  </>
}

function ConversationRow({ hostId, conversation, active, onDelete }: { hostId: string; conversation: Conversation; active: boolean; onDelete: (conversation: Conversation) => Promise<string> }) {
  const [confirming, setConfirming] = useState(false)
  const [problem, setProblem] = useState('')
  return <li className={`chat-row ${active ? 'chat-row-on' : ''}`}>
    {confirming ? <div className="chat-row-confirm"><span>Delete “{conversation.title}”?</span>
      <button type="button" className="button button-danger button-small" onClick={async () => { const reason = await onDelete(conversation); if (reason) { setProblem(reason); setConfirming(false) } }}>Delete</button>
      <button type="button" className="button button-secondary button-small" onClick={() => setConfirming(false)}>Keep</button></div>
      : <>
        <a href={href({ page: 'chat', hostId, conversationId: conversation.id })} aria-current={active ? 'page' : undefined}>
          <strong>{conversation.title}</strong><small>{conversation.busy ? 'Answering…' : when(conversation.updated_at)}</small></a>
        <button type="button" className="icon-button chat-row-delete" aria-label={`Delete ${conversation.title}`} title="Delete" onClick={() => setConfirming(true)}><Trash2 size={16} /></button>
      </>}
    {problem && <small className="operation-error">{problem}</small>}
  </li>
}

function ChatTitle({ title, editable, onRename }: { title: string; editable: boolean; onRename: (title: string) => Promise<void> }) {
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(title)
  if (!editing) return <h1 className="chat-title" title={title}><span className="chat-title-text">{title}</span>{editable && <button type="button" className="icon-button" aria-label="Rename" title="Rename" onClick={() => { setValue(title); setEditing(true) }}><Pencil size={16} /></button>}</h1>
  const save = async () => { setEditing(false); if (value.trim() && value.trim() !== title) await onRename(value) }
  return <form className="chat-title-edit" onSubmit={(event) => { event.preventDefault(); void save() }}>
    <input aria-label="Conversation name" value={value} maxLength={200} autoFocus onChange={(event) => setValue(event.target.value)} onKeyDown={(event) => { if (event.key === 'Escape') setEditing(false) }} />
    <button type="submit" className="icon-button" aria-label="Save name"><Check size={16} /></button>
    <button type="button" className="icon-button" aria-label="Cancel" onClick={() => setEditing(false)}><X size={16} /></button>
  </form>
}

function ChatWelcome({ runtimes, models }: { runtimes: Runtime[]; models: { id: string; state: string }[] }) {
  const running = runtimes.filter((runtime) => runtime.generation && models.find((model) => model.id === runtime.id)?.state === 'ready')
  return <div className="chat-welcome">
    <Bot size={32} aria-hidden="true" />
    <h2>What would you like to talk about?</h2>
    <p>Ask anything. Attach earlier results with the paperclip to talk about them or use them in something new.</p>
    <p>{running.length ? <>It can also make things with the models running now: <strong>{running.map((runtime) => runtime.name).join(', ')}</strong>. Ask for a picture, a song, a clip or speech.</>
      : 'Start a picture, video, music or speech model on the Models page and it can make things for you too.'}</p>
  </div>
}

function MessageView({ message, session, jobs, runtimes, onOpenJob }: { message: ChatMessage; session: HostSession; jobs: Job[]; runtimes: Runtime[]; onOpenJob: (id: string) => void }) {
  if (message.role === 'user') return <div className="chat-msg from-user">
    <div className="chat-bubble">
      {message.attachments.length > 0 && <div className="chat-attachments">{message.attachments.map((item) => <AttachmentChip key={`${item.job_id}/${item.name}`} item={item} jobs={jobs} session={session} onOpen={onOpenJob} />)}</div>}
      {message.content && <p className="chat-user-text">{message.content}</p>}
    </div>
  </div>
  if (message.role === 'tool') return message.job_id
    ? <JobCard jobId={message.job_id} jobs={jobs} runtimes={runtimes} session={session} onOpen={onOpenJob} />
    : <p className="chat-tool-note">{message.content}</p>
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

function DraftView({ draft }: { draft: Draft }) {
  return <div className="chat-msg from-model">
    <span className="chat-avatar" aria-hidden="true"><Bot size={18} /></span>
    <div className="chat-answer">
      {draft.reasoning && <Thinking text={draft.reasoning} live={!draft.content} />}
      {draft.content ? <Markdown text={draft.content} /> : !draft.reasoning && !draft.tool && <span className="chat-typing"><Loader2 size={16} className="spin" aria-hidden="true" /> Writing…</span>}
      {draft.tool && <span className="chat-typing"><Loader2 size={16} className="spin" aria-hidden="true" /> Setting up a job…</span>}
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
function JobCard({ jobId, jobs, runtimes, session, onOpen }: { jobId: string; jobs: Job[]; runtimes: Runtime[]; session: HostSession; onOpen: (id: string) => void }) {
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

function Composer({ text, setText, attached, setAttached, thinking, setThinking, disabled, busy, sending, stopping, onSend, onStop, onAttach, session }: {
  text: string; setText: (text: string) => void; attached: Pick[]; setAttached: (picks: Pick[]) => void
  thinking: boolean; setThinking: (on: boolean) => void; disabled: boolean; busy: boolean; sending: boolean; stopping: boolean
  onSend: () => void; onStop: () => void; onAttach: () => void; session: HostSession
}) {
  const area = useRef<HTMLTextAreaElement>(null)
  useEffect(() => {
    const element = area.current
    if (!element) return
    element.style.height = 'auto'
    element.style.height = `${Math.min(element.scrollHeight, 240)}px`
  }, [text])
  const empty = !text.trim() && attached.length === 0
  return <form className="chat-composer" onSubmit={(event) => { event.preventDefault(); onSend() }}>
    {attached.length > 0 && <div className="chat-attachments">{attached.map((pick) => <span key={`${pick.job_id}/${pick.name}`} className="chat-chip">
      <ResultThumb job={pick.job} kind={kindOf(pick.mime)} fileUrl={(j, o) => session.fileUrl(j, o)} />
      <span>{KIND_WORD[kindOf(pick.mime)] ?? 'Result'} · {pick.job_id.slice(0, 8)}</span>
      <button type="button" className="icon-button" aria-label={`Remove ${jobTitle(pick.job)}`} onClick={() => setAttached(attached.filter((other) => other !== pick))}><X size={14} /></button>
    </span>)}</div>}
    <label className="sr-only" htmlFor="chat-input">Message</label>
    <textarea id="chat-input" ref={area} rows={1} value={text} disabled={disabled} maxLength={20000}
      placeholder={disabled ? 'Start a text model to chat' : 'Message'} title="Enter sends; Shift+Enter starts a new line"
      onChange={(event) => setText(event.target.value)}
      onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); onSend() } }} />
    <div className="chat-tools">
      <button type="button" className="button button-secondary button-small" onClick={onAttach} disabled={disabled || attached.length >= MAX_ATTACHMENTS}><Paperclip size={16} aria-hidden="true" />Attach</button>
      <button type="button" className={`button button-small chat-think ${thinking ? 'chat-think-on' : 'button-secondary'}`} aria-pressed={thinking} onClick={() => setThinking(!thinking)}
        title="Thinking first gives better answers to harder questions but takes longer"><Brain size={16} aria-hidden="true" />Think first</button>
      <span className="chat-tools-gap" />
      {busy ? <button type="button" className="button button-secondary" onClick={onStop} disabled={!sending || stopping}>{stopping ? <Loader2 size={16} className="spin" aria-hidden="true" /> : <Square size={14} aria-hidden="true" />}Stop</button>
        : <button type="submit" className="button button-primary" disabled={disabled || empty}><ArrowUp size={16} aria-hidden="true" />Send</button>}
    </div>
  </form>
}

/** Earlier results to attach: newest first, filtered by kind. */
function ResultPicker({ jobs, runtimes, session, chosen, onDone }: { jobs: Job[]; runtimes: Runtime[]; session: HostSession; chosen: Pick[]; onDone: (picks: Pick[]) => void }) {
  const [kind, setKind] = useState('')
  const [picks, setPicks] = useState<Pick[]>(chosen)
  const done = useMemo(() => jobs.filter((job) => job.status === 'done' && mainOutput(job)), [jobs])
  const kinds = [...new Set(done.map((job) => kindOf(mainOutput(job)?.mime)))].filter((item) => KIND_WORD[item])
  const shown = done.filter((job) => !kind || kindOf(mainOutput(job)?.mime) === kind)
  const toggle = (job: Job) => {
    const output = mainOutput(job)!
    setPicks((current) => current.some((pick) => pick.job_id === job.id) ? current.filter((pick) => pick.job_id !== job.id)
      : current.length >= MAX_ATTACHMENTS ? current : [...current, { job_id: job.id, name: output.name, mime: output.mime, model_id: job.model_id, job }])
  }
  return <div className="chat-picker">
    {kinds.length > 1 && <div className="chat-picker-filter" role="group" aria-label="Show">
      {['', ...kinds].map((item) => <button key={item || 'all'} type="button" className={`button button-small ${kind === item ? 'button-primary' : 'button-secondary'}`} aria-pressed={kind === item} onClick={() => setKind(item)}>{item ? `${KIND_WORD[item]}s` : 'All'}</button>)}
    </div>}
    {shown.length === 0 ? <p className="results-empty">No finished results yet.</p>
      : <ul className="chat-picker-grid">{shown.map((job) => {
        const on = picks.some((pick) => pick.job_id === job.id)
        const output = mainOutput(job)!
        return <li key={job.id}><button type="button" className={`chat-pick ${on ? 'chat-pick-on' : ''}`} aria-pressed={on} onClick={() => toggle(job)}>
          <ResultThumb job={job} kind={kindOf(output.mime)} fileUrl={(j, o) => session.fileUrl(j, o)} />
          <span className="chat-pick-text"><strong>{jobTitle(job)}</strong><small>{runtimes.find((runtime) => runtime.id === job.model_id)?.name ?? job.model_id} · {when(job.created_at)}</small></span>
          {on && <Check size={18} className="chat-pick-check" aria-hidden="true" />}
        </button></li>
      })}</ul>}
    <div className="chat-picker-actions">
      <small>{picks.length} of {MAX_ATTACHMENTS} chosen</small>
      <button type="button" className="button button-primary" onClick={() => onDone(picks)}>Attach</button>
    </div>
  </div>
}
