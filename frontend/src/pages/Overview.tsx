import { ArrowUpRight, MemoryStick, Monitor, Plus } from 'lucide-react'
import { humanAge } from '../api'
import { ConnectionBanner, hostName, stateText } from '../components/HostBits'
import { GpuCard, modelColor, ramSegments, ResourceCard } from '../components/Resources'
import { WorkloadIcon } from '../components/WorkloadIcon'
import type { SavedHost } from '../hosts'
import { href } from '../routes'
import { type HostStore, useHostView, useSession } from '../store'

export function OverviewPage({ store, hosts }: { store: HostStore; hosts: SavedHost[] }) {
  return <>
    <section className="page-heading"><div><div className="eyebrow"><span className="eyebrow-dot" /> YOUR LOCAL AI WORKSPACE</div><h1>Overview</h1><p>Every connected host, its memory, and what is running on it.</p></div>
      <a className="button button-secondary" href={href({ page: 'connections' })}><Plus size={15} /> Manage connections</a></section>
    {hosts.length === 0 && <div className="empty-models"><div><strong>No hosts yet</strong><p>Add a Generation Station host on the Connections page.</p></div></div>}
    {hosts.map((host) => <HostOverview key={host.id} store={store} host={host} />)}
  </>
}

function HostOverview({ store, host }: { store: HostStore; host: SavedHost }) {
  const state = useSession(store.session(host.id))
  const view = useHostView(state)
  const name = hostName(host, state)
  const current = !!state.snapshot && state.connection !== 'idle'
  const services = (state.runtimes ?? []).map((runtime) => ({ runtime, model: state.models?.find((item) => item.id === runtime.id) }))
  const recent = state.jobs.filter((job) => job.status === 'done').slice(0, 3)
  return <section className="host-overview" aria-label={name}>
    <section className="host-strip" aria-label="Connected host identity">
      <div className="host-icon"><Monitor size={19} /></div>
      <div className="host-main"><span className="micro-label">HOST</span><strong>{name}</strong><small>{view.host ? `${view.host.host.hostname} · ${view.host.host.os}` : host.url || 'Same address as this page'}</small></div>
      {view.host && <><div className="host-divider" /><div className="host-attribute"><span className="micro-label">ROLE</span><strong className={`role-pill role-${view.host.host.role}`}>{view.host.host.role}</strong></div><div className="host-attribute scope-attribute"><span className="micro-label">MEASUREMENT SCOPE</span><strong>{view.host.host.scope}</strong></div><div className="host-updated"><span className={`status-dot ${view.live ? 'dot-live' : ''}`} />{humanAge(view.age)}</div></>}
    </section>
    {state.connection !== 'connected' && <div className="overview-connect"><ConnectionBanner state={state} />{state.connection !== 'connecting' && state.connection !== 'reconnecting' && <a className="button button-primary" href={href({ page: 'connections' })}>Open Connections <ArrowUpRight size={14} /></a>}</div>}
    {current && <section className="resource-grid" aria-label={`${name} resource usage`}>
      <ResourceCard title="System memory" icon={<MemoryStick size={17} />} iconClass="icon-violet" memory={view.host?.ram} age={view.age} isCurrent={current} error={view.host?.ram_error ?? undefined} kind="RAM" stale={view.stale} segments={ramSegments(view.host, state.runtimes)} />
      <GpuCard host={view.host} age={view.age} stale={view.stale} isCurrent={current} runtimes={state.runtimes} />
    </section>}
    {services.length > 0 && <div className="overview-services" aria-label={`${name} services`}>
      {services.map(({ runtime, model }) => <a key={runtime.id} className="service-tile" href={href(runtime.generation ? { page: 'service', hostId: host.id, modelId: runtime.id } : { page: 'models', hostId: host.id })}>
        <span className="service-tile-name"><span className="service-tile-icon" style={{ color: modelColor(state.runtimes, runtime.id), background: `${modelColor(state.runtimes, runtime.id)}1f` }}><WorkloadIcon workload={runtime.workload} /></span><span><strong>{runtime.name}</strong><small>{runtime.workload}</small></span></span>
        <span className={`model-state state-${model?.state ?? 'unknown'}`}>{stateText[model?.state ?? ''] ?? model?.state ?? 'Unknown'}</span>
      </a>)}
    </div>}
    {recent.length > 0 && <div className="overview-recent"><span className="micro-label">RECENT RESULTS</span>{recent.map((job) => {
      const runtime = state.runtimes?.find((item) => item.id === job.model_id)
      const title = typeof job.inputs.style === 'string' ? job.inputs.style : typeof job.inputs.prompt === 'string' ? job.inputs.prompt : 'Untitled'
      return <a key={job.id} href={href({ page: 'service', hostId: host.id, modelId: job.model_id })}>{title} <small>· {runtime?.name ?? job.model_id}</small></a>
    })}</div>}
  </section>
}
