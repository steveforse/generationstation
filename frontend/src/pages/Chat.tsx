import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ArrowLeft, ArrowUp, ArrowUpRight, Bot, Brain, Check, Loader2, Paperclip, Pencil, Plus, Square, Trash2, X } from 'lucide-react'
import { ConnectionBanner, hostName, stateText } from '../components/HostBits'
import { DraftView, KIND_WORD, kindOf, mainOutput, MessageView, useChatTurn, usePinnedScroll } from '../components/ChatParts'
import { JobDetail, JobModal, jobTitle, ResultThumb, when } from '../components/Runtime'
import { ConnectPanel } from '../components/Connect'
import { StatePill } from '../components/StatePill'
import { handOff } from '../voiceSample'
import type { SavedHost } from '../hosts'
import { href } from '../routes'
import type { HostSession } from '../session'
import { type HostStore, useSession } from '../store'
import type { ChatAttachment, ChatMessage, Conversation, Job, Runtime, Thinking } from '../types'

type Loaded = { conversation: Conversation; messages: ChatMessage[] }
type Pick = ChatAttachment & { job: Job }

const MAX_ATTACHMENTS = 6
const THINKING_KEY = 'generation-station.chat-thinking' // the older on/off choice: "off" carries over
const LEVELS_KEY = 'generation-station.chat-thinking-levels' // {model id: level}, per device

const LEVEL_NAMES: Record<string, string> = { off: 'Off', none: 'None', minimal: 'Minimal', low: 'Low', medium: 'Medium', high: 'High', xhigh: 'Extra high', max: 'Max' }
const levelName = (level: string) => LEVEL_NAMES[level] ?? level.charAt(0).toUpperCase() + level.slice(1)

function readLevels(): Record<string, string> {
  try { const saved = JSON.parse(localStorage.getItem(LEVELS_KEY) ?? '{}'); return saved && typeof saved === 'object' ? saved : {} } catch { return {} }
}

/** The level to send: the one chosen for this model if it still takes it, else its default (off if thinking was turned off before levels). */
function chosenLevel(thinking: Thinking | null | undefined, modelId: string | undefined, saved: Record<string, string>): string | null {
  if (!thinking || thinking.levels.length === 0 || !modelId) return null
  const valid = (level?: string) => !!level && (thinking.levels.includes(level) || (level === 'off' && thinking.off))
  const mine = saved[modelId]
  if (valid(mine)) return mine
  let legacy: string | null = null
  try { legacy = localStorage.getItem(THINKING_KEY) } catch { /* no storage */ }
  if (legacy === 'off' && thinking.off) return 'off'
  return thinking.default ?? thinking.levels[thinking.levels.length - 1]
}

/** Chat with the host's text model, which can also make things with the other running models. */
export function ChatPage({ store, host, conversationId }: { store: HostStore; host?: SavedHost; conversationId?: string }) {
  const session = host ? store.session(host.id) : undefined
  const state = useSession(session)
  const [list, setList] = useState<Conversation[] | null>(null)
  const [listError, setListError] = useState('')
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  const [loadError, setLoadError] = useState('')
  const { draft, activity, sending, stopping, error, setError, send: sendTurn, stop: stopTurn } = useChatTurn(session)
  const [text, setText] = useState('')
  const [attached, setAttached] = useState<Pick[]>([])
  const [savedLevels, setSavedLevels] = useState(readLevels)
  const [picking, setPicking] = useState(false)
  const [openJob, setOpenJob] = useState<string | null>(null)
  const streaming = useRef<string | null>(null)
  const connected = state.connection === 'connected'
  // Only running chat models are offered or named. The one answering: the one picked here, else the conversation's own,
  // else the first running. A conversation whose model has stopped moves to a running one when the next message is sent.
  const [pickedId, setPickedId] = useState<string | null>(null)
  useEffect(() => { setPickedId(null) }, [conversationId])
  const running = (state.runtimes ?? []).filter((runtime) => runtime.chat && state.models?.find((model) => model.id === runtime.id)?.state === 'ready')
  const chatRuntime = running.find((runtime) => runtime.id === pickedId)
    ?? running.find((runtime) => runtime.id === loaded?.conversation.model_id)
    ?? running[0]
  const ready = !!chatRuntime
  const thinkingOptions = chatRuntime?.thinking
  const level = chosenLevel(thinkingOptions, chatRuntime?.id, savedLevels)
  const chooseLevel = (next: string) => {
    if (!chatRuntime) return
    const all = { ...savedLevels, [chatRuntime.id]: next }
    setSavedLevels(all)
    try { localStorage.setItem(LEVELS_KEY, JSON.stringify(all)) } catch { /* per-device preference only */ }
  }

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
    setError('')
    void load()
    return () => { cancelled = true; window.clearTimeout(timer) }
  }, [session, connected, conversationId])

  const { thread, body: threadBody } = usePinnedScroll(conversationId)

  if (!host || !session) return <div className="empty-models"><div><strong>Host not found</strong><p>This host is no longer saved on this device.</p></div></div>

  const send = async () => {
    const message = text.trim()
    if ((!message && attached.length === 0) || sending || !ready) return
    let id = conversationId
    try {
      if (!id) {
        const created = await session.createConversation(chatRuntime?.id)
        id = created.id
        streaming.current = id
        setLoaded({ conversation: created, messages: [] })
        window.location.hash = href({ page: 'chat', hostId: host.id, conversationId: id })
      }
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'The conversation could not be started.'); return }
    streaming.current = id
    const model = chatRuntime && loaded && chatRuntime.id !== loaded.conversation.model_id ? { model_id: chatRuntime.id } : {}
    const body = { text: message, attachments: attached.map(({ job_id, name }) => ({ job_id, name })), thinking: level ?? true, ...model }
    setText(''); setAttached([])
    await sendTurn(id, body, (saved) => setLoaded((current) => current && { ...current, messages: [...current.messages.filter((other) => other.id !== saved.id), saved] }))
    streaming.current = null
    void refreshList()
    session.conversation(id).then(setLoaded).catch(() => undefined)
  }

  const stop = async () => { if (conversationId) await stopTurn(conversationId) }

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
          {chatRuntime && (running.length > 1
            ? <label className="chat-model chat-model-pick"><span className="sr-only">Model</span>
              <select value={chatRuntime.id} disabled={busy} onChange={(event) => setPickedId(event.target.value)} aria-label="Model answering">
                {running.map((runtime) => <option key={runtime.id} value={runtime.id}>{runtime.name}</option>)}
              </select></label>
            : <span className="chat-model"><span>{chatRuntime.name}</span><StatePill state="ready">{stateText.ready ?? 'Running'}</StatePill></span>)}
        </header>
        {chatRuntime && session && host && <ConnectPanel kind="chat" runtime={chatRuntime} host={host} session={session} />}
        {state.runtimes && !state.runtimes.some((runtime) => runtime.chat) && <p className="chat-notice">{hostName(host, state)} has no text model to chat with.</p>}
        {state.runtimes?.some((runtime) => runtime.chat) && !ready && state.models && <p className="chat-notice">No text model is running. <a href={href({ page: 'models', hostId: host.id })}>Start one on the Models page</a>, then come back.</p>}
        <div className="chat-thread" ref={thread} aria-live="polite" aria-busy={busy}><div className="chat-thread-body" ref={threadBody}>
          {loadError && <p className="operation-error" role="alert">{loadError}</p>}
          {!conversationId && <ChatWelcome runtimes={state.runtimes ?? []} models={state.models ?? []} />}
          {loaded && conversationId && loaded.messages.map((message) => <MessageView key={message.id} message={message} session={session} jobs={state.jobs} runtimes={state.runtimes ?? []} onOpenJob={setOpenJob} />)}
          {draft && <DraftView draft={draft} />}
          {busy && !draft && <div className="chat-msg from-model chat-waiting"><span className="chat-avatar" aria-hidden="true"><Bot size={18} /></span><span><Loader2 size={16} className="spin" aria-hidden="true" /> {activity || (sending ? 'Reading…' : 'Answering in another window…')}</span></div>}
          {error && <p className="chat-error" role="alert">{error}</p>}
        </div></div>
        <Composer text={text} setText={setText} attached={attached} setAttached={setAttached} thinking={thinkingOptions} level={level} setLevel={chooseLevel}
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

function Composer({ text, setText, attached, setAttached, thinking, level, setLevel, disabled, busy, sending, stopping, onSend, onStop, onAttach, session }: {
  text: string; setText: (text: string) => void; attached: Pick[]; setAttached: (picks: Pick[]) => void
  thinking: Thinking | null | undefined; level: string | null; setLevel: (level: string) => void; disabled: boolean; busy: boolean; sending: boolean; stopping: boolean
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
      <button type="button" className="button button-secondary button-small" onClick={onAttach} disabled={disabled || attached.length >= MAX_ATTACHMENTS}><Paperclip size={16} aria-hidden="true" /><span className="chat-tool-word">Attach</span></button>
      {thinking && level && thinking.levels.length > 0 && <label className={`chat-think ${level !== 'off' ? 'chat-think-on' : ''}`}
        title="How much the model thinks before it answers: more gives better answers to harder questions but takes longer">
        <Brain size={16} aria-hidden="true" /><span className="chat-tool-word">Thinking</span>
        <select value={level} disabled={disabled} onChange={(event) => setLevel(event.target.value)}>
          {(thinking.off ? ['off', ...thinking.levels] : thinking.levels).map((option) => <option key={option} value={option}>{levelName(option)}{option === thinking.default ? ' (default)' : ''}</option>)}
        </select>
      </label>}
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
