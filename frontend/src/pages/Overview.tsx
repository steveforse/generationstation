import { ArrowUpRight, MemoryStick, Monitor, Plus } from 'lucide-react'
import { humanAge } from '../api'
import { ConnectionBanner, hostName, stateText } from '../components/HostBits'
import { GpuCard, modelColor, ramSegments, ResourceCard } from '../components/Resources'
import { groupByWorkload, WorkloadIcon } from '../components/WorkloadIcon'
import { StatePill } from '../components/StatePill'
import { jobTitle, ResultThumb, when } from '../components/Runtime'
import type { SavedHost } from '../hosts'
import { href } from '../routes'
import { type HostStore, useHostView, useSession } from '../store'

export function OverviewPage({ store, hosts }: { store: HostStore; hosts: SavedHost[] }) {
  return <>
    <section className="page-heading"><div><div className="eyebrow"><span className="eyebrow-dot" /> Your local AI workspace</div><h1>Overview</h1><p>Every connected host, its memory, and what is running on it.</p></div>
      <a className="button button-secondary" href={href({ page: 'connections' })}><Plus size={16} /> Manage connections</a></section>
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
      <div className="host-icon"><Monitor size={24} /></div>
      <div className="host-main"><span className="micro-label">Host</span><strong>{name}</strong><small>{view.host ? `${view.host.host.hostname} · ${view.host.host.os}` : host.url || 'Same address as this page'}</small></div>
      {view.host && <><div className="host-divider" /><div className="host-attribute"><span className="micro-label">Role</span><strong className={`role-pill role-${view.host.host.role}`}>{view.host.host.role}</strong></div><div className="host-attribute scope-attribute"><span className="micro-label">Measurement scope</span><strong>{view.host.host.scope}</strong></div><div className="host-updated"><span className={`status-dot ${view.live ? 'dot-live' : ''}`} aria-hidden="true" />{(view.live ? humanAge(view.age) || 'Live' : humanAge(view.age)) || 'Not live'}</div></>}
    </section>
    {state.connection !== 'connected' && <div className="overview-connect"><ConnectionBanner state={state} />{state.connection !== 'connecting' && state.connection !== 'reconnecting' && <a className="button button-primary" href={href({ page: 'connections' })}>Open Connections <ArrowUpRight size={16} /></a>}</div>}
    {current && <section className="resource-grid" aria-label={`${name} resource usage`}>
      <ResourceCard title="System memory" icon={<MemoryStick size={20} />} iconClass="icon-violet" memory={view.host?.ram} age={view.age} isCurrent={current} error={view.host?.ram_error ?? undefined} kind="RAM" stale={view.stale} segments={ramSegments(view.host, state.runtimes)} />
      <GpuCard host={view.host} age={view.age} stale={view.stale} isCurrent={current} runtimes={state.runtimes} />
    </section>}
    {services.length > 0 && <div className="overview-services" aria-label={`${name} services`}>
      {/* The same groups, in the same order, as the sidebar. */}
      {groupByWorkload(services, ({ runtime }) => runtime.workload).map((group) => <section className="service-group" key={group.key} aria-labelledby={`overview-${host.id}-${group.key}`}>
        <h3 className="service-group-label" id={`overview-${host.id}-${group.key}`}>{group.label}</h3>
        <div className="service-group-tiles">{group.items.map(({ runtime, model }) => <a key={runtime.id} className="service-tile" href={href(runtime.generation ? { page: 'service', hostId: host.id, modelId: runtime.id } : runtime.chat ? { page: 'chat', hostId: host.id } : { page: 'models', hostId: host.id })}>
          <span className="service-tile-icon" style={{ color: modelColor(state.runtimes, runtime.id), background: `${modelColor(state.runtimes, runtime.id)}1f` }}><WorkloadIcon workload={runtime.workload} /></span>
          <span className="service-tile-text"><strong>{runtime.name}</strong><small>{runtime.workload}</small>
            <StatePill state={model?.state ?? 'unknown'}>{stateText[model?.state ?? ''] ?? model?.state ?? 'Unknown'}</StatePill></span>
        </a>)}</div>
      </section>)}
    </div>}
    {recent.length > 0 && <section className="overview-recent" aria-labelledby={`recent-${host.id}`}><h2 id={`recent-${host.id}`}>Recent results</h2><ul>{recent.map((job) => {
      const runtime = state.runtimes?.find((item) => item.id === job.model_id)
      const session = store.session(host.id)
      return <li key={job.id}><a href={href({ page: 'service', hostId: host.id, modelId: job.model_id })}>
        {runtime?.generation && session ? <ResultThumb job={job} kind={runtime.generation.output_kind} fileUrl={(item, output) => session.fileUrl(item, output)} /> : null}
        <span className="overview-recent-text"><strong>{jobTitle(job)}</strong><small>{runtime?.name ?? job.model_id} · {when(job.created_at)}</small></span>
      </a></li>
    })}</ul></section>}
  </section>
}
