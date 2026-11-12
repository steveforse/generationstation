import { useEffect, useState, useSyncExternalStore } from 'react'
import { loadHosts, saveHosts, type SavedHost } from './hosts'
import { HostSession, type SessionState } from './session'
import type { Snapshot } from './types'

/** Saved hosts plus one live session per host. */
export class HostStore {
  hosts: SavedHost[]
  sessions = new Map<string, HostSession>()
  private listeners = new Set<() => void>()

  constructor(hosts: SavedHost[] = loadHosts()) {
    this.hosts = hosts
    for (const host of hosts) this.sessions.set(host.id, new HostSession(host))
  }

  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener) } }
  getHosts = () => this.hosts
  session(id: string) { return this.sessions.get(id) }

  private commit(hosts: SavedHost[]) {
    this.hosts = hosts
    saveHosts(hosts)
    this.listeners.forEach((listener) => listener())
  }

  save(host: SavedHost) {
    const existing = this.sessions.get(host.id)
    if (existing) existing.update(host)
    else this.sessions.set(host.id, new HostSession(host))
    const index = this.hosts.findIndex((item) => item.id === host.id)
    this.commit(index === -1 ? [...this.hosts, host] : this.hosts.map((item) => item.id === host.id ? host : item))
  }

  remove(id: string) {
    this.sessions.get(id)?.disconnect()
    this.sessions.delete(id)
    this.commit(this.hosts.filter((host) => host.id !== id))
  }

  /** Connect every saved host that has a token (used once at page load). */
  connectSaved() {
    for (const host of this.hosts) if (host.token.trim()) void this.sessions.get(host.id)?.connect()
  }
}

export function useHosts(store: HostStore) {
  return useSyncExternalStore(store.subscribe, store.getHosts)
}

const emptySubscribe = () => () => undefined
const idleState = (): SessionState => ({
  connection: 'idle', message: 'Open Connections to connect this host.', snapshot: null, models: null, profiles: null, runtimes: null, operations: [], jobs: [],
  catalogError: '', actionError: '', pendingModelId: null, refusals: {}, runtimeMessages: {}, jobErrors: {},
})
const IDLE = idleState()

export function useSession(session: HostSession | undefined) {
  return useSyncExternalStore(session?.subscribe ?? emptySubscribe, session?.getState ?? (() => IDLE))
}

/** Age of the latest sample, ticking so stale data visibly stops being "live". */
export function useHostAge(snapshot: Snapshot | null) {
  const [now, setNow] = useState(() => performance.now())
  useEffect(() => {
    const id = window.setInterval(() => setNow(performance.now()), 500)
    return () => window.clearInterval(id)
  }, [])
  if (!snapshot) return { age: null as number | null, stale: true }
  const elapsed = Math.max(0, (now - snapshot.arrivedAt) / 1000)
  const age = snapshot.data.age_seconds === null ? null : Math.max(0, snapshot.data.age_seconds) + elapsed
  return { age, stale: snapshot.data.stale || age === null || age >= snapshot.data.stale_after_seconds }
}

/** Connection-level view used by every page: live, stale, degraded, display label. */
export function useHostView(state: SessionState) {
  const { age, stale: sampleStale } = useHostAge(state.snapshot)
  const stale = sampleStale || (!!state.snapshot && state.connection !== 'connected')
  const host = state.snapshot?.data
  const degraded = state.connection === 'connected' && host?.status === 'degraded'
  const fresh = state.connection === 'connected' && !stale
  const live = fresh && !degraded
  return { age, stale, host, degraded, fresh, live }
}
