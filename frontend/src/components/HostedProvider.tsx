import { useState } from 'react'
import { RefreshCw } from 'lucide-react'
import type { HostedProvider } from '../types'

/** One hosted provider on the Models page: every model it lists, with a box for each one the Chat should offer. Nothing runs on
 * this computer for these models, so there is no start or stop, only the choice and the state of the connection. */
export function HostedProviderSection({ provider, onChoose, onRefresh }: { provider: HostedProvider; onChoose: (ids: string[]) => Promise<void>; onRefresh: () => Promise<void> }) {
  const [filter, setFilter] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const on = provider.models.filter((model) => model.enabled)
  const shown = provider.models.filter((model) => `${model.name} ${model.id}`.toLowerCase().includes(filter.trim().toLowerCase()))
  const run = async (work: () => Promise<void>) => {
    setBusy(true); setError('')
    try { await work() } catch (reason) { setError(reason instanceof Error ? reason.message : 'That did not work.') } finally { setBusy(false) }
  }
  const toggle = (id: string, enabled: boolean) => run(() => onChoose(provider.models.filter((model) => (model.id === id ? enabled : model.enabled)).map((model) => model.id)))
  const id = `hosted-${provider.id}`
  return <section className="models-group hosted-group" aria-labelledby={id}>
    <div className="models-group-bar">
      <h2 className="models-group-heading" id={id}><span>{provider.name}</span><span className="models-group-count">{on.length} of {provider.models.length}</span></h2>
      <button type="button" className="button button-small button-secondary" disabled={busy} onClick={() => run(onRefresh)}><RefreshCw size={14} aria-hidden="true" /> Refresh</button>
    </div>
    <div className="hosted-card">
      <p className="hosted-note">Hosted models run on {provider.address ?? 'a gateway'}, not on this computer, so work data goes there. Tick the ones the Chat should offer.
        {provider.token_variable && <> The token comes from <code>{provider.token_variable}</code> where the backend starts{provider.token_set ? '.' : ', and it is not set.'}</>}</p>
      {provider.error && <p className="hosted-error" role="alert">{provider.error}</p>}
      {error && <p className="hosted-error" role="alert">{error}</p>}
      {provider.models.length > 8 && <input className="hosted-filter" type="search" placeholder="Filter models" aria-label={`Filter ${provider.name} models`} value={filter} onChange={(event) => setFilter(event.target.value)} />}
      <ul className="hosted-models">
        {shown.map((model) => <li key={model.id}><label><input type="checkbox" checked={model.enabled} disabled={busy} onChange={(event) => toggle(model.id, event.target.checked)} /> <span>{model.name}</span>{model.name !== model.id && <code>{model.id}</code>}</label></li>)}
        {provider.models.length > 0 && shown.length === 0 && <li className="hosted-none">No model matches.</li>}
        {provider.models.length === 0 && !provider.error && <li className="hosted-none">The provider lists no chat models.</li>}
      </ul>
    </div>
  </section>
}
