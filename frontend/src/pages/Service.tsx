import { Activity, ArrowUpRight } from 'lucide-react'
import { ConnectionBanner, hostName } from '../components/HostBits'
import { ProfileManager } from '../components/Profiles'
import { RuntimeCard } from '../components/Runtime'
import type { SavedHost } from '../hosts'
import { href } from '../routes'
import { type HostStore, useHostView, useSession } from '../store'

function Missing({ title, text }: { title: string; text: string }) {
  return <div className="empty-models"><div><strong>{title}</strong><p>{text}</p></div><a className="button button-secondary" href={href({ page: 'overview' })}>Back to Overview</a></div>
}

export function ServicePage({ store, host, modelId }: { store: HostStore; host?: SavedHost; modelId: string }) {
  const session = host ? store.session(host.id) : undefined
  const state = useSession(session)
  const view = useHostView(state)
  if (!host || !session) return <Missing title="Host not found" text="This host is no longer saved on this device." />
  const runtime = state.runtimes?.find((item) => item.id === modelId)
  const model = state.models?.find((item) => item.id === modelId)
  const operations = state.operations.filter((operation) => operation.model_id === modelId)
  return <>
    <section className="page-heading"><div><div className="eyebrow"><span className="eyebrow-dot" /> {hostName(host, state).toUpperCase()}</div><h1>{runtime?.name ?? modelId}</h1><p>{runtime ? `${runtime.workload} · runs on ${hostName(host, state)}` : 'Waiting for this host’s model list.'}</p></div></section>
    {state.connection !== 'connected' && <div className="overview-connect"><ConnectionBanner state={state} /><a className="button button-primary" href={href({ page: 'connections' })}>Open Connections <ArrowUpRight size={14} /></a></div>}
    {runtime
      ? <RuntimeCard key={`${host.id}:${runtime.id}`} runtime={runtime} model={model} host={view.host} fresh={view.fresh} pending={state.pendingModelId === runtime.id}
          refusal={state.refusals[runtime.id]} message={state.runtimeMessages[runtime.id]} onRun={(r, action, launch) => session.runRuntime(r, action, launch)}
          jobs={state.jobs} jobErrors={state.jobErrors} onGenerate={(r, inputs) => session.runJob(r, inputs)} fileUrl={(job, output) => session.fileUrl(job, output)} />
      : state.runtimes && <Missing title="Service not found" text="This host does not list this service any more." />}
    {operations.length > 0 && <section className="operations-section" aria-labelledby="service-history"><div className="section-heading"><div><h3 id="service-history">History</h3><p>Starts and stops of this service.</p></div></div>
      <div className="operation-list">{operations.map((operation) => <div className="operation-row" key={operation.id}><span className={`operation-mark op-${operation.status}`}><Activity size={15} /></span><div className="operation-copy"><strong>{operation.action === 'load' ? 'Start' : 'Stop'} · {operation.status.replaceAll('_', ' ')}</strong><small>operation {operation.id}</small>{operation.error_message && <small className="operation-error">{operation.error_code ? `${operation.error_code}: ` : ''}{operation.error_message}</small>}</div><span className="simulation-badge">MODEL SERVER</span></div>)}</div></section>}
  </>
}

export function ProfilesPage({ store, host }: { store: HostStore; host?: SavedHost }) {
  const session = host ? store.session(host.id) : undefined
  const state = useSession(session)
  const view = useHostView(state)
  if (!host || !session) return <Missing title="Host not found" text="This host is no longer saved on this device." />
  return <>
    <section className="page-heading"><div><div className="eyebrow"><span className="eyebrow-dot" /> {hostName(host, state).toUpperCase()}</div><h1>Test profiles</h1><p>Simulation profiles exercise capacity checks with a fake worker. Nothing is loaded or generated.</p></div></section>
    {state.connection !== 'connected' && <div className="overview-connect"><ConnectionBanner state={state} /></div>}
    <ProfileManager key={`${host.id}|${view.host?.instance_id ?? 'disconnected'}`} profiles={state.profiles} models={state.models} host={view.host} fresh={view.fresh}
      catalogError={state.catalogError} actionError={state.actionError} operations={state.operations.filter((operation) => operation.simulation)}
      pendingModelId={state.pendingModelId} refusals={state.refusals} onRegister={(profile) => session.registerProfile(profile)}
      onLifecycle={(model, action, profile) => session.runLifecycle(model, action, profile)} />
  </>
}
