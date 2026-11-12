import { AlertCircle, Server, Wifi, WifiOff } from 'lucide-react'
import type { SavedHost } from '../hosts'
import type { SessionState } from '../session'
import { useHostView } from '../store'

export function hostName(host: SavedHost, state: SessionState) {
  return host.label.trim() || state.snapshot?.data.host.label || host.url || 'This computer'
}

export function connectionLabel(state: SessionState, view: ReturnType<typeof useHostView>) {
  const { connection } = state
  return connection === 'connected' && view.stale ? 'Telemetry stale'
    : view.degraded ? 'Live · partial telemetry'
      : connection === 'connected' ? 'Live connection'
        : connection === 'reconnecting' ? 'Reconnecting'
          : connection === 'connecting' ? 'Connecting'
            : connection === 'error' ? 'Connection issue' : 'Not connected'
}

export function ConnectionBanner({ state }: { state: SessionState }) {
  const view = useHostView(state)
  const warn = view.degraded || state.connection === 'reconnecting' || (state.connection === 'connected' && view.stale)
  return <section className={`connection-banner ${view.live ? 'banner-live' : warn ? 'banner-warn' : 'banner-muted'}`} aria-live="polite">
    <div className="connection-symbol">{view.live ? <Wifi size={17} /> : warn ? <AlertCircle size={17} /> : state.connection === 'error' ? <WifiOff size={17} /> : <Server size={17} />}</div>
    <div className="connection-copy"><strong>{connectionLabel(state, view)}</strong><span>{state.message}</span></div>
  </section>
}

export function StatusDot({ state }: { state: SessionState }) {
  const view = useHostView(state)
  const tone = view.live ? 'dot-live' : state.connection === 'error' ? 'dot-error' : state.connection === 'idle' ? 'dot-idle' : 'dot-warn'
  return <span className={`status-dot ${tone}`} aria-label={connectionLabel(state, view)} title={connectionLabel(state, view)} />
}

export const stateText: Record<string, string> = {
  unloaded: 'Stopped', loading: 'Loading', ready: 'Running', unloading: 'Stopping', error: 'Stopped after an error',
  cleanup_failed: 'Stop did not finish', simulation_ready: 'Simulation ready',
}
