import { Fragment, useCallback, useEffect, useRef, useState } from 'react'
import { Activity, FileText, Loader2, Menu, MessagesSquare, NotebookPen, Plug, Server, Settings, SlidersHorizontal, Sparkles } from 'lucide-react'
import { hostedRuntimes } from './hosted'
import { AssistantBubble } from './components/Assistant'
import { hostName, StatusDot, stateText } from './components/HostBits'
import { groupByWorkload, WorkloadIcon } from './components/WorkloadIcon'
import type { SavedHost } from './hosts'
import { ConnectionsPage } from './pages/Connections'
import { OverviewPage } from './pages/Overview'
import { ChatPage } from './pages/Chat'
import { LogsPage } from './pages/Logs'
import { HostSettingsPage } from './pages/HostSettings'
import { ImagesPage } from './pages/Images'
import { MusicPage } from './pages/Music'
import { TranscribePage } from './pages/Transcribe'
import { VideoPage } from './pages/Video'
import { SpeechPage } from './pages/Speech'
import { DecidePage, ModelsPage, ServicePage } from './pages/Service'
import { href, type Route, useRoute } from './routes'
import { HostStore, useHosts, useSession } from './store'

const store = new HostStore()
let connectedOnce = false

export default function App() {
  const hosts = useHosts(store)
  const route = useRoute()
  useEffect(() => {
    // Connect saved hosts once per page load (not on React's development double-mount).
    if (!connectedOnce) { connectedOnce = true; store.connectSaved() }
  }, [])
  const routeHost = 'hostId' in route ? hosts.find((host) => host.id === route.hostId) : undefined
  // Phone: the sidebar is a drawer opened from the Menu button (the CSS only applies it at ≤720px).
  const [menuOpen, setMenuOpen] = useState(false)
  const menuButton = useRef<HTMLButtonElement>(null)
  const sidebar = useRef<HTMLElement>(null)
  const closeMenu = useCallback(() => { setMenuOpen(false); menuButton.current?.focus() }, [])
  useEffect(() => {
    if (!menuOpen) return
    const focusables = () => Array.from(sidebar.current?.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])') ?? [])
    const frame = window.requestAnimationFrame(() => focusables()[0]?.focus())
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); closeMenu(); return }
      if (event.key !== 'Tab') return
      // Keep focus inside the drawer while it is open.
      const items = focusables()
      if (!items.length) return
      const first = items[0]
      const last = items[items.length - 1]
      const inside = sidebar.current?.contains(document.activeElement)
      if (!inside) { event.preventDefault(); (event.shiftKey ? last : first).focus() }
      else if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
    }
    const phone = window.matchMedia('(max-width: 720px)')
    const onWidth = () => { if (!phone.matches) setMenuOpen(false) }
    document.addEventListener('keydown', onKey)
    window.addEventListener('hashchange', closeMenu)
    phone.addEventListener('change', onWidth)
    document.body.classList.add('drawer-open')
    return () => {
      window.cancelAnimationFrame(frame)
      document.removeEventListener('keydown', onKey)
      window.removeEventListener('hashchange', closeMenu)
      phone.removeEventListener('change', onWidth)
      document.body.classList.remove('drawer-open')
    }
  }, [menuOpen, closeMenu])

  return <div className={`app-shell ${menuOpen ? 'menu-open' : ''}`}>
    {menuOpen && <div className="drawer-backdrop" onClick={closeMenu} aria-hidden="true" />}
    <aside className="sidebar" id="sidebar" ref={sidebar}><div className="sidebar-inner">
      <div className="brand-lockup"><div className="brand-mark"><Sparkles size={24} strokeWidth={2.3} /></div><div><strong>generation<span>station</span></strong><small>Local model control</small></div></div>
      <nav aria-label="Main navigation" onClick={(event) => { if (menuOpen && (event.target as Element).closest('a')) closeMenu() }}>
        <NavLink route={{ page: 'overview' }} current={route} icon={<Activity size={20} />} label="Overview" />
        {hosts.map((host) => <HostNav key={host.id} host={host} current={route} />)}
      </nav>
      <ToolsMenu hosts={hosts} current={route} />
    </div></aside>
    <main className="main-content">
      <header className="topbar"><button ref={menuButton} type="button" className="icon-button menu-button" aria-label="Menu" aria-expanded={menuOpen} aria-controls="sidebar" onClick={() => setMenuOpen((open) => !open)}><Menu size={20} aria-hidden="true" /></button><Crumbs route={route} host={routeHost} /><div className="topbar-right"><span className="secure-top"><Server size={16} /> {hosts.length} host{hosts.length === 1 ? '' : 's'}</span><span className="avatar" title="Generation Station">GS</span></div></header>
      <div className="page-wrap">
        {route.page === 'overview' && <OverviewPage store={store} hosts={hosts} />}
        {route.page === 'connections' && <ConnectionsPage store={store} hosts={hosts} />}
        {route.page === 'service' && <ServicePage key={`${route.hostId}:${route.modelId}`} store={store} host={routeHost} modelId={route.modelId} />}
        {route.page === 'images' && <ImagesPage key={route.hostId} store={store} host={routeHost} />}
        {route.page === 'music' && <MusicPage key={route.hostId} store={store} host={routeHost} />}
        {route.page === 'video' && <VideoPage key={route.hostId} store={store} host={routeHost} />}
        {route.page === 'transcribe' && <TranscribePage key={route.hostId} store={store} host={routeHost} />}
        {route.page === 'speech' && <SpeechPage key={route.hostId} store={store} host={routeHost} />}
        {route.page === 'decide' && <DecidePage key={route.hostId} store={store} host={routeHost} />}
        {route.page === 'models' && <ModelsPage key={route.hostId} store={store} host={routeHost} />}
        {route.page === 'settings' && <HostSettingsPage key={route.hostId} store={store} host={routeHost} />}
        {route.page === 'logs' && <LogsPage key={route.hostId} store={store} host={routeHost} name={route.name} />}
        {route.page === 'chat' && <ChatPage key={route.hostId} store={store} host={routeHost} conversationId={route.conversationId} />}
        {route.page !== 'chat' && <footer className="page-footer"><span>Generation Station <b>·</b> Host-first model management</span><span><span className="footer-dot" /> Measurements are reported by each connected service</span></footer>}
      </div>
    </main>
    {route.page !== 'chat' && <AssistantSlot route={route} host={routeHost ?? hosts[0]} />}
  </div>
}

/** The help bubble for the host being looked at, told which page is open (it is the Chat page's own model). */
function AssistantSlot({ route, host }: { route: Route; host?: SavedHost }) {
  const state = useSession(host ? store.session(host.id) : undefined)
  const page = route.page === 'service' ? `the ${state.runtimes?.find((runtime) => runtime.id === route.modelId)?.name ?? route.modelId} page`
    : route.page === 'models' ? 'the Models page' : route.page === 'decide' ? 'the Decision page' : route.page === 'speech' ? 'the Speech page' : route.page === 'images' ? 'the Images page' : route.page === 'music' ? 'the Music page' : route.page === 'video' ? 'the Video page' : route.page === 'transcribe' ? 'the Transcription page' : route.page === 'overview' ? 'the Overview page' : route.page === 'logs' ? 'the Logs page'
      : route.page === 'settings' ? 'the Host settings page' : route.page === 'connections' ? 'the Connections page' : 'a page'
  return <AssistantBubble store={store} host={host} where={page} />
}

function Crumbs({ route, host }: { route: Route; host?: SavedHost }) {
  const state = useSession(host ? store.session(host.id) : undefined)
  const title = route.page === 'connections' ? 'Connections' : route.page === 'overview' ? 'Overview' : route.page === 'models' ? 'Models' : route.page === 'decide' ? 'Decision' : route.page === 'speech' ? 'Speech' : route.page === 'images' ? 'Images' : route.page === 'music' ? 'Music' : route.page === 'video' ? 'Video' : route.page === 'transcribe' ? 'Transcription' : route.page === 'chat' ? 'Chat' : route.page === 'logs' ? 'Logs' : route.page === 'settings' ? 'Host settings'
    : state.runtimes?.find((runtime) => runtime.id === route.modelId)?.name ?? route.modelId
  return <div className="breadcrumb"><span className="crumb-host">{host ? hostName(host, state) : 'Workspace'}</span><span className="crumb-slash" aria-hidden="true">/</span><strong>{title}</strong></div>
}

function sameRoute(a: Route, b: Route) {
  if (a.page === 'chat' && b.page === 'chat') return a.hostId === b.hostId  // every conversation is under Chat
  if (a.page === 'logs' && b.page === 'logs') return a.hostId === b.hostId  // and every log under Logs
  return href(a) === href(b)
}

function NavLink({ route, current, icon, label, badge, title }: { route: Route; current: Route; icon: React.ReactNode; label: string; badge?: React.ReactNode; title?: string }) {
  const active = sameRoute(route, current)
  return <a className={`nav-item ${active ? 'active' : ''}`} href={href(route)} aria-current={active ? 'page' : undefined} title={title ?? label}>{icon}<span className="nav-item-label">{label}</span>{badge}</a>
}

/** Running state beside a nav item: never colour alone (a dot and the word "On", or an icon with hidden text).
 * Errors are left to the model's own page and the Models page; the sidebar shows only on and busy. */
function NavState({ state }: { state?: string }) {
  if (state === 'ready') return <span className="nav-state"><span className="nav-state-dot" aria-hidden="true" /><span className="nav-state-text">On</span></span>
  if (state === 'loading' || state === 'unloading') return <span className="nav-busy"><Loader2 size={14} className="spin" aria-hidden="true" /><span className="sr-only">{state === 'loading' ? 'Starting' : 'Stopping'}</span></span>
  return null
}

/** The state named in a nav item's tooltip, without errors (see NavState). */
function navStatus(state?: string) {
  return state === 'error' || state === 'cleanup_failed' ? undefined : stateText[state ?? '']
}


function HostNav({ host, current }: { host: SavedHost; current: Route }) {
  const state = useSession(store.session(host.id))
  const runtimes = state.runtimes ?? []
  const running = runtimes.filter((runtime) => state.models?.find((item) => item.id === runtime.id)?.state === 'ready').length
  const name = hostName(host, state)
  // Decision models are one Decision entry (they all share a page).
  const decisionRuntimes = runtimes.filter((runtime) => runtime.generation && runtime.workload === 'decision')
  const groups = groupByWorkload(runtimes.filter((runtime) => runtime.generation && runtime.workload !== 'decision' && runtime.workload !== 'speech' && runtime.workload !== 'image' && runtime.workload !== 'music' && runtime.workload !== 'video' && runtime.workload !== 'transcription' && runtime.workload !== 'workflow'), (runtime) => runtime.workload, (runtime) => runtime.name)
  // Workflows (Meeting notes is the first) are not models: they sit apart, below a rule.
  const workflowRuntimes = runtimes.filter((runtime) => runtime.generation && runtime.workload === 'workflow').sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }))
  const decideOn = decisionRuntimes.some((runtime) => state.models?.find((item) => item.id === runtime.id)?.state === 'ready')
  const decideLoading = decisionRuntimes.some((runtime) => state.models?.find((item) => item.id === runtime.id)?.state === 'loading')
  const decideLink = decisionRuntimes.length > 0 ? <NavLink route={{ page: 'decide', hostId: host.id }} current={current} icon={<WorkloadIcon workload="decision" />} label="Decision"
    title={decideOn ? 'Decision: a model is running' : 'Decision'} badge={<NavState state={decideOn ? 'ready' : decideLoading ? 'loading' : undefined} />} /> : null
  // Speech models share one Speech entry.
  const speechRuntimes = runtimes.filter((runtime) => runtime.generation && runtime.workload === 'speech')
  const speechOn = speechRuntimes.some((runtime) => state.models?.find((item) => item.id === runtime.id)?.state === 'ready')
  const speechLoading = speechRuntimes.some((runtime) => state.models?.find((item) => item.id === runtime.id)?.state === 'loading')
  // Picture models share one Images entry (a video model with picture tabs counts too).
  const imageRuntimes = runtimes.filter((runtime) => runtime.generation?.image)
  const imagesOn = imageRuntimes.some((runtime) => state.models?.find((item) => item.id === runtime.id)?.state === 'ready')
  const imagesLoading = imageRuntimes.some((runtime) => state.models?.find((item) => item.id === runtime.id)?.state === 'loading')
  // Song models share one Music entry.
  const musicRuntimes = runtimes.filter((runtime) => runtime.generation?.music)
  const musicOn = musicRuntimes.some((runtime) => state.models?.find((item) => item.id === runtime.id)?.state === 'ready')
  const musicLoading = musicRuntimes.some((runtime) => state.models?.find((item) => item.id === runtime.id)?.state === 'loading')
  // Video models share one Video entry.
  const videoRuntimes = runtimes.filter((runtime) => runtime.generation?.video)
  const videoOn = videoRuntimes.some((runtime) => state.models?.find((item) => item.id === runtime.id)?.state === 'ready')
  const videoLoading = videoRuntimes.some((runtime) => state.models?.find((item) => item.id === runtime.id)?.state === 'loading')
  // Speech-to-text models share one Transcribe entry.
  const transcribeRuntimes = runtimes.filter((runtime) => runtime.generation?.transcribe)
  const transcribeOn = transcribeRuntimes.some((runtime) => state.models?.find((item) => item.id === runtime.id)?.state === 'ready')
  const transcribeLoading = transcribeRuntimes.some((runtime) => state.models?.find((item) => item.id === runtime.id)?.state === 'loading')
  // Chat sits first under Text: it talks to the text model, which can use every other running model.
  const hostedChat = hostedRuntimes(state.providers)
  const chatRuntimes = runtimes.filter((runtime) => runtime.chat)
  const chatRuntime = chatRuntimes.find((runtime) => state.models?.find((item) => item.id === runtime.id)?.state === 'ready') ?? hostedChat[0] ?? chatRuntimes[0]
  const chatState = hostedChat.some((runtime) => runtime.id === chatRuntime?.id) ? 'ready' : state.models?.find((item) => item.id === chatRuntime?.id)?.state
    // The tools that serve several models (or one tool, like meeting notes) sit directly in the sidebar, alphabetical:
  // Chat, Decision, Images, Music, Speech, Transcribe, Video. Workflows (Meeting notes) follow a rule below them. Only generators with their own page are grouped by what they make.
  const toolEntries = [
    ...(chatRuntime ? [{ label: 'Chat', node: <NavLink key="chat" route={{ page: 'chat', hostId: host.id }} current={current} icon={<MessagesSquare size={20} />} label="Chat"
      title={navStatus(chatState) ? `Chat: ${chatRuntime.name} ${navStatus(chatState)?.toLowerCase()}` : 'Chat'} badge={<NavState state={chatState} />} /> }] : []),
    ...(decideLink ? [{ label: 'Decision', node: <Fragment key="decide">{decideLink}</Fragment> }] : []),
    ...(groups.find((group) => group.key === 'text')?.items ?? []).map((runtime) => {
      const model = state.models?.find((item) => item.id === runtime.id)
      const status = navStatus(model?.state)
      return { label: runtime.name, node: <NavLink key={runtime.id} route={{ page: 'service', hostId: host.id, modelId: runtime.id }} current={current}
        icon={<NotebookPen size={20} />} label={runtime.name} title={status ? `${runtime.name}: ${status}` : runtime.name}
        badge={<NavState state={model?.state} />} /> }
    }),
    ...(imageRuntimes.length > 0 ? [{ label: 'Images', node: <NavLink key="images" route={{ page: 'images', hostId: host.id }} current={current} icon={<WorkloadIcon workload="image" />} label="Images"
      title={imagesOn ? 'Images: a model is running' : 'Images'} badge={<NavState state={imagesOn ? 'ready' : imagesLoading ? 'loading' : undefined} />} /> }] : []),
    ...(musicRuntimes.length > 0 ? [{ label: 'Music', node: <NavLink key="music" route={{ page: 'music', hostId: host.id }} current={current} icon={<WorkloadIcon workload="music" />} label="Music"
      title={musicOn ? 'Music: a model is running' : 'Music'} badge={<NavState state={musicOn ? 'ready' : musicLoading ? 'loading' : undefined} />} /> }] : []),
    ...(videoRuntimes.length > 0 ? [{ label: 'Video', node: <NavLink key="video" route={{ page: 'video', hostId: host.id }} current={current} icon={<WorkloadIcon workload="video" />} label="Video"
      title={videoOn ? 'Video: a model is running' : 'Video'} badge={<NavState state={videoOn ? 'ready' : videoLoading ? 'loading' : undefined} />} /> }] : []),
    ...(transcribeRuntimes.length > 0 ? [{ label: 'Transcription', node: <NavLink key="transcribe" route={{ page: 'transcribe', hostId: host.id }} current={current} icon={<WorkloadIcon workload="transcription" />} label="Transcription"
      title={transcribeOn ? 'Transcription: a model is running' : 'Transcription'} badge={<NavState state={transcribeOn ? 'ready' : transcribeLoading ? 'loading' : undefined} />} /> }] : []),
    ...(speechRuntimes.length > 0 ? [{ label: 'Speech', node: <NavLink key="speech" route={{ page: 'speech', hostId: host.id }} current={current} icon={<WorkloadIcon workload="speech" />} label="Speech"
      title={speechOn ? 'Speech: a model is running' : 'Speech'} badge={<NavState state={speechOn ? 'ready' : speechLoading ? 'loading' : undefined} />} /> }] : []),
  ].sort((a, b) => a.label.localeCompare(b.label, undefined, { sensitivity: 'base' }))
  return <div className="nav-host" aria-label={`Host ${name}`}>
    <div className="nav-host-label"><StatusDot state={state} /><span className="nav-host-name">{name}</span></div>
    {runtimes.length > 0 && <NavLink route={{ page: 'models', hostId: host.id }} current={current} icon={<Server size={20} />} label="Models"
      title={running ? `Models: ${running} running` : 'Models'}
      badge={running ? <span className="nav-state" title={`${running} running`}><span className="nav-state-dot" aria-hidden="true" /><span className="nav-state-text">{running} on</span></span> : undefined} />}
    {toolEntries.length > 0 && runtimes.length > 0 && <hr className="nav-separator" />}
    {toolEntries.map((entry) => entry.node)}
    {groups.filter((group) => group.key !== 'text').map((group) => {
      const id = `nav-${host.id}-${group.key}`
      return <div className="nav-group" role="group" aria-labelledby={id} key={group.key}>
        <div className="nav-group-label" id={id}><WorkloadIcon workload={group.key} size={18} /><span>{group.label}</span></div>
        {group.items.map((runtime) => {
          const model = state.models?.find((item) => item.id === runtime.id)
          const status = navStatus(model?.state)
          return <NavLink key={runtime.id} route={{ page: 'service', hostId: host.id, modelId: runtime.id }} current={current}
            icon={<span className="nav-rail-icon"><WorkloadIcon workload={runtime.workload} /></span>} label={runtime.name} title={status ? `${runtime.name}: ${status}` : runtime.name}
            badge={<NavState state={model?.state} />} />
        })}
      </div>
    })}
    {workflowRuntimes.length > 0 && <>
      <hr className="nav-separator" />
      <div className="nav-group" role="group" aria-labelledby={`nav-${host.id}-workflow`}>
        <div className="nav-group-label" id={`nav-${host.id}-workflow`}><WorkloadIcon workload="workflow" size={18} /><span>Workflows</span></div>
        {workflowRuntimes.map((runtime) => {
          const model = state.models?.find((item) => item.id === runtime.id)
          const status = navStatus(model?.state)
          return <NavLink key={runtime.id} route={{ page: 'service', hostId: host.id, modelId: runtime.id }} current={current}
            icon={<NotebookPen size={20} />} label={runtime.name} title={status ? `${runtime.name}: ${status}` : runtime.name}
            badge={<NavState state={model?.state} />} />
        })}
      </div>
    </>}
    {state.connection !== 'connected' && state.connection !== 'connecting' && state.connection !== 'reconnecting' && <a className="nav-item nav-muted" href={href({ page: 'connections' })} title={state.connection === 'error' ? 'Connection issue' : 'Not connected'}><Plug size={20} /><span className="nav-item-label">{state.connection === 'error' ? 'Connection issue' : 'Not connected'}</span></a>}
  </div>
}

/** Quiet tools at the bottom of the sidebar: connections, and each host's settings and logs. */
function ToolsMenu({ hosts, current }: { hosts: SavedHost[]; current: Route }) {
  const onToolPage = current.page === 'connections' || current.page === 'logs' || current.page === 'settings'
  const [open, setOpen] = useState(onToolPage)
  useEffect(() => { if (onToolPage) setOpen(true) }, [onToolPage])
  return <div className="sidebar-tools">
    {open && <nav id="tools-menu" className="tools-menu" aria-label="Settings">
      <NavLink route={{ page: 'connections' }} current={current} icon={<Plug size={18} />} label="Connections" />
      {hosts.map((host) => <ToolsHostLinks key={host.id} host={host} current={current} several={hosts.length > 1} />)}
    </nav>}
    <button type="button" className="nav-item tools-toggle" aria-expanded={open} aria-controls="tools-menu" title="Settings" onClick={() => setOpen(!open)}>
      <Settings size={20} aria-hidden="true" /><span className="nav-item-label">Settings</span></button>
  </div>
}

function ToolsHostLinks({ host, current, several }: { host: SavedHost; current: Route; several: boolean }) {
  const state = useSession(store.session(host.id))
  const suffix = several ? ` · ${hostName(host, state)}` : ''
  return <>
    <NavLink route={{ page: 'settings', hostId: host.id }} current={current} icon={<SlidersHorizontal size={18} />} label={`Host settings${suffix}`} />
    <NavLink route={{ page: 'logs', hostId: host.id }} current={current} icon={<FileText size={18} />} label={`Logs${suffix}`} />
  </>
}
