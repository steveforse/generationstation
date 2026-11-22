import { useEffect, useState } from 'react'
import { Activity, Plug, Server, ShieldCheck, Sparkles } from 'lucide-react'
import { hostName, StatusDot, stateText } from './components/HostBits'
import { WorkloadIcon } from './components/WorkloadIcon'
import type { SavedHost } from './hosts'
import { ConnectionsPage } from './pages/Connections'
import { OverviewPage } from './pages/Overview'
import { ModelsPage, ProfilesPage, ServicePage } from './pages/Service'
import { href, type Route, useRoute } from './routes'
import { HostStore, useHosts, useSession } from './store'

const store = new HostStore()
let connectedOnce = false

export default function App() {
  const hosts = useHosts(store)
  const route = useRoute()
  const [clock, setClock] = useState(() => new Date())
  useEffect(() => {
    // Connect saved hosts once per page load (not on React's development double-mount).
    if (!connectedOnce) { connectedOnce = true; store.connectSaved() }
    const id = window.setInterval(() => setClock(new Date()), 30_000)
    return () => window.clearInterval(id)
  }, [])
  const routeHost = 'hostId' in route ? hosts.find((host) => host.id === route.hostId) : undefined

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand-lockup"><div className="brand-mark"><Sparkles size={21} strokeWidth={2.3} /></div><div><strong>generation<span>station</span></strong><small>LOCAL MODEL CONTROL</small></div></div>
      <nav aria-label="Main navigation">
        <div className="nav-label">WORKSPACE</div>
        <NavLink route={{ page: 'overview' }} current={route} icon={<Activity size={17} />} label="Overview" />
        <NavLink route={{ page: 'connections' }} current={route} icon={<Plug size={17} />} label="Connections" />
        {hosts.map((host) => <HostNav key={host.id} host={host} current={route} />)}
      </nav>
      <div className="sidebar-footer"><div className="secure-badge"><ShieldCheck size={17} /><span>Host reported data</span></div><p>Models run on each connected host. Measurements describe that host's service process.</p><span className="version">PREVIEW · 0.2</span></div>
    </aside>
    <main className="main-content">
      <header className="topbar"><Crumbs route={route} host={routeHost} /><div className="topbar-right"><span className="local-time">{clock.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span><span className="top-divider" /><span className="secure-top"><Server size={14} /> {hosts.length} host{hosts.length === 1 ? '' : 's'}</span><span className="avatar" title="Generation Station">GS</span></div></header>
      <div className="page-wrap">
        {route.page === 'overview' && <OverviewPage store={store} hosts={hosts} />}
        {route.page === 'connections' && <ConnectionsPage store={store} hosts={hosts} />}
        {route.page === 'service' && <ServicePage key={`${route.hostId}:${route.modelId}`} store={store} host={routeHost} modelId={route.modelId} />}
        {route.page === 'profiles' && <ProfilesPage key={route.hostId} store={store} host={routeHost} />}
        {route.page === 'models' && <ModelsPage key={route.hostId} store={store} host={routeHost} />}
        <footer className="page-footer"><span>Generation Station <b>·</b> Host-first model management</span><span><span className="footer-dot" /> Measurements are reported by each connected service</span></footer>
      </div>
    </main>
  </div>
}

function Crumbs({ route, host }: { route: Route; host?: SavedHost }) {
  const state = useSession(host ? store.session(host.id) : undefined)
  const title = route.page === 'connections' ? 'Connections' : route.page === 'overview' ? 'Overview' : route.page === 'profiles' ? 'Test profiles' : route.page === 'models' ? 'Models'
    : state.runtimes?.find((runtime) => runtime.id === route.modelId)?.name ?? route.modelId
  return <div className="breadcrumb"><span>{host ? hostName(host, state) : 'Workspace'}</span><span className="crumb-slash">/</span><strong>{title}</strong></div>
}

function sameRoute(a: Route, b: Route) { return href(a) === href(b) }

function NavLink({ route, current, icon, label, badge }: { route: Route; current: Route; icon: React.ReactNode; label: string; badge?: React.ReactNode }) {
  const active = sameRoute(route, current)
  return <a className={`nav-item ${active ? 'active' : ''}`} href={href(route)} aria-current={active ? 'page' : undefined}>{icon}<span>{label}</span>{badge}{active && <span className="nav-indicator" />}</a>
}


function HostNav({ host, current }: { host: SavedHost; current: Route }) {
  const state = useSession(store.session(host.id))
  const runtimes = state.runtimes ?? []
  const running = runtimes.filter((runtime) => state.models?.find((item) => item.id === runtime.id)?.state === 'ready').length
  return <div className="nav-host" aria-label={`Host ${hostName(host, state)}`}>
    <div className="nav-label nav-host-label"><StatusDot state={state} /><span>{hostName(host, state).toUpperCase()}</span></div>
    {runtimes.length > 0 && <NavLink route={{ page: 'models', hostId: host.id }} current={current} icon={<Server size={16} />} label="Models"
      badge={<span className={`nav-state ${running ? 'nav-state-on' : ''}`} title={`${running} running`}>{running ? `${running} on` : ''}</span>} />}
    {runtimes.filter((runtime) => runtime.generation).map((runtime) => {
      const model = state.models?.find((item) => item.id === runtime.id)
      const running = model?.state === 'ready'
      return <NavLink key={runtime.id} route={{ page: 'service', hostId: host.id, modelId: runtime.id }} current={current}
        icon={<WorkloadIcon workload={runtime.workload} />} label={runtime.name}
        badge={<span className={`nav-state ${running ? 'nav-state-on' : ''}`} title={stateText[model?.state ?? ''] ?? ''}>{running ? 'on' : model && ['loading', 'unloading'].includes(model.state) ? '…' : ''}</span>} />
    })}
    {state.connection !== 'connected' && state.connection !== 'connecting' && state.connection !== 'reconnecting' && <a className="nav-item nav-muted" href={href({ page: 'connections' })}><Plug size={16} /><span>{state.connection === 'error' ? 'Connection issue' : 'Not connected'}</span></a>}
  </div>
}
