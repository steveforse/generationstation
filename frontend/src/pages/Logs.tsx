import { useCallback, useEffect, useState } from 'react'
import { AlertCircle, ArrowLeft, Loader2, RefreshCw } from 'lucide-react'
import { ConnectionBanner, hostName } from '../components/HostBits'
import { StatePill } from '../components/StatePill'
import { when } from '../components/Runtime'
import { formatBytes } from '../api'
import type { SavedHost } from '../hosts'
import { href } from '../routes'
import { type HostStore, useSession } from '../store'
import type { LogEntry, LogText } from '../types'

const OUTCOME: Record<string, [string, string]> = {
  ready: ['done', 'Started'], unloaded: ['done', 'Stopped'], failed: ['failed', 'Failed'], refused: ['failed', 'Refused'],
  cleanup_failed: ['failed', 'Stop did not finish'], loading: ['running', 'Starting'], unloading: ['running', 'Stopping'],
}
/** One phrase for a start or stop and how it ended: "Started", "Failed to start", "Refused". */
const outcome = (entry: LogEntry): [string, string] => {
  const [kind, word] = OUTCOME[entry.status ?? ''] ?? ['unknown', entry.status ?? 'Unknown']
  return entry.status === 'failed' ? [kind, `Failed to ${entry.action === 'unload' ? 'stop' : 'start'}`] : [kind, word]
}
const SIZES = [500, 2000, 5000]

/** Model server logs: one per start or stop, newest first, with the outcome and, for one, its last lines. */
export function LogsPage({ store, host, name }: { store: HostStore; host?: SavedHost; name?: string }) {
  const session = host ? store.session(host.id) : undefined
  const state = useSession(session)
  const [logs, setLogs] = useState<LogEntry[] | null>(null)
  const [listError, setListError] = useState('')
  const [onlyProblems, setOnlyProblems] = useState(false)
  const [text, setText] = useState<LogText | null>(null)
  const [textError, setTextError] = useState('')
  const [lines, setLines] = useState(500)
  const [loading, setLoading] = useState(false)
  const connected = state.connection === 'connected'

  const loadList = useCallback(async () => {
    if (!session) return
    try { setLogs(await session.logs()); setListError('') } catch (reason) { setListError(reason instanceof Error ? reason.message : 'The logs could not be listed.') }
  }, [session])
  const loadText = useCallback(async () => {
    if (!session || !name) { setText(null); return }
    setLoading(true)
    try { setText(await session.logText(name, lines)); setTextError('') } catch (reason) { setText(null); setTextError(reason instanceof Error ? reason.message : 'This log could not be read.') }
    finally { setLoading(false) }
  }, [session, name, lines])
  useEffect(() => { if (connected) void loadList() }, [connected, loadList])
  useEffect(() => { if (connected) void loadText() }, [connected, loadText])

  if (!host || !session) return <div className="empty-models"><div><strong>Host not found</strong><p>This host is no longer saved on this device.</p></div></div>
  // Retired entries keep the name the host's database still has for them.
  const modelName = (entry: LogEntry) => state.runtimes?.find((runtime) => runtime.id === entry.model_id)?.name
    ?? state.models?.find((model) => model.id === entry.model_id)?.name ?? entry.model_id ?? entry.kind
  const verb = (entry: LogEntry) => entry.action === 'unload' ? 'Stop' : 'Start'
  const shown = (logs ?? []).filter((entry) => !onlyProblems || outcome(entry)[0] === 'failed')
  const selected = logs?.find((entry) => entry.name === name)

  return <>
    <section className="page-heading"><div><div className="eyebrow"><span className="eyebrow-dot" /> {hostName(host, state)}</div><h1>Logs</h1><p>What each model server wrote when it started, ran and stopped. Look here when a model stopped after an error.</p></div></section>
    {!connected && <div className="overview-connect"><ConnectionBanner state={state} /></div>}
    <div className={`logs-layout ${name ? 'logs-open' : ''}`}>
      <aside className="logs-list" aria-label="Logs">
        <div className="logs-list-head">
          <label className="logs-filter"><input type="checkbox" checked={onlyProblems} onChange={(event) => setOnlyProblems(event.target.checked)} />Only problems</label>
          <button type="button" className="icon-button" aria-label="Refresh the list" title="Refresh" onClick={() => void loadList()}><RefreshCw size={16} /></button>
        </div>
        {listError && <p className="operation-error" role="alert">{listError}</p>}
        {logs && shown.length === 0 && <p className="results-empty">{onlyProblems ? 'No problems logged.' : 'No logs yet.'}</p>}
        <ul>{shown.map((entry) => {
          const [kind, word] = outcome(entry)
          return <li key={entry.name}><a className={`log-row ${entry.name === name ? 'log-row-on' : ''}`} aria-current={entry.name === name ? 'page' : undefined} href={href({ page: 'logs', hostId: host.id, name: entry.name })}>
            <span className="log-row-top"><strong>{modelName(entry)}</strong><StatePill state={kind}>{word}</StatePill></span>
            <small>{when(entry.started_at ?? entry.modified_at)} · {formatBytes(entry.bytes)}</small>
            {entry.error_message && <small className="log-row-error">{entry.error_message}</small>}
          </a></li>
        })}</ul>
      </aside>
      <section className="log-view" aria-label={selected ? `${modelName(selected)} log` : 'Log'}>
        {!name ? <p className="log-placeholder">Choose a log to read it.</p> : <>
          <div className="log-view-head">
            <a className="icon-button log-back" href={href({ page: 'logs', hostId: host.id })} aria-label="All logs"><ArrowLeft size={18} /></a>
            <div className="log-view-title"><strong>{selected ? `${modelName(selected)} · ${verb(selected)}` : name}</strong>
              {selected && <small>{when(selected.started_at ?? selected.modified_at)}</small>}</div>
            <label className="log-size"><span>Last</span><select value={lines} onChange={(event) => setLines(Number(event.target.value))}>{SIZES.map((size) => <option key={size} value={size}>{size.toLocaleString()} lines</option>)}</select></label>
            <button type="button" className="button button-secondary button-small" onClick={() => { void loadText(); void loadList() }} disabled={loading}>{loading ? <Loader2 size={14} className="spin" aria-hidden="true" /> : <RefreshCw size={14} aria-hidden="true" />}Refresh</button>
          </div>
          {selected?.error_message && <p className="log-error"><AlertCircle size={16} aria-hidden="true" /><span>{selected.error_code ? `${selected.error_code}: ` : ''}{selected.error_message}</span></p>}
          {textError && <p className="operation-error" role="alert">{textError}</p>}
          {text && <>{text.truncated && <p className="log-note">Showing the last {text.lines.length.toLocaleString()} lines of {formatBytes(text.bytes)}.</p>}
            <pre className="log-text" tabIndex={0}>{text.lines.length ? text.lines.join('\n') : '(empty)'}</pre></>}
        </>}
      </section>
    </div>
  </>
}
