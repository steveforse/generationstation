import { useCallback, useEffect, useRef, useState } from 'react'
import { Activity, AlertCircle, FileText, Loader2, Menu, MessagesSquare, Plug, Server, Settings, Sparkles } from 'lucide-react'
import { hostName, StatusDot, stateText } from './components/HostBits'
import { groupByWorkload, WorkloadIcon } from './components/WorkloadIcon'
import type { SavedHost } from './hosts'
import { ConnectionsPage } from './pages/Connections'
import { OverviewPage } from './pages/Overview'
import { ChatPage } from './pages/Chat'
import { LogsPage } from './pages/Logs'
import { ModelsPage, ServicePage } from './pages/Service'
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
        {route.page === 'models' && <ModelsPage key={route.hostId} store={store} host={routeHost} />}
        {route.page === 'logs' && <LogsPage key={route.hostId} store={store} host={routeHost} name={route.name} />}
        {route.page === 'chat' && <ChatPage key={route.hostId} store={store} host={routeHost} conversationId={route.conversationId} />}
        {route.page !== 'chat' && <footer className="page-footer"><span>Generation Station <b>·</b> Host-first model management</span><span><span className="footer-dot" /> Measurements are reported by each connected service</span></footer>}
      </div>
    </main>
  </div>
}

function Crumbs({ route, host }: { route: Route; host?: SavedHost }) {
  const state = useSession(host ? store.session(host.id) : undefined)
  const title = route.page === 'connections' ? 'Connections' : route.page === 'overview' ? 'Overview' : route.page === 'models' ? 'Models' : route.page === 'chat' ? 'Chat' : route.page === 'logs' ? 'Logs'
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

/** Running state beside a nav item: never colour alone (a dot and the word "On", or an icon with hidden text). */
function NavState({ state }: { state?: string }) {
  if (state === 'ready') return <span className="nav-state"><span className="nav-state-dot" aria-hidden="true" /><span className="nav-state-text">On</span></span>
  if (state === 'loading' || state === 'unloading') return <span className="nav-busy"><Loader2 size={14} className="spin" aria-hidden="true" /><span className="sr-only">{state === 'loading' ? 'Starting' : 'Stopping'}</span></span>
  if (state === 'error' || state === 'cleanup_failed') return <span className="nav-error"><AlertCircle size={14} aria-hidden="true" /><span className="sr-only">Error</span></span>
  return null
}


function HostNav({ host, current }: { host: SavedHost; current: Route }) {
  const state = useSession(store.session(host.id))
  const runtimes = state.runtimes ?? []
  const running = runtimes.filter((runtime) => state.models?.find((item) => item.id === runtime.id)?.state === 'ready').length
  const name = hostName(host, state)
  const groups = groupByWorkload(runtimes.filter((runtime) => runtime.generation), (runtime) => runtime.workload)
  // Chat sits first under Text: it talks to the text model, which can use every other running model.
  const chatRuntimes = runtimes.filter((runtime) => runtime.chat)
  const chatRuntime = chatRuntimes.find((runtime) => state.models?.find((item) => item.id === runtime.id)?.state === 'ready') ?? chatRuntimes[0]
  const chatState = state.models?.find((item) => item.id === chatRuntime?.id)?.state
  const chatId = `nav-${host.id}-chat`
  return <div className="nav-host" aria-label={`Host ${name}`}>
    <div className="nav-host-label"><StatusDot state={state} /><span className="nav-host-name">{name}</span></div>
    {runtimes.length > 0 && <NavLink route={{ page: 'models', hostId: host.id }} current={current} icon={<Server size={20} />} label="Models"
      title={running ? `Models: ${running} running` : 'Models'}
      badge={running ? <span className="nav-state" title={`${running} running`}><span className="nav-state-dot" aria-hidden="true" /><span className="nav-state-text">{running} on</span></span> : undefined} />}
    {chatRuntime && <div className="nav-group" role="group" aria-labelledby={chatId}>
      <div className="nav-group-label" id={chatId}><WorkloadIcon workload="text" size={18} /><span>Text</span></div>
      <NavLink route={{ page: 'chat', hostId: host.id }} current={current} icon={<span className="nav-rail-icon"><MessagesSquare size={20} /></span>} label="Chat"
        title={stateText[chatState ?? ''] ? `Chat: ${chatRuntime.name} ${stateText[chatState ?? ''].toLowerCase()}` : 'Chat'} badge={<NavState state={chatState} />} />
    </div>}
    {groups.filter((group) => group.key !== 'text' || !chatRuntime).map((group) => {
      const id = `nav-${host.id}-${group.key}`
      return <div className="nav-group" role="group" aria-labelledby={id} key={group.key}>
        <div className="nav-group-label" id={id}><WorkloadIcon workload={group.key} size={18} /><span>{group.label}</span></div>
        {group.items.map((runtime) => {
          const model = state.models?.find((item) => item.id === runtime.id)
          const status = stateText[model?.state ?? '']
          return <NavLink key={runtime.id} route={{ page: 'service', hostId: host.id, modelId: runtime.id }} current={current}
            icon={<span className="nav-rail-icon"><WorkloadIcon workload={runtime.workload} /></span>} label={runtime.name} title={status ? `${runtime.name}: ${status}` : runtime.name}
            badge={<NavState state={model?.state} />} />
        })}
      </div>
    })}
    {state.connection !== 'connected' && state.connection !== 'connecting' && state.connection !== 'reconnecting' && <a className="nav-item nav-muted" href={href({ page: 'connections' })} title={state.connection === 'error' ? 'Connection issue' : 'Not connected'}><Plug size={20} /><span className="nav-item-label">{state.connection === 'error' ? 'Connection issue' : 'Not connected'}</span></a>}
  </div>
}

/** Quiet tools at the bottom of the sidebar: connections and each host's logs. */
function ToolsMenu({ hosts, current }: { hosts: SavedHost[]; current: Route }) {
  const onToolPage = current.page === 'connections' || current.page === 'logs'
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
  return <NavLink route={{ page: 'logs', hostId: host.id }} current={current} icon={<FileText size={18} />} label={`Logs${suffix}`} />
}
