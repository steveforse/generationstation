import { useState } from 'react'
import { LockKeyhole, Pencil, Plus, Server, ShieldCheck, Trash2, Wifi, X } from 'lucide-react'
import { normalizeBase } from '../api'
import { ConnectionBanner, hostName } from '../components/HostBits'
import { newHostId, type SavedHost } from '../hosts'
import { type HostStore, useSession } from '../store'

export function ConnectionsPage({ store, hosts }: { store: HostStore; hosts: SavedHost[] }) {
  const [adding, setAdding] = useState(hosts.length === 0)
  return <>
    <section className="page-heading"><div><div className="eyebrow"><span className="eyebrow-dot" /> Hosts</div><h1>Connections</h1><p>The Generation Station hosts this browser connects to. Addresses and access tokens are saved on this device.</p></div>
      {!adding && <button className="button button-primary" onClick={() => setAdding(true)}><Plus size={16} /> Add host</button>}</section>
    {adding && <HostForm title="Add a host" onCancel={hosts.length ? () => setAdding(false) : undefined} onSave={(host) => {
      store.save(host); setAdding(false); void store.session(host.id)?.connect()
    }} />}
    <div className="connection-list">{hosts.map((host) => <HostRow key={host.id} store={store} host={host} />)}</div>
    <div className="settings-note"><ShieldCheck size={18} /><span>Tokens are kept in this browser's storage so you do not have to paste them again. Use Forget on a shared computer.</span></div>
  </>
}

function HostRow({ store, host }: { store: HostStore; host: SavedHost }) {
  const session = store.session(host.id)
  const state = useSession(session)
  const [editing, setEditing] = useState(false)
  const [confirmForget, setConfirmForget] = useState(false)
  const active = state.connection !== 'idle' && state.connection !== 'error'
  if (!host.token) return <HostForm title={`Connect to ${hostName(host, state)}`} initial={host} onSave={(next) => {
    store.save(next); void store.session(next.id)?.connect()
  }} />
  if (editing) return <HostForm title={`Edit ${hostName(host, state)}`} initial={host} onCancel={() => setEditing(false)} onSave={(next) => {
    store.save(next); setEditing(false); void store.session(next.id)?.connect()
  }} />
  return <article className="profile-card connection-card" aria-label={`Host ${hostName(host, state)}`}>
    <div className="profile-card-main"><div className="model-icon"><Server size={20} /></div><div className="profile-card-title"><div><strong>{hostName(host, state)}</strong><span className="profile-id">{host.url || 'Same address as this page'} · {host.token ? 'token saved' : 'no token'}</span></div></div></div>
    <ConnectionBanner state={state} />
    <div className="profile-card-footer"><span className="worker-caption">{state.snapshot ? `${state.snapshot.data.host.hostname} · ${state.snapshot.data.host.os}` : ''}</span><div className="profile-actions">
      {active ? <button className="button button-secondary" onClick={() => session?.disconnect()}><X size={16} /> Disconnect</button>
        : <button className="button button-primary" onClick={() => void session?.connect()} disabled={!host.token}><Wifi size={16} /> Connect</button>}
      <button className="button button-secondary" onClick={() => setEditing(true)}><Pencil size={16} /> Edit</button>
      {confirmForget
        ? <><button className="button button-secondary" onClick={() => store.remove(host.id)}><Trash2 size={16} /> Forget it</button><button className="text-button" onClick={() => setConfirmForget(false)}>Keep</button></>
        : <button className="button button-secondary" onClick={() => setConfirmForget(true)}><Trash2 size={16} /> Forget</button>}
    </div></div>
  </article>
}

function HostForm({ title, initial, onSave, onCancel }: { title: string; initial?: SavedHost; onSave: (host: SavedHost) => void; onCancel?: () => void }) {
  const [label, setLabel] = useState(initial?.label ?? '')
  const [url, setUrl] = useState(initial?.url ?? '')
  const [token, setToken] = useState(initial?.token ?? '')
  const [error, setError] = useState('')
  const submit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    let base: string
    try { base = normalizeBase(url) } catch (reason) { setError(reason instanceof Error ? reason.message : 'Invalid address.'); return }
    if (!token.trim()) { setError('Enter the access token configured on the host.'); return }
    onSave({ id: initial?.id ?? newHostId(), label: label.trim(), url: base, token: token.trim() })
  }
  return <form className="profile-form host-form" onSubmit={submit} aria-label={title}>
    <div className="profile-form-heading"><div><strong>{title}</strong><small>Leave the address blank for the host that serves this page.</small></div></div>
    <div className="settings-fields">
      <label className="field"><span>Name</span><div className="input-wrap"><Server size={18} /><input aria-label="Host name" placeholder="Desktop" value={label} onChange={(event) => setLabel(event.target.value)} /></div><small>Optional. Shown in the sidebar.</small></label>
      <label className="field"><span>Server address</span><div className="input-wrap"><Server size={18} /><input aria-label="Server address" type="url" autoComplete="url" placeholder="Same origin · or http://host:8000" value={url} onChange={(event) => setUrl(event.target.value)} /></div><small>For example http://100.109.129.35:8000 over Tailscale.</small></label>
      <label className="field"><span>Access token</span><div className="input-wrap"><LockKeyhole size={18} /><input aria-label="Access token" type="password" autoComplete="new-password" placeholder="Paste the host access token" value={token} onChange={(event) => setToken(event.target.value)} /></div><small>GS_API_TOKEN from the host's .env. Saved on this device.</small></label>
    </div>
    {error && <div className="form-error" role="alert">{error}</div>}
    <div className="profile-form-actions"><span /><div>{onCancel && <button className="button button-secondary" type="button" onClick={onCancel}>Cancel</button>}<button className="button button-primary" type="submit"><Wifi size={16} /> Save and connect</button></div></div>
  </form>
}
