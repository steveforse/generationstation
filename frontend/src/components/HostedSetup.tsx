import { useEffect, useState } from 'react'
import { AlertCircle, CheckCircle2, Loader2, Plus, Trash2 } from 'lucide-react'
import type { HostSession } from '../session'
import type { ProviderSetup, SearchTestResult } from '../types'

const blank = (): ProviderSetup => ({ name: '', base_url: '', api_key_env: '' })
const same = (a: ProviderSetup[], b: ProviderSetup[]) => JSON.stringify(a) === JSON.stringify(b)

/** Host settings: the hosted chat providers (an OpenAI-compatible gateway such as LiteLLM).
 * The token is never entered here: a provider names the environment variable (in the host's environment or its .env file) that holds it. */
export function HostedSetup({ session, connected }: { session: HostSession; connected: boolean }) {
  const [saved, setSaved] = useState<ProviderSetup[] | null>(null)
  const [fromFile, setFromFile] = useState<ProviderSetup[]>([])
  const [items, setItems] = useState<ProviderSetup[]>([])
  const [results, setResults] = useState<Record<number, SearchTestResult>>({})
  const [busy, setBusy] = useState<'' | 'save' | number>('')
  const [message, setMessage] = useState<SearchTestResult | null>(null)

  useEffect(() => {
    if (!connected) return
    session.providerSetups().then((all) => {
      const mine = all.filter((item) => item.origin === 'settings')
      setSaved(mine); setItems(mine); setFromFile(all.filter((item) => item.origin === 'file'))
    }).catch(() => setSaved(null))
  }, [session, connected])

  const change = (index: number, patch: Partial<ProviderSetup>) => { setItems((list) => list.map((item, at) => at === index ? { ...item, ...patch } : item)); setResults({}); setMessage(null) }
  const changed = !!saved && !same(items, saved)
  const test = async (index: number) => {
    setBusy(index)
    try { setResults({ [index]: await session.testProvider(items[index]) }) } catch (reason) { setResults({ [index]: { ok: false, message: reason instanceof Error ? reason.message : 'The test could not run.' } }) }
    finally { setBusy('') }
  }
  const save = async () => {
    setBusy('save'); setMessage(null)
    try {
      const all = await session.saveProviderSetups(items)
      const mine = all.filter((item) => item.origin === 'settings')
      setSaved(mine); setItems(mine); setResults({}); setMessage({ ok: true, message: mine.length ? 'Saved. Tick the models to offer on the Models page, under Hosted.' : 'Saved. No hosted providers are set up here.' })
    } catch (reason) { setMessage({ ok: false, message: reason instanceof Error ? reason.message : 'It could not be saved.' }) }
    finally { setBusy('') }
  }
  return <form className="profile-card settings-section" onSubmit={(event) => { event.preventDefault(); void save() }} aria-labelledby="hosted-title">
    <h2 id="hosted-title">Hosted chat models</h2>
    <p className="settings-help">The chat can also use models on an OpenAI-compatible gateway, such as LiteLLM in front of Bedrock. They run there, not on this computer, so what you send in a chat goes to the gateway. The token is not entered here: name the environment variable that holds it, set in this host's environment or its .env file.</p>
    {fromFile.map((item) => <p key={item.id} className="settings-source">{item.name} is set up in this host's runtimes file.</p>)}
    {items.map((item, index) => <fieldset key={index} className="hosted-setup" disabled={!connected || !!busy}>
      <legend>{item.name || 'New provider'}</legend>
      <div className="field"><label htmlFor={`hp-name-${index}`}>Name</label>
        <input id={`hp-name-${index}`} className="text-input" value={item.name} placeholder="LiteLLM" onChange={(event) => change(index, { name: event.target.value })} /></div>
      <div className="field"><label htmlFor={`hp-url-${index}`}>Gateway address</label>
        <input id={`hp-url-${index}`} className="text-input" type="url" inputMode="url" value={item.base_url ?? ''} placeholder="https://litellm.example.com" onChange={(event) => change(index, { base_url: event.target.value })} /></div>
      <div className="field"><label htmlFor={`hp-key-${index}`}>Token variable</label>
        <input id={`hp-key-${index}`} className="text-input" value={item.api_key_env ?? ''} placeholder="LITELLM_API_KEY" onChange={(event) => change(index, { api_key_env: event.target.value })} />
        <small>The name of the variable, not the token.</small></div>
      <div className="settings-actions">
        <button type="button" className="button button-secondary" onClick={() => void test(index)}>{busy === index && <Loader2 size={16} className="spin" aria-hidden="true" />}Test</button>
        <button type="button" className="button button-secondary" onClick={() => { setItems((list) => list.filter((_, at) => at !== index)); setResults({}) }}><Trash2 size={16} aria-hidden="true" />Remove</button>
      </div>
      {results[index] && <p className={`settings-result ${results[index].ok ? 'settings-ok' : 'settings-problem'}`} role="status">
        {results[index].ok ? <CheckCircle2 size={16} aria-hidden="true" /> : <AlertCircle size={16} aria-hidden="true" />}{results[index].message}</p>}
    </fieldset>)}
    <div className="settings-actions">
      <button type="button" className="button button-secondary" disabled={!connected || !!busy || items.length >= 10} onClick={() => setItems((list) => [...list, blank()])}><Plus size={16} aria-hidden="true" />Add a provider</button>
      <button type="submit" className="button button-primary" disabled={!connected || !!busy || !changed}>{busy === 'save' && <Loader2 size={16} className="spin" aria-hidden="true" />}Save</button>
    </div>
    {message && <p className={`settings-result ${message.ok ? 'settings-ok' : 'settings-problem'}`} role="status">
      {message.ok ? <CheckCircle2 size={16} aria-hidden="true" /> : <AlertCircle size={16} aria-hidden="true" />}{message.message}</p>}
  </form>
}
