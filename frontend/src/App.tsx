import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Activity, AlertCircle, ArrowUpRight, ChevronDown,
  CircleHelp, Cpu, Database, LockKeyhole, MemoryStick,
  Monitor, RefreshCw, Server, Settings2, ShieldCheck, Sparkles, Wifi, WifiOff,
  X,
} from 'lucide-react'

type Memory = { total_bytes: number; available_bytes: number; used_bytes: number }
type Gpu = { id: string; name: string; memory: Memory | null; error: string | null }
type Host = {
  instance_id: string
  host: { hostname: string; os: string; label: string; role: string; scope: string }
  ram: Memory | null; ram_error: string | null; gpus: Gpu[]; gpu_error: string | null
  observed_at: string | null; sequence: number; age_seconds: number | null
  stale: boolean; stale_after_seconds: number; status: string; loading_enabled: boolean
  loading_reason: string
}
type Snapshot = { data: Host; arrivedAt: number }
type Model = { id: string; name: string; workload: string }
type Connection = 'idle' | 'connecting' | 'connected' | 'reconnecting' | 'error'

const URL_KEY = 'generation-station.server-url'

function readSavedUrl() {
  try { return localStorage.getItem(URL_KEY) ?? '' } catch { return '' }
}

function formatBytes(value?: number | null) {
  if (value == null || !Number.isFinite(value) || value < 0) return 'Unavailable'
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']
  if (value < 1024) return `${value} B`
  let amount = value
  let unit = 0
  while (amount >= 1024 && unit < units.length - 1) { amount /= 1024; unit += 1 }
  return `${amount.toFixed(amount < 10 ? 1 : 0).replace(/\.0$/, '')} ${units[unit]}`
}

function humanAge(seconds: number | null) {
  if (seconds == null || !Number.isFinite(seconds)) return 'No sample yet'
  if (seconds < 1) return 'Updated just now'
  return `Updated ${Math.floor(seconds)}s ago`
}

function normalizeBase(url: string) {
  const trimmed = url.trim()
  if (!trimmed) return ''
  const parsed = new URL(trimmed)
  if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error('Use an http:// or https:// server address.')
  if (parsed.username || parsed.password || parsed.search || parsed.hash || (parsed.pathname !== '/' && parsed.pathname !== '')) {
    throw new Error('Enter the server origin only, without a path, query, or credentials.')
  }
  return parsed.toString().replace(/\/$/, '')
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function validMemory(value: unknown): value is Memory {
  if (!value || typeof value !== 'object') return false
  const memory = value as Record<string, unknown>
  const { total_bytes: total, available_bytes: available, used_bytes: used } = memory
  return isFiniteNumber(total) && total > 0 && isFiniteNumber(available) && available >= 0 && available <= total
    && isFiniteNumber(used) && used >= 0 && used <= total
}

function isHost(value: unknown): value is Host {
  if (!value || typeof value !== 'object') return false
  const host = value as Record<string, unknown>
  if (typeof host.instance_id !== 'string' || !host.instance_id
      || !host.host || typeof host.host !== 'object' || !Array.isArray(host.gpus)
      || !(host.observed_at === null || typeof host.observed_at === 'string')
      || !isFiniteNumber(host.sequence) || !Number.isInteger(host.sequence) || host.sequence < 0
      || !['live', 'degraded', 'stale'].includes(String(host.status))
      || typeof host.loading_enabled !== 'boolean' || typeof host.loading_reason !== 'string'
      || typeof host.stale !== 'boolean' || !isFiniteNumber(host.stale_after_seconds) || host.stale_after_seconds <= 0
      || !(host.age_seconds === null || (isFiniteNumber(host.age_seconds) && host.age_seconds >= 0))) return false
  const identity = host.host as Record<string, unknown>
  if (!['hostname', 'os', 'label', 'role', 'scope'].every((key) => typeof identity[key] === 'string' && identity[key])) return false
  if (!(host.ram === null || validMemory(host.ram))) return false
  if (!(host.ram_error === null || typeof host.ram_error === 'string')) return false
  if (!(host.gpu_error === null || typeof host.gpu_error === 'string')) return false
  return host.gpus.every((entry: unknown) => {
    if (!entry || typeof entry !== 'object') return false
    const gpu = entry as Record<string, unknown>
    return typeof gpu.id === 'string' && typeof gpu.name === 'string' && !!gpu.name
      && (gpu.memory === null || validMemory(gpu.memory))
      && (gpu.error === null || typeof gpu.error === 'string')
  })
}

function isCatalog(value: unknown): value is { models: Model[] } {
  if (!value || typeof value !== 'object' || !Array.isArray((value as Record<string, unknown>).models)) return false
  return ((value as { models: unknown[] }).models).every((entry) => !!entry && typeof entry === 'object'
    && typeof (entry as Record<string, unknown>).id === 'string'
    && typeof (entry as Record<string, unknown>).name === 'string'
    && typeof (entry as Record<string, unknown>).workload === 'string')
}

function sseBoundary(value: string) { return /\r\n\r\n|\n\n|\r\r/.exec(value) }

function readWithWatchdog<T>(promise: Promise<T>, controller: AbortController, milliseconds: number): Promise<T> {
  return new Promise((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      controller.abort()
      reject(new Error('No telemetry arrived before the stream watchdog expired.'))
    }, milliseconds)
    promise.then((value) => { window.clearTimeout(timeout); resolve(value) }, (error) => { window.clearTimeout(timeout); reject(error) })
  })
}

function apiUrl(base: string, path: string) { return `${base}${path}` }

function parseSseBlock(block: string): { event: string; data: string } | null {
  let event = 'message'
  const data: string[] = []
  for (const line of block.split(/\r\n|\r|\n/)) {
    if (!line || line.startsWith(':')) continue
    const colon = line.indexOf(':')
    const field = colon === -1 ? line : line.slice(0, colon)
    let value = colon === -1 ? '' : line.slice(colon + 1)
    if (value.startsWith(' ')) value = value.slice(1)
    if (field === 'event') event = value
    if (field === 'data') data.push(value)
  }
  return data.length ? { event, data: data.join('\n') } : null
}

function useHostAge(snapshot: Snapshot | null) {
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

export default function App() {
  const [serverUrl, setServerUrl] = useState(readSavedUrl)
  const [accessToken, setAccessToken] = useState('')
  const [connection, setConnection] = useState<Connection>('idle')
  const [message, setMessage] = useState('Connect to a Generation Station host to see live resource usage.')
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [models, setModels] = useState<Model[] | null>(null)
  const [modelsError, setModelsError] = useState('')
  const [settingsOpen, setSettingsOpen] = useState(true)
  const [clock, setClock] = useState(() => new Date())
  const sessionRef = useRef<AbortController | null>(null)
  const generationRef = useRef(0)
  const instanceRef = useRef<string | null>(null)
  const { age, stale: sampleStale } = useHostAge(snapshot)
  const stale = sampleStale || (!!snapshot && connection !== 'connected')
  const connected = connection === 'connected' || connection === 'reconnecting'
  const host = snapshot?.data
  const degraded = connection === 'connected' && host?.status === 'degraded'

  const clearHost = useCallback(() => {
    sessionRef.current?.abort()
    sessionRef.current = null
    generationRef.current += 1
    setSnapshot(null)
    instanceRef.current = null
    setModels(null)
    setModelsError('')
    setConnection('idle')
  }, [])

  useEffect(() => {
    const id = window.setInterval(() => setClock(new Date()), 30_000)
    return () => window.clearInterval(id)
  }, [])
  useEffect(() => () => sessionRef.current?.abort(), [])

  const invalidateOnEdit = (field: 'url' | 'token', value: string) => {
    if (field === 'url') setServerUrl(value)
    else setAccessToken(value)
    if (connection !== 'idle' || snapshot) {
      clearHost()
      setMessage('Connection settings changed. Connect again to load data from this host.')
    }
  }

  const connect = async () => {
    clearHost()
    const currentGeneration = generationRef.current
    const controller = new AbortController()
    sessionRef.current = controller
    setConnection('connecting')
    setMessage('Checking the host and opening its telemetry stream…')
    let base: string
    try { base = normalizeBase(serverUrl) }
    catch (error) {
      setConnection('error')
      setMessage(error instanceof Error ? error.message : 'Invalid server address.')
      return
    }
    if (!accessToken.trim()) {
      setConnection('error')
      setMessage('Enter the access token configured on the host.')
      return
    }
    try { localStorage.setItem(URL_KEY, base) } catch { /* local storage is optional */ }
    const headers = { Authorization: `Bearer ${accessToken.trim()}` }
    const assertCurrent = () => {
      if (controller.signal.aborted || generationRef.current !== currentGeneration) throw new DOMException('Aborted', 'AbortError')
    }
    const fetchJson = async (path: string) => {
      const requestController = new AbortController()
      const abortRequest = () => requestController.abort()
      controller.signal.addEventListener('abort', abortRequest, { once: true })
      const timeout = window.setTimeout(abortRequest, 10_000)
      try {
        const response = await fetch(apiUrl(base, path), { headers, signal: requestController.signal, cache: 'no-store' })
        if (response.status === 401) throw new Error('The access token was rejected. Check the token and reconnect.')
        if (!response.ok) throw new Error(`Host request failed (${response.status}).`)
        try { return await response.json() }
        catch { throw new Error('This address did not return a valid Generation Station API response.') }
      }
      catch (error) {
        if (!controller.signal.aborted && requestController.signal.aborted) throw new Error('Host request timed out. Check the address and try again.')
        throw error
      } finally {
        window.clearTimeout(timeout)
        controller.signal.removeEventListener('abort', abortRequest)
      }
    }
    try {
      const initial = await fetchJson('/api/host') as unknown
      assertCurrent()
      if (!isHost(initial)) throw new Error('The host returned an invalid telemetry response.')
      instanceRef.current = initial.instance_id
      setSnapshot({ data: initial, arrivedAt: performance.now() })
      setMessage('Host found. Waiting for the next live telemetry sample…')
      void fetchJson('/api/models').then((result) => {
        if (controller.signal.aborted || generationRef.current !== currentGeneration) return
        if (!isCatalog(result)) throw new Error('The host returned an invalid model catalog.')
        setModels(result.models)
        setModelsError('')
      }).catch((error: unknown) => {
        if (controller.signal.aborted || generationRef.current !== currentGeneration) return
        setModelsError(error instanceof Error ? error.message : 'Model catalog is unavailable.')
      })
      let retry = 0
      while (!controller.signal.aborted && generationRef.current === currentGeneration) {
        const streamController = new AbortController()
        let streamReader: ReadableStreamDefaultReader<Uint8Array> | null = null
        const abortStream = () => streamController.abort()
        controller.signal.addEventListener('abort', abortStream, { once: true })
        try {
          const headerTimeout = window.setTimeout(() => streamController.abort(), 10_000)
          let response: Response
          try {
            response = await fetch(apiUrl(base, '/api/events'), {
              headers: { ...headers, Accept: 'text/event-stream' },
              signal: streamController.signal,
              cache: 'no-store',
            })
          } finally { window.clearTimeout(headerTimeout) }
          if (response.status === 401) throw new Error('The access token was rejected. Check the token and reconnect.')
          if (!response.ok || !response.body) throw new Error(`Telemetry stream failed (${response.status}).`)
          let lastValidTelemetryAt = performance.now()
          setMessage('Stream open. Waiting for a valid host measurement…')
          retry = 0
          const reader = response.body.getReader()
          streamReader = reader
          const decoder = new TextDecoder()
          let buffer = ''
          while (true) {
            if (performance.now() - lastValidTelemetryAt > Math.max(12_000, initial.stale_after_seconds * 1000 + 1_500)) {
              throw new Error('No fresh host sample arrived before the telemetry watchdog expired.')
            }
            const next = await readWithWatchdog(reader.read(), streamController, 12_000)
            if (next.done) throw new Error('Telemetry stream closed by the host.')
            buffer += decoder.decode(next.value, { stream: true })
            if (buffer.length > 1_000_000) throw new Error('Telemetry stream event exceeded the allowed size.')
            let boundary = sseBoundary(buffer)
            while (boundary) {
              const parsed = parseSseBlock(buffer.slice(0, boundary.index))
              buffer = buffer.slice(boundary.index! + boundary[0].length)
              if (parsed?.event === 'host') {
                let data: unknown
                try { data = JSON.parse(parsed.data) }
                catch { throw new Error('The host sent malformed telemetry JSON.') }
                if (!isHost(data)) throw new Error('The host sent an invalid telemetry sample.')
                assertCurrent()
                const changedInstance = instanceRef.current !== data.instance_id
                instanceRef.current = data.instance_id
                lastValidTelemetryAt = performance.now()
                setSnapshot({ data, arrivedAt: performance.now() })
                setConnection('connected')
                setMessage('Live telemetry is streaming from the host.')
                if (changedInstance) {
                  setModels(null)
                  void fetchJson('/api/models').then((result) => {
                    if (controller.signal.aborted || generationRef.current !== currentGeneration) return
                    if (!isCatalog(result)) throw new Error('The host returned an invalid model catalog.')
                    setModels(result.models)
                    setModelsError('')
                  }).catch(() => {
                    if (!controller.signal.aborted && generationRef.current === currentGeneration) setModelsError('Model catalog is unavailable for the new host service instance.')
                  })
                }
              }
              boundary = sseBoundary(buffer)
            }
          }
        } catch (error) {
          if (controller.signal.aborted || generationRef.current !== currentGeneration) break
          if (error instanceof Error && error.message.startsWith('The access token')) {
            setConnection('error')
            setMessage(error.message)
            break
          }
          retry += 1
          setConnection('reconnecting')
          setMessage(`Telemetry stream interrupted. Reconnecting (attempt ${retry})…`)
          await new Promise((resolve) => window.setTimeout(resolve, Math.min(1_000 * 2 ** Math.min(retry - 1, 4), 12_000)))
        } finally {
          if (streamReader) void streamReader.cancel().catch(() => undefined)
          streamController.abort()
          controller.signal.removeEventListener('abort', abortStream)
        }
      }
    } catch (error) {
      if (controller.signal.aborted || generationRef.current !== currentGeneration) return
      setConnection('error')
      setMessage(error instanceof Error ? error.message : 'Could not connect to the host.')
    }
  }

  const disconnect = () => {
    clearHost()
    setMessage('Disconnected. Host measurements and model data have been cleared.')
  }

  const connectionLabel = connection === 'connected' && stale ? 'Telemetry stale'
    : degraded ? 'Live · partial telemetry'
    : connection === 'connected' ? 'Live connection'
      : connection === 'reconnecting' ? 'Reconnecting'
        : connection === 'connecting' ? 'Connecting'
          : connection === 'error' ? 'Connection issue' : 'Not connected'
  const isLive = connection === 'connected' && !stale && !degraded

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand-lockup"><div className="brand-mark"><Sparkles size={21} strokeWidth={2.3} /></div><div><strong>generation<span>station</span></strong><small>LOCAL MODEL CONTROL</small></div></div>
      <nav aria-label="Main navigation">
        <div className="nav-label">WORKSPACE</div>
        <a className="nav-item active" href="#overview" aria-label="Overview"><Activity size={17} /><span>Overview</span><span className="nav-indicator" /></a>
        <a className="nav-item disabled-link" href="#models" aria-disabled="true" aria-label="Models, coming soon"><Cpu size={17} /><span>Models</span><span className="soon-tag">SOON</span></a>
      </nav>
      <div className="sidebar-footer"><div className="secure-badge"><ShieldCheck size={17} /><span>Host reported data</span></div><p>Your models run on the connected machine. Measurements describe the service process environment.</p><span className="version">PREVIEW · 0.1</span></div>
    </aside>

    <main id="overview" className="main-content">
      <header className="topbar"><div className="breadcrumb"><span>Workspace</span><span className="crumb-slash">/</span><strong>Overview</strong></div><div className="topbar-right"><span className="local-time">{clock.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span><span className="top-divider" /><span className="secure-top"><Server size={14} /> Host dashboard</span><span className="avatar" title="Generation Station">GS</span></div></header>

      <div className="page-wrap">
        <section className="page-heading"><div><div className="eyebrow"><span className="eyebrow-dot" /> YOUR LOCAL AI WORKSPACE</div><h1>System overview</h1><p>Monitor your host and manage the models running on it.</p></div><button className="button button-secondary refresh-button" onClick={connect} disabled={connection === 'connecting'}><RefreshCw size={15} className={connection === 'connecting' ? 'spin' : ''} /> Refresh connection</button></section>

        <section className={`connection-banner ${isLive ? 'banner-live' : degraded || connection === 'reconnecting' || (connection === 'connected' && stale) ? 'banner-warn' : 'banner-muted'}`} aria-live="polite">
          <div className="connection-symbol">{isLive ? <Wifi size={17} /> : degraded || connection === 'reconnecting' || (connection === 'connected' && stale) ? <AlertCircle size={17} /> : connection === 'error' ? <WifiOff size={17} /> : <Server size={17} />}</div>
          <div className="connection-copy"><strong>{connectionLabel}</strong><span>{message}</span></div>
          <div className="connection-actions">{connected ? <button className="text-button" onClick={disconnect}>Disconnect</button> : <span className="connection-scope"><LockKeyhole size={13} />{connection === 'connecting' ? 'Checking access' : connection === 'error' ? 'Check access' : 'Token required'}</span>}</div>
        </section>

        <section className="host-strip" aria-label="Connected host identity">
          <div className="host-icon"><Monitor size={19} /></div>
          <div className="host-main"><span className="micro-label">CONNECTED HOST</span><strong>{host?.host.label ?? 'No host selected'}</strong><small>{host ? `${host.host.hostname} · ${host.host.os}` : 'Choose a host address below to begin'}</small></div>
          {host && <><div className="host-divider" /><div className="host-attribute"><span className="micro-label">ROLE</span><strong className={`role-pill role-${host.host.role}`}>{host.host.role}</strong></div><div className="host-attribute scope-attribute"><span className="micro-label">MEASUREMENT SCOPE</span><strong>{host.host.scope}</strong></div><div className="host-updated"><span className={`status-dot ${isLive ? 'dot-live' : ''}`} />{humanAge(age)}</div></>}
        </section>

        <div className="section-heading"><div><h2>Resource usage</h2><p>Live measurements reported by the connected host</p></div><span className={`live-tag ${isLive ? 'live-tag-on' : ''}`}><span className="status-dot" />{degraded ? 'PARTIAL' : isLive ? 'LIVE' : stale && snapshot ? 'STALE' : 'WAITING'}</span></div>
        <section className="resource-grid" aria-label="Host resource usage">
          <ResourceCard title="System memory" icon={<MemoryStick size={17} />} iconClass="icon-violet" memory={host?.ram} age={age} isCurrent={!!snapshot && connection !== 'idle'} error={host?.ram_error ?? undefined} kind="RAM" stale={stale} />
          <GpuCard host={host} age={age} stale={stale} isCurrent={!!snapshot && connection !== 'idle'} />
        </section>

        <section id="models" className="models-section"><div className="section-heading model-heading"><div><h2>Installed models</h2><p>Choose what to load onto your host</p></div><button className="button button-primary" disabled title="Model loading is unavailable in this preview"><Cpu size={15} /> Add model</button></div>
          {modelsError ? <div className="inline-alert"><AlertCircle size={17} /><span>{modelsError}</span></div> : models && models.length > 0 ? <div className="model-placeholder">{models.map((model) => <div className="model-row" key={model.id}><div className="model-icon"><Cpu size={18} /></div><div><strong>{model.name ?? model.id}</strong><small>Runtime details are not available in this preview.</small></div><button className="button button-secondary" disabled title="Model loading is unavailable in this preview">Load</button></div>)}</div> : <div className="empty-models"><div className="empty-illustration"><Database size={22} /><span><Cpu size={15} /></span></div><div><strong>{models?.length === 0 ? 'No models installed yet' : 'Model catalog is waiting'}</strong><p>{models?.length === 0 ? 'Once a model is registered on this host, it will appear here with its runtime and memory profile.' : connection === 'idle' ? 'Connect to your host to see its registered model catalog.' : 'Loading model catalog from the connected host.'}</p></div><div className="empty-status"><span className="status-dot" />{models?.length === 0 ? 'EMPTY CATALOG' : 'HOST REQUIRED'}</div></div>}
          <div className="model-footnote"><CircleHelp size={14} /><span>Load and unload controls will be enabled when the host has verified capacity checks and a supported runtime.</span></div>
        </section>

        <section className="settings-section"><button className="settings-toggle" aria-expanded={settingsOpen} onClick={() => setSettingsOpen(!settingsOpen)}><span className="settings-title"><Settings2 size={17} /><span><strong>Connection settings</strong><small>Choose the Generation Station host to monitor</small></span></span><ChevronDown size={17} className={settingsOpen ? 'chevron-open' : ''} /></button>
          {settingsOpen && <div className="settings-content"><div className="settings-fields"><label className="field"><span>SERVER ADDRESS</span><div className="input-wrap"><Server size={16} /><input aria-label="Server address" type="url" autoComplete="url" placeholder="Same origin · or https://host:port" value={serverUrl} onChange={(event) => invalidateOnEdit('url', event.target.value)} /></div><small>Leave blank when the dashboard is served by the host. Remote addresses are saved on this device.</small></label><label className="field"><span>ACCESS TOKEN</span><div className="input-wrap"><LockKeyhole size={16} /><input aria-label="Access token" type="password" autoComplete="new-password" placeholder="Paste the host access token" value={accessToken} onChange={(event) => invalidateOnEdit('token', event.target.value)} /></div><small>Held in memory only. It is not saved in the URL or browser storage.</small></label></div><div className="settings-bottom"><div className="settings-note"><ShieldCheck size={16} /><span>Measurements describe the host service process environment.</span></div><div className="settings-buttons">{connection !== 'idle' && <button className="button button-secondary" onClick={disconnect}><X size={15} /> Disconnect</button>}<button className="button button-primary" onClick={connect} disabled={connection === 'connecting'}><Wifi size={15} /> {connection === 'connecting' ? 'Connecting…' : connection === 'reconnecting' ? 'Reconnect now' : 'Connect to host'} <ArrowUpRight size={14} /></button></div></div></div>}
        </section>
        <footer className="page-footer"><span>Generation Station <b>·</b> Host-first model management</span><span><span className="footer-dot" /> Measurements are reported by the connected service</span></footer>
      </div>
    </main>
  </div>
}

function ResourceCard({ title, icon, iconClass, memory, age, isCurrent, error, kind, stale }: {
  title: string; icon: React.ReactNode; iconClass: string; memory?: Memory | null
  age: number | null; isCurrent: boolean; error?: string; kind: string; stale: boolean
}) {
  const known = !!memory && isCurrent
  const used = known ? memory.used_bytes : null
  const total = known ? memory.total_bytes : null
  const available = known ? memory.available_bytes : null
  const percent = total && used != null ? Math.min(100, Math.max(0, used / total * 100)) : 0
  return <article className={`resource-card ${stale && known ? 'resource-stale' : ''}`}>
    <div className="resource-card-top"><div className="resource-title"><span className={`resource-icon ${iconClass}`}>{icon}</span><div><h3>{title}</h3><span>{kind === 'RAM' ? 'Physical RAM' : 'NVIDIA · NVML'}</span></div></div><span className="icon-help" title={`${title} measurements are supplied by host telemetry.`} aria-label={`${title} information`}><CircleHelp size={16} /></span></div>
    <div className="resource-value-row"><strong>{formatBytes(used)}</strong><span>of {formatBytes(total)}</span></div>
    <div className="progress-track" role="progressbar" aria-label={`${title} used`} aria-valuenow={known ? Math.round(percent) : undefined} aria-valuemin={0} aria-valuemax={100}><div className={`progress-fill ${iconClass}`} style={{ width: `${percent}%` }} /></div>
    <div className="resource-stats"><span><span className="stats-dot used-dot" />Used <b>{known ? `${percent.toFixed(0)}%` : '—'}</b></span><span><span className="stats-dot available-dot" />Available <b>{formatBytes(available)}</b></span></div>
    <div className="resource-card-bottom">{error ? <span className="resource-error"><AlertCircle size={13} />{error}</span> : known ? <span className={stale ? 'stale-copy' : 'sample-copy'}>{stale ? 'Last known measurement' : humanAge(age)}</span> : <span className="sample-copy">{isCurrent ? 'Waiting for a valid sample' : 'Connect to view measurements'}</span>}<span className="capacity-label">{stale && known ? 'STALE' : known ? 'MEASURED' : 'NO DATA'}</span></div>
  </article>
}

function GpuCard({ host, age, stale, isCurrent }: { host?: Host; age: number | null; stale: boolean; isCurrent: boolean }) {
  const gpus = host?.gpus ?? []
  const availableDevices = gpus.filter((gpu) => gpu.memory !== null).length
  if (!isCurrent || !host) return <ResourceCard title="Graphics memory" icon={<Cpu size={17} />} iconClass="icon-blue" memory={null} age={age} isCurrent={false} kind="VRAM" stale={stale} />
  if (gpus.length === 0) return <article className="resource-card"><div className="resource-card-top"><div className="resource-title"><span className="resource-icon icon-blue"><Cpu size={17} /></span><div><h3>Graphics memory</h3><span>GPU telemetry</span></div></div><span className="icon-help" title="VRAM is measured with NVIDIA NVML." aria-label="Graphics memory information"><CircleHelp size={16} /></span></div><div className="gpu-unavailable"><div className="gpu-empty-icon"><Cpu size={20} /></div><strong>GPU memory unavailable</strong><p>{host.gpu_error ?? 'No GPU devices have been reported by the host.'}</p></div><div className="resource-card-bottom"><span className="sample-copy">{humanAge(age)}</span><span className="capacity-label">NO DATA</span></div></article>
  const capacityState = stale ? 'STALE' : availableDevices === 0 ? 'NO DATA' : availableDevices < gpus.length || host.gpu_error ? 'PARTIAL' : 'MEASURED'
  return <article className={`resource-card gpu-card ${stale ? 'resource-stale' : ''}`}><div className="resource-card-top"><div className="resource-title"><span className="resource-icon icon-blue"><Cpu size={17} /></span><div><h3>Graphics memory</h3><span>{gpus.length} physical GPU{gpus.length === 1 ? '' : 's'}</span></div></div><span className="icon-help" title="VRAM is measured with NVIDIA NVML." aria-label="Graphics memory information"><CircleHelp size={16} /></span></div><div className="gpu-list">{gpus.map((gpu, i) => <div className="gpu-item" key={gpu.id}><div className="gpu-name"><strong>{gpu.name}</strong><span>DEVICE {String(i + 1).padStart(2, '0')}</span></div>{gpu.memory ? <><div className="resource-value-row gpu-value"><strong>{formatBytes(gpu.memory.used_bytes)}</strong><span>of {formatBytes(gpu.memory.total_bytes)}</span></div><div className="progress-track" role="progressbar" aria-label={`${gpu.name} used`} aria-valuenow={Math.round(gpu.memory.used_bytes / gpu.memory.total_bytes * 100)} aria-valuemin={0} aria-valuemax={100}><div className="progress-fill icon-blue" style={{ width: `${Math.min(100, gpu.memory.used_bytes / gpu.memory.total_bytes * 100)}%` }} /></div><div className="resource-stats"><span><span className="stats-dot used-dot" />Used <b>{(gpu.memory.used_bytes / gpu.memory.total_bytes * 100).toFixed(0)}%</b></span><span><span className="stats-dot available-dot" />Available <b>{formatBytes(gpu.memory.available_bytes)}</b></span></div></> : <div className="gpu-error"><AlertCircle size={14} />{gpu.error ?? host.gpu_error ?? 'VRAM accounting unavailable for this device.'}</div>}</div>)}</div><div className="resource-card-bottom"><span className={stale ? 'stale-copy' : 'sample-copy'}>{stale ? 'Last known measurement' : humanAge(age)}{host.gpu_error ? ` · ${host.gpu_error}` : ''}</span><span className="capacity-label">{capacityState}</span></div></article>
}
