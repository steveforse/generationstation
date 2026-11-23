import type { ReactNode } from 'react'
import { AlertCircle, AlertTriangle, Ban, CheckCircle2, CircleOff, Hourglass, Loader2 } from 'lucide-react'

/** A status pill: a word and a 14px icon, so the state never rests on colour alone (docs/ui-redesign.md §5.6). */
export function StatePill({ state, children, className = 'model-state' }: { state: string; children: ReactNode; className?: string }) {
  return <span className={`${className} state-${state}`}><StateIcon state={state} />{children}</span>
}

export function StateIcon({ state }: { state: string }) {
  const props = { size: 14, 'aria-hidden': true } as const
  switch (state) {
    case 'ready': case 'simulation_ready': case 'done': case 'measured': return <CheckCircle2 {...props} />
    case 'loading': case 'unloading': case 'checking': case 'running': return <Loader2 {...props} className="spin" />
    case 'queued': return <Hourglass {...props} />
    case 'error': case 'cleanup_failed': case 'failed': return <AlertCircle {...props} />
    case 'stale': case 'partial': return <AlertTriangle {...props} />
    case 'cancelled': return <Ban {...props} />
    default: return <CircleOff {...props} />
  }
}
