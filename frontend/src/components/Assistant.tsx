import { useCallback, useEffect, useRef, useState } from 'react'
import { ArrowUp, ArrowUpRight, Bot, ChevronDown, Loader2, MessageCircleQuestion, RotateCcw, Square } from 'lucide-react'
import { DraftView, MessageView, useChatTurn, usePinnedScroll } from './ChatParts'
import type { SavedHost } from '../hosts'
import { hostedRuntimes } from '../hosted'
import { href, modelRoute } from '../routes'
import { type HostStore, useSession } from '../store'
import type { ChatMessage, Conversation } from '../types'

type Loaded = { conversation: Conversation; messages: ChatMessage[] }

const OPEN_KEY = 'generation-station.assistant-open'
const SUGGESTIONS = ['What can I make here?', 'How do I make a song?', "What's running right now?"]

function readOpen() {
  try { return localStorage.getItem(OPEN_KEY) === 'open' } catch { return false }
}

/**
 * The help assistant: a round button at the bottom right of every page that opens a small chat panel. It keeps
 * one ongoing conversation (also listed on the Chat page), is told which page is open, and offers to start the
 * text model when it is off.
 */
export function AssistantBubble({ store, host, where }: { store: HostStore; host?: SavedHost; where: string }) {
  const session = host ? store.session(host.id) : undefined
  const state = useSession(session)
  const [open, setOpen] = useState(readOpen)
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  const [loadError, setLoadError] = useState('')
  const [text, setText] = useState('')
  const { draft, activity, sending, stopping, error, setError, send, stop } = useChatTurn(session)
  const { thread, body } = usePinnedScroll(loaded?.conversation.id)
  const panel = useRef<HTMLElement>(null)
  const launcher = useRef<HTMLButtonElement>(null)
  const input = useRef<HTMLTextAreaElement>(null)
  const connected = state.connection === 'connected'
  // Like the Chat page: only a running text model is named or used. The thread's own model if it is running, else the one
  // marked for the assistant, else any other that is running. With none running, no model is named: a link goes to the
  // Models page to start one.
  const chats = state.runtimes?.filter((item) => item.chat) ?? []
  const isReady = (id: string) => state.models?.find((model) => model.id === id)?.state === 'ready'
  // Hosted models are always ready; they come after the local ones that are running.
  const running = [...chats.filter((item) => isReady(item.id)), ...hostedRuntimes(state.providers)]
  const runtime = running.find((item) => item.id === loaded?.conversation.model_id) ?? running.find((item) => item.assistant) ?? running[0]
  const ready = !!runtime
  const starting = chats.some((item) => state.pendingModelId === item.id || state.models?.find((model) => model.id === item.id)?.state === 'loading')
  const conversationId = loaded?.conversation.id

  const setOpenSaved = (next: boolean) => {
    setOpen(next)
    try { localStorage.setItem(OPEN_KEY, next ? 'open' : 'closed') } catch { /* a per-device convenience */ }
    if (!next) window.setTimeout(() => launcher.current?.focus(), 0)
  }

  const load = useCallback(async (fresh = false) => {
    if (!session) return
    try {
      setLoaded(fresh ? await session.assistantNew() : await session.assistant())
      setLoadError('')
    } catch (reason) { setLoadError(reason instanceof Error ? reason.message : 'The assistant could not be opened.') }
  }, [session])

  // The thread is fetched when the panel first opens on a connected host (and again after a reconnect).
  useEffect(() => { if (open && connected && !loaded) void load() }, [open, connected, loaded, load])
  useEffect(() => { setLoaded(null) }, [host?.id])
  // An answer being written elsewhere (the same thread open on the Chat page) is followed until it finishes.
  useEffect(() => {
    if (!open || !session || !loaded?.conversation.busy || sending) return
    const timer = window.setTimeout(() => { session.conversation(loaded.conversation.id).then(setLoaded).catch(() => undefined) }, 2000)
    return () => window.clearTimeout(timer)
  }, [open, session, loaded, sending])
  useEffect(() => { if (open && ready) input.current?.focus() }, [open, ready])
  useEffect(() => {
    const element = input.current
    if (!element) return
    element.style.height = 'auto'
    element.style.height = `${Math.min(element.scrollHeight, 160)}px`
  }, [text, open])

  if (!host || !session) return null

  const ask = async (question: string) => {
    const message = question.trim()
    if (!message || sending || !ready || !conversationId) return
    setText('')
    const id = conversationId
    const problem = await send(id, { text: message, attachments: [], thinking: false, where }, (saved) =>
      setLoaded((current) => current && current.conversation.id === id
        ? { ...current, messages: [...current.messages.filter((other) => other.id !== saved.id), saved] } : current))
    if (problem && !loaded?.messages.length) setText(message)
    session.conversation(id).then(setLoaded).catch(() => undefined)
  }

  if (!open) return <button ref={launcher} type="button" className="assistant-launcher" aria-label="Open the assistant" aria-expanded="false"
    title="Ask the assistant for help" onClick={() => setOpenSaved(true)}>
    <MessageCircleQuestion size={26} aria-hidden="true" /><span className="assistant-launcher-label">Assistant</span>
  </button>

  const busy = sending || !!loaded?.conversation.busy
  return <section ref={panel} className="assistant-panel" aria-label="Assistant"
    onKeyDown={(event) => { if (event.key === 'Escape') setOpenSaved(false) }}>
    <header className="assistant-head">
      <span className="assistant-mark" aria-hidden="true"><Bot size={18} /></span>
      <div className="assistant-title"><strong>Assistant</strong><small>{!connected ? 'Not connected' : ready ? `${runtime?.name ?? 'Text model'} · ready` : starting ? 'Starting…' : 'Off'}</small></div>
      <button type="button" className="icon-button" aria-label="Start over" title="Start over (the old conversation stays under Chat)"
        disabled={busy || !connected || !loaded?.messages.length} onClick={() => { setError(''); void load(true) }}><RotateCcw size={16} /></button>
      {conversationId && <a className="icon-button" href={href({ page: 'chat', hostId: host.id, conversationId })} aria-label="Open in Chat" title="Open in Chat"
        onClick={() => setOpenSaved(false)}><ArrowUpRight size={16} /></a>}
      <button type="button" className="icon-button" aria-label="Close the assistant" title="Close" onClick={() => setOpenSaved(false)}><ChevronDown size={18} /></button>
    </header>
    <div className="assistant-thread" ref={thread} aria-live="polite" aria-busy={busy}><div className="chat-thread-body" ref={body}>
      {!connected && <p className="assistant-note">This browser is not connected to the desktop. <a href={href({ page: 'connections' })}>Open Connections</a></p>}
      {connected && state.runtimes && chats.length === 0 && <p className="assistant-note">This desktop has no text model for the assistant.</p>}
      {connected && chats.length > 0 && !ready && <div className="assistant-off">
        <p>{starting ? 'A text model is starting.' : 'No text model is running.'}</p>
        {starting
          ? <p className="assistant-starting"><Loader2 size={16} className="spin" aria-hidden="true" /> Starting…</p>
          : <a className="button button-primary" href={href({ page: 'models', hostId: host.id })} onClick={() => setOpenSaved(false)}>Start one on the Models page <ArrowUpRight size={16} aria-hidden="true" /></a>}
      </div>}
      {loadError && <p className="operation-error" role="alert">{loadError}</p>}
      {connected && loaded && loaded.messages.length === 0 && !draft && <div className="assistant-welcome">
        <p>Hi! I can explain how Generation Station works, walk you through making something, or do it for you.</p>
        <div className="assistant-suggestions">{SUGGESTIONS.map((question) => <button key={question} type="button" className="button button-secondary button-small"
          disabled={!ready || busy} onClick={() => void ask(question)}>{question}</button>)}</div>
      </div>}
      {loaded?.messages.map((message) => <MessageView key={message.id} message={message} session={session} jobs={state.jobs} runtimes={state.runtimes ?? []}
        onOpenJob={(id) => { const job = state.jobs.find((item) => item.id === id); if (job) { setOpenSaved(false); window.location.hash = href(modelRoute(host.id, job.model_id, state.runtimes)) } }} />)}
      {draft && <DraftView draft={draft} />}
      {busy && !draft && <div className="chat-msg from-model chat-waiting"><span className="chat-avatar" aria-hidden="true"><Bot size={18} /></span><span><Loader2 size={16} className="spin" aria-hidden="true" /> {activity || 'Reading…'}</span></div>}
      {error && <p className="chat-error" role="alert">{error}</p>}
    </div></div>
    <form className="assistant-composer" onSubmit={(event) => { event.preventDefault(); void ask(text) }}>
      <label className="sr-only" htmlFor="assistant-input">Ask the assistant</label>
      <textarea id="assistant-input" ref={input} rows={1} value={text} maxLength={20000} disabled={!ready || !connected}
        placeholder={ready ? 'Ask anything about Generation Station' : 'Start a text model to ask'}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void ask(text) } }} />
      {busy ? <button type="button" className="icon-button assistant-send" aria-label="Stop" title="Stop" disabled={!sending || stopping}
        onClick={() => conversationId && void stop(conversationId)}>{stopping ? <Loader2 size={16} className="spin" /> : <Square size={14} />}</button>
        : <button type="submit" className="icon-button assistant-send" aria-label="Send" title="Send" disabled={!ready || !text.trim()}><ArrowUp size={18} /></button>}
    </form>
  </section>
}
