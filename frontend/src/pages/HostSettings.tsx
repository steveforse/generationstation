import { useEffect, useState } from 'react'
import { AlertCircle, CheckCircle2, Loader2 } from 'lucide-react'
import { HostedSetup } from '../components/HostedSetup'
import { ConnectionBanner, hostName } from '../components/HostBits'
import type { SavedHost } from '../hosts'
import { type HostStore, useSession } from '../store'
import type { HostSettings, SearchTestResult } from '../types'

/** Settings kept on the host, for every browser that connects to it. */
export function HostSettingsPage({ store, host }: { store: HostStore; host?: SavedHost }) {
  const session = host ? store.session(host.id) : undefined
  const state = useSession(session)
  const [saved, setSaved] = useState<HostSettings | null>(null)
  const [url, setUrl] = useState('')
  const [loadError, setLoadError] = useState('')
  const [result, setResult] = useState<SearchTestResult | null>(null)
  const [busy, setBusy] = useState<'' | 'test' | 'save'>('')
  const connected = state.connection === 'connected'

  useEffect(() => {
    if (!session || !connected) return
    session.settings().then((value) => { setSaved(value); setUrl(value.searxng_url); setLoadError('') })
      .catch((reason) => setLoadError(reason instanceof Error ? reason.message : 'The settings could not be loaded.'))
  }, [session, connected])

  if (!host || !session) return <div className="empty-models"><div><strong>Host not found</strong><p>This host is no longer saved on this device.</p></div></div>
  const changed = !!saved && url.trim().replace(/\/+$/, '') !== saved.searxng_url
  const test = async () => {
    setBusy('test'); setResult(null)
    try { setResult(await session.testSearch(url.trim())) } catch (reason) { setResult({ ok: false, message: reason instanceof Error ? reason.message : 'The test could not run.' }) }
    finally { setBusy('') }
  }
  const save = async () => {
    setBusy('save'); setResult(null)
    try {
      const value = await session.saveSettings(url.trim())
      setSaved(value); setUrl(value.searxng_url)
      setResult({ ok: true, message: value.searxng_url ? 'Saved. The chat uses it from its next answer.' : 'Saved. Web search is off.' })
    } catch (reason) { setResult({ ok: false, message: reason instanceof Error ? reason.message : 'It could not be saved.' }) }
    finally { setBusy('') }
  }
  return <>
    <section className="page-heading"><div><div className="eyebrow"><span className="eyebrow-dot" /> {hostName(host, state)}</div><h1>Host settings</h1><p>Settings kept on {hostName(host, state)}, for every browser that connects to it.</p></div></section>
    {!connected && <div className="overview-connect"><ConnectionBanner state={state} /></div>}
    {loadError && <p className="operation-error" role="alert">{loadError}</p>}
    <form className="profile-card settings-section" onSubmit={(event) => { event.preventDefault(); void save() }} aria-labelledby="web-search-title">
      <h2 id="web-search-title">Web search</h2>
      <p className="settings-help">The chat searches the web through a SearXNG service you run, such as one on your home server. Leave the address empty to turn search off. The chat can read web pages either way.</p>
      <div className="field">
        <label htmlFor="searxng-url">Search service address</label>
        <input id="searxng-url" className="text-input" type="url" inputMode="url" placeholder="http://searxng.example.lan" value={url}
          disabled={!saved || !!busy} onChange={(event) => { setUrl(event.target.value); setResult(null) }} />
        {saved?.searxng_source === 'environment' && !changed && <small className="settings-source">Set in this host's .env file. Saving here takes its place.</small>}
      </div>
      <div className="settings-actions">
        <button type="button" className="button button-secondary" disabled={!saved || !!busy || !url.trim()} onClick={() => void test()}>{busy === 'test' && <Loader2 size={16} className="spin" aria-hidden="true" />}Test</button>
        <button type="submit" className="button button-primary" disabled={!saved || !!busy || !changed}>{busy === 'save' && <Loader2 size={16} className="spin" aria-hidden="true" />}Save</button>
      </div>
      {result && <p className={`settings-result ${result.ok ? 'settings-ok' : 'settings-problem'}`} role="status">
        {result.ok ? <CheckCircle2 size={16} aria-hidden="true" /> : <AlertCircle size={16} aria-hidden="true" />}{result.message}</p>}
    </form>
    <HostedSetup session={session} connected={connected} />
  </>
}
