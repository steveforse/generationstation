import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Activity, AlertCircle, ArrowUpRight, ChevronDown,
  CircleHelp, Cpu, Database, LockKeyhole, MemoryStick,
  Monitor, Plus, RefreshCw, Server, Settings2, ShieldCheck, Sparkles, Wifi, WifiOff,
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
type Model = { id: string; name: string; workload: string; state: string; loading_enabled: boolean; loading_reason?: string | null }
type ModelProfile = { id: string; model_id: string; name: string; workload: string; ram_peak_bytes: number; gpu_vram_bytes_by_id: Record<string, number>; mode: 'simulation' }
type Operation = { id: string; model_id: string; action: string; status: string; simulation: boolean; worker_type: string; created_at?: string; updated_at?: string; error_code?: string | null; error_message?: string | null; refusal?: Refusal | null; launch?: Launch | null }
type SettingValue = string | number | boolean | null
type Launch = { preset: string; settings: Record<string, SettingValue>; gpus: number[] }
type RuntimeSetting = { key: string; label: string; kind: 'int' | 'bool' | 'choice' | 'optional_int'; minimum: number | null; maximum: number | null; unit: string | null; help: string; default: SettingValue; options: string[] | null }
type RuntimePreset = { name: string; gpus: number[]; allowed_gpus: { index: number; name: string }[]; settings: RuntimeSetting[]; estimate: { ram_gib: number; gpu_min_free_gib: Record<string, number> } }
type InputField = { key: string; label: string; kind: 'text' | 'textarea' | 'int' | 'choice' | 'seed'; required: boolean; default: string | number | null; minimum: number | null; maximum: number | null; max_length: number | null; options: string[]; placeholder: string | null; help: string; advanced: boolean }
type Generation = { output_kind: 'audio' | 'image' | 'video'; inputs: InputField[] }
type Runtime = { id: string; kind: string; name: string; workload: string; port: number; default_preset: string; presets: Record<string, RuntimePreset>; last_launch: Launch | null; max_gpus?: number | null; generation?: Generation | null }
type JobOutput = { name: string; mime: string; bytes: number }
type Job = { id: string; model_id: string; inputs: Record<string, string | number>; status: 'queued' | 'running' | 'done' | 'failed'; progress: string | null; outputs: JobOutput[]; error_message: string | null; created_at: string; finished_at: string | null }
type RefusalResource = { resource: string; required_bytes: number; available_bytes: number; headroom_bytes?: number }
type Refusal = { code: string; message: string; resources?: RefusalResource[] }
type ApiErrorBody = { detail?: string | Refusal; [key: string]: unknown }
class ApiError extends Error {
  constructor(readonly status: number, readonly body: ApiErrorBody) { super(typeof body.detail === 'string' ? body.detail : body.detail?.message ?? `Host request failed (${status}).`) }
}
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
    && typeof (entry as Record<string, unknown>).workload === 'string'
    && typeof (entry as Record<string, unknown>).state === 'string'
    && typeof (entry as Record<string, unknown>).loading_enabled === 'boolean')
}

function isProfiles(value: unknown): value is { profiles: ModelProfile[] } {
  if (!value || typeof value !== 'object' || !Array.isArray((value as Record<string, unknown>).profiles)) return false
  return ((value as { profiles: unknown[] }).profiles).every((entry) => {
    if (!entry || typeof entry !== 'object') return false
    const profile = entry as Record<string, unknown>
    if (!(typeof profile.model_id === 'string' || typeof profile.id === 'string') || typeof profile.name !== 'string' || typeof profile.workload !== 'string'
        || !isFiniteNumber(profile.ram_peak_bytes) || profile.ram_peak_bytes <= 0 || profile.mode !== 'simulation'
        || !profile.gpu_vram_bytes_by_id || typeof profile.gpu_vram_bytes_by_id !== 'object' || Array.isArray(profile.gpu_vram_bytes_by_id)) return false
    return Object.values(profile.gpu_vram_bytes_by_id as Record<string, unknown>).every((bytes) => isFiniteNumber(bytes) && bytes > 0)
  })
}

function isOperation(value: unknown): value is Operation {
  if (!value || typeof value !== 'object') return false
  const operation = value as Record<string, unknown>
  return typeof operation.id === 'string' && typeof operation.model_id === 'string'
    && typeof operation.action === 'string' && typeof operation.status === 'string'
    && ((operation.simulation === true && operation.worker_type === 'fake')
      || (operation.simulation === false && operation.worker_type === 'runtime'))
}

function isJob(value: unknown): value is Job {
  if (!value || typeof value !== 'object') return false
  const job = value as Record<string, unknown>
  return typeof job.id === 'string' && typeof job.model_id === 'string' && typeof job.status === 'string'
    && Array.isArray(job.outputs) && !!job.inputs && typeof job.inputs === 'object'
}

function isJobs(value: unknown): value is { jobs: Job[] } {
  return !!value && typeof value === 'object' && Array.isArray((value as Record<string, unknown>).jobs)
    && ((value as { jobs: unknown[] }).jobs).every(isJob)
}

function isRuntimes(value: unknown): value is { runtimes: Runtime[] } {
  if (!value || typeof value !== 'object' || !Array.isArray((value as Record<string, unknown>).runtimes)) return false
  return ((value as { runtimes: unknown[] }).runtimes).every((entry) => {
    if (!entry || typeof entry !== 'object') return false
    const runtime = entry as Record<string, unknown>
    return typeof runtime.id === 'string' && typeof runtime.name === 'string' && typeof runtime.default_preset === 'string'
      && !!runtime.presets && typeof runtime.presets === 'object'
  })
}

function isOperations(value: unknown): value is { operations: Operation[] } {
  return !!value && typeof value === 'object' && Array.isArray((value as Record<string, unknown>).operations)
    && ((value as { operations: unknown[] }).operations).every(isOperation)
}

function isRefusal(value: unknown): value is Refusal {
  if (!value || typeof value !== 'object') return false
  const refusal = value as Record<string, unknown>
  return typeof refusal.code === 'string' && typeof refusal.message === 'string'
    && (refusal.resources === undefined || (Array.isArray(refusal.resources) && refusal.resources.every((item) => {
      if (!item || typeof item !== 'object') return false
      const resource = item as Record<string, unknown>
      return typeof resource.resource === 'string' && isFiniteNumber(resource.required_bytes)
        && isFiniteNumber(resource.available_bytes)
        && (resource.headroom_bytes === undefined || isFiniteNumber(resource.headroom_bytes))
    })))
}

function isTerminalOperation(status: string) {
  return ['simulation_ready', 'ready', 'unloaded', 'refused', 'failed', 'cleanup_failed'].includes(status)
}

function idempotencyKey() {
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  return Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('')
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

async function requestApi(base: string, token: string, path: string, init: RequestInit = {}, parentSignal?: AbortSignal) {
  const controller = new AbortController()
  const abort = () => controller.abort()
  parentSignal?.addEventListener('abort', abort, { once: true })
  const timer = window.setTimeout(abort, 10_000)
  try {
    const response = await fetch(apiUrl(base, path), {
      ...init,
      headers: { Authorization: `Bearer ${token}`, ...(init.body ? { 'Content-Type': 'application/json' } : {}), ...init.headers },
      signal: controller.signal,
      cache: 'no-store',
    })
    let body: unknown = null
    if (response.status !== 204) {
      try { body = await response.json() }
      catch { throw new Error('The host returned an invalid JSON response.') }
    }
    if (!response.ok) throw new ApiError(response.status, body && typeof body === 'object' ? body as ApiErrorBody : {})
    return body
  } catch (error) {
    if (parentSignal?.aborted) throw new DOMException('Aborted', 'AbortError')
    if (controller.signal.aborted) throw new Error('Host request timed out. Check the connection and try again.')
    throw error
  } finally {
    window.clearTimeout(timer)
    parentSignal?.removeEventListener('abort', abort)
  }
}

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
  const [profiles, setProfiles] = useState<ModelProfile[] | null>(null)
  const [runtimes, setRuntimes] = useState<Runtime[] | null>(null)
  const [runtimeMessages, setRuntimeMessages] = useState<Record<string, string>>({})
  const [jobs, setJobs] = useState<Job[]>([])
  const [jobErrors, setJobErrors] = useState<Record<string, string>>({})
  const [catalogError, setCatalogError] = useState('')
  const [operations, setOperations] = useState<Operation[]>([])
  const [pendingModelId, setPendingModelId] = useState<string | null>(null)
  const [refusals, setRefusals] = useState<Record<string, Refusal>>({})
  const [actionError, setActionError] = useState('')
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
    setProfiles(null)
    setRuntimes(null)
    setRuntimeMessages({})
    setJobs([])
    setJobErrors({})
    setCatalogError('')
    setOperations([])
    setRefusals({})
    setActionError('')
    setPendingModelId(null)
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
    const refreshCatalog = async () => {
      try {
        const [modelsResult, profilesResult] = await Promise.all([fetchJson('/api/models'), fetchJson('/api/profiles')])
        assertCurrent()
        if (!isCatalog(modelsResult) || !isProfiles(profilesResult)) throw new Error('The host returned an invalid model profile catalog.')
        setModels(modelsResult.models)
        setProfiles(profilesResult.profiles.map((profile) => ({ ...profile, id: profile.id || profile.model_id, model_id: profile.model_id || profile.id })))
        void fetchJson('/api/runtimes').then((result) => {
          if (controller.signal.aborted || generationRef.current !== currentGeneration) return
          setRuntimes(isRuntimes(result) ? result.runtimes : [])
        }).catch(() => setRuntimes([]))
        void fetchJson('/api/jobs?limit=20').then((result) => {
          if (controller.signal.aborted || generationRef.current !== currentGeneration) return
          if (isJobs(result)) setJobs(result.jobs)
        }).catch(() => undefined)
        void fetchJson('/api/operations?limit=100').then((result) => {
          if (controller.signal.aborted || generationRef.current !== currentGeneration) return
          if (isOperations(result)) setOperations(result.operations.slice(0, 8))
        }).catch(() => undefined)
        setCatalogError('')
      } catch (error) {
        if (controller.signal.aborted || generationRef.current !== currentGeneration) return
        setModels(null)
        setProfiles(null)
        setCatalogError(error instanceof Error ? error.message : 'Model profile catalog is unavailable.')
      }
    }
    try {
      const initial = await fetchJson('/api/host') as unknown
      assertCurrent()
      if (!isHost(initial)) throw new Error('The host returned an invalid telemetry response.')
      instanceRef.current = initial.instance_id
      setSnapshot({ data: initial, arrivedAt: performance.now() })
      setMessage('Host found. Waiting for the next live telemetry sample…')
      void refreshCatalog()
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
                  setProfiles(null)
                  void refreshCatalog()
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

  const refreshCatalogNow = async (base: string, token: string, signal: AbortSignal, generation: number) => {
    const [modelsResult, profilesResult] = await Promise.all([
      requestApi(base, token, '/api/models', {}, signal),
      requestApi(base, token, '/api/profiles', {}, signal),
    ])
    if (signal.aborted || generationRef.current !== generation) return
    if (!isCatalog(modelsResult) || !isProfiles(profilesResult)) throw new Error('The host returned an invalid model profile catalog.')
    setModels(modelsResult.models)
    setProfiles(profilesResult.profiles.map((profile) => ({ ...profile, id: profile.id || profile.model_id, model_id: profile.model_id || profile.id })))
    const [operationsResult, runtimesResult, jobsResult] = await Promise.all([
      requestApi(base, token, '/api/operations?limit=100', {}, signal).catch(() => null),
      requestApi(base, token, '/api/runtimes', {}, signal).catch(() => null),
      requestApi(base, token, '/api/jobs?limit=20', {}, signal).catch(() => null),
    ])
    if (signal.aborted || generationRef.current !== generation) return
    if (isOperations(operationsResult)) setOperations(operationsResult.operations.slice(0, 8))
    if (isRuntimes(runtimesResult)) setRuntimes(runtimesResult.runtimes)
    if (isJobs(jobsResult)) setJobs(jobsResult.jobs)
    setCatalogError('')
  }

  // While a runtime is starting or stopping (it can take many minutes), keep its state current.
  const runtimeBusy = !!models?.some((model) => runtimes?.some((runtime) => runtime.id === model.id)
    && ['loading', 'unloading'].includes(model.state))
  useEffect(() => {
    if (!runtimeBusy || connection !== 'connected' || !sessionRef.current) return
    const generation = generationRef.current
    const signal = sessionRef.current.signal
    let base: string
    try { base = normalizeBase(serverUrl) } catch { return }
    const token = accessToken.trim()
    const id = window.setInterval(() => { void refreshCatalogNow(base, token, signal, generation).catch(() => undefined) }, 3_000)
    return () => window.clearInterval(id)
    // refreshCatalogNow is recreated each render; the interval only needs these inputs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runtimeBusy, connection, serverUrl, accessToken])

  const runJob = async (runtime: Runtime, inputs: Record<string, string | number | null>) => {
    if (!host || connection !== 'connected' || !sessionRef.current) return false
    const generation = generationRef.current
    const signal = sessionRef.current.signal
    const base = normalizeBase(serverUrl)
    const token = accessToken.trim()
    setJobErrors((previous) => ({ ...previous, [runtime.id]: '' }))
    try {
      const accepted = await requestApi(base, token, `/api/models/${encodeURIComponent(runtime.id)}/jobs`, { method: 'POST', body: JSON.stringify({ inputs }) }, signal)
      if (!isJob(accepted)) throw new Error('The host returned an invalid job.')
      let job: Job = accepted
      const save = (item: Job) => setJobs((items) => [item, ...items.filter((other) => other.id !== item.id)].slice(0, 20))
      save(job)
      void (async () => {
        while (job.status === 'queued' || job.status === 'running') {
          await new Promise((resolve) => window.setTimeout(resolve, 3_000))
          if (signal.aborted || generationRef.current !== generation) return
          const next = await requestApi(base, token, `/api/jobs/${encodeURIComponent(job.id)}`, {}, signal).catch(() => null)
          if (isJob(next)) { job = next; save(job) }
        }
      })()
      return true
    } catch (error) {
      if (signal.aborted || generationRef.current !== generation) return false
      setJobErrors((previous) => ({ ...previous, [runtime.id]: error instanceof Error ? error.message : 'The job could not be started.' }))
      return false
    }
  }

  // Files need the access token, so fetch them and hand the browser a local object URL.
  const fileUrl = async (job: Job, output: JobOutput) => {
    if (!sessionRef.current) throw new Error('Not connected.')
    const response = await fetch(apiUrl(normalizeBase(serverUrl), `/api/jobs/${encodeURIComponent(job.id)}/files/${encodeURIComponent(output.name)}`), {
      headers: { Authorization: `Bearer ${accessToken.trim()}` }, signal: sessionRef.current.signal, cache: 'no-store',
    })
    if (!response.ok) throw new Error(`The file could not be loaded (${response.status}).`)
    return URL.createObjectURL(await response.blob())
  }

  const runRuntime = async (runtime: Runtime, action: 'start' | 'stop', launch?: Launch) => {
    if (!host || connection !== 'connected' || stale || !sessionRef.current) return
    const generation = generationRef.current
    const signal = sessionRef.current.signal
    const base = normalizeBase(serverUrl)
    const token = accessToken.trim()
    const say = (text: string) => setRuntimeMessages((previous) => ({ ...previous, [runtime.id]: text }))
    setPendingModelId(runtime.id)
    setActionError('')
    setRefusals((previous) => { const next = { ...previous }; delete next[runtime.id]; return next })
    say(action === 'start' ? 'Checking capacity…' : 'Stopping…')
    try {
      const path = action === 'start' ? `/api/runtimes/${encodeURIComponent(runtime.id)}/start` : `/api/models/${encodeURIComponent(runtime.id)}/unload`
      const accepted = await requestApi(base, token, path, {
        method: 'POST', headers: { 'Idempotency-Key': idempotencyKey() },
        ...(action === 'start' && launch ? { body: JSON.stringify({ preset: launch.preset, settings: launch.settings, gpus: launch.gpus }) } : {}),
      }, signal)
      if (!isOperation(accepted)) throw new Error('The host returned an invalid operation.')
      let latest: Operation = accepted
      const saveOperation = (operation: Operation) => setOperations((items) => [operation, ...items.filter((item) => item.id !== operation.id)].slice(0, 8))
      saveOperation(latest)
      await refreshCatalogNow(base, token, signal, generation)
      const started = performance.now()
      while (!isTerminalOperation(latest.status)) {
        const minutes = Math.floor((performance.now() - started) / 60_000)
        say(action === 'start' ? `Loading ${runtime.presets[launch?.preset ?? runtime.default_preset]?.name ?? runtime.name}… ${minutes ? `${minutes} min so far. ` : ''}Large models can take 5–20 minutes.` : 'Stopping…')
        await new Promise((resolve) => window.setTimeout(resolve, 2_000))
        if (signal.aborted || generationRef.current !== generation) return
        const result = await requestApi(base, token, `/api/operations/${encodeURIComponent(latest.id)}`, {}, signal)
        if (!isOperation(result)) throw new Error('The host returned an invalid operation status.')
        latest = result
        saveOperation(latest)
      }
      say(latest.status === 'ready' ? 'Ready.' : latest.status === 'unloaded' ? 'Stopped.'
        : `${latest.status.replaceAll('_', ' ')}${latest.error_message ? `: ${latest.error_message}` : ''}`)
      await refreshCatalogNow(base, token, signal, generation)
    } catch (error) {
      if (signal.aborted || generationRef.current !== generation) return
      if (error instanceof ApiError && error.status === 401) {
        clearHost()
        setConnection('error')
        setMessage('The access token was rejected. Check the token and reconnect.')
        return
      }
      const detail = error instanceof ApiError ? error.body.detail : undefined
      if (error instanceof ApiError && error.status === 409 && isRefusal(detail) && detail.resources?.length) {
        setRefusals((previous) => ({ ...previous, [runtime.id]: detail }))
        say('')
      } else say(error instanceof Error ? error.message : 'The host could not complete this operation.')
    } finally {
      if (generationRef.current === generation) setPendingModelId(null)
    }
  }

  const registerProfile = async (profile: { id: string; name: string; workload: string; ram_peak_bytes: number; gpu_vram_bytes_by_id: Record<string, number>; mode: 'simulation' }) => {
    if (!host || connection !== 'connected' || stale || !sessionRef.current) return false
    const generation = generationRef.current
    const signal = sessionRef.current.signal
    const base = normalizeBase(serverUrl)
    const token = accessToken.trim()
    setCatalogError('')
    setActionError('')
    try {
      await requestApi(base, token, '/api/profiles', { method: 'POST', body: JSON.stringify(profile) }, signal)
      await refreshCatalogNow(base, token, signal, generation)
      return true
    } catch (error) {
      if (signal.aborted || generationRef.current !== generation) return false
      if (error instanceof ApiError && error.status === 401) {
        clearHost()
        setConnection('error')
        setMessage('The access token was rejected. Check the token and reconnect.')
        return false
      }
      setActionError(error instanceof Error ? error.message : 'Could not register the simulation profile.')
      return false
    }
  }

  const runLifecycle = async (model: Model, action: 'load' | 'unload', profile: ModelProfile) => {
    if (!host || connection !== 'connected' || stale || !sessionRef.current) return
    const generation = generationRef.current
    const signal = sessionRef.current.signal
    const base = normalizeBase(serverUrl)
    const token = accessToken.trim()
    setPendingModelId(model.id)
    setActionError('')
    setRefusals((previous) => { const next = { ...previous }; delete next[model.id]; return next })
    try {
      const accepted = await requestApi(base, token, `/api/models/${encodeURIComponent(model.id)}/${action}`, {
        method: 'POST',
        headers: { 'Idempotency-Key': idempotencyKey() },
        ...(action === 'load' ? { body: JSON.stringify({ profile_id: profile.id }) } : {}),
      }, signal) as Record<string, unknown>
      const operationId = typeof accepted.operation_id === 'string' ? accepted.operation_id : accepted.id
      if (typeof operationId !== 'string') throw new Error('The host did not return an operation ID.')
      let latest: Operation = {
        id: operationId, model_id: model.id, action, status: String(accepted.status ?? (action === 'load' ? 'loading' : 'unloading')),
        simulation: accepted.simulation === true, worker_type: String(accepted.worker_type ?? 'fake'),
      }
      if (!isOperation(latest)) throw new Error('The host returned a non-simulation lifecycle operation.')
      const saveOperation = (operation: Operation) => setOperations((items) => [operation, ...items.filter((item) => item.id !== operation.id)].slice(0, 8))
      saveOperation(latest)
      for (let attempt = 0; attempt < 60 && !isTerminalOperation(latest.status); attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 350))
        if (signal.aborted || generationRef.current !== generation) return
        const result = await requestApi(base, token, `/api/operations/${encodeURIComponent(latest.id)}`, {}, signal)
        if (!isOperation(result)) throw new Error('The host returned an invalid operation status.')
        latest = result
        saveOperation(latest)
      }
      if (!isTerminalOperation(latest.status)) setActionError('The worker operation is still in progress. Its latest state is shown below.')
      await refreshCatalogNow(base, token, signal, generation)
    } catch (error) {
      if (signal.aborted || generationRef.current !== generation) return
      if (error instanceof ApiError && error.status === 409) {
        const value = isRefusal(error.body.detail) ? error.body.detail : isRefusal(error.body) ? error.body as Refusal : null
        if (value) setRefusals((previous) => ({ ...previous, [model.id]: value }))
        else setActionError(error.message)
      } else if (error instanceof ApiError && error.status === 401) {
        clearHost()
        setConnection('error')
        setMessage('The access token was rejected. Check the token and reconnect.')
      } else setActionError(error instanceof Error ? error.message : 'The host could not complete this operation.')
    } finally {
      if (generationRef.current === generation) setPendingModelId(null)
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
        <a className="nav-item" href="#models" aria-label="Model profiles"><Cpu size={17} /><span>Profiles</span></a>
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

        <RuntimePanel runtimes={runtimes} models={models} host={host} fresh={connection === 'connected' && !stale} pendingModelId={pendingModelId} refusals={refusals} messages={runtimeMessages} onRun={runRuntime} jobs={jobs} jobErrors={jobErrors} onGenerate={runJob} fileUrl={fileUrl} />

        <ProfileManager key={`${serverUrl}|${host?.instance_id ?? 'disconnected'}`} profiles={profiles} models={models} host={host} fresh={connection === 'connected' && !stale} catalogError={catalogError} actionError={actionError} operations={operations} pendingModelId={pendingModelId} refusals={refusals} onRegister={registerProfile} onLifecycle={runLifecycle} />

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

function ProfileManager({ profiles, models, host, fresh, catalogError, actionError, operations, pendingModelId, refusals, onRegister, onLifecycle }: {
  profiles: ModelProfile[] | null; models: Model[] | null; host?: Host; fresh: boolean; catalogError: string; actionError: string
  operations: Operation[]; pendingModelId: string | null; refusals: Record<string, Refusal>
  onRegister: (profile: { id: string; name: string; workload: string; ram_peak_bytes: number; gpu_vram_bytes_by_id: Record<string, number>; mode: 'simulation' }) => Promise<boolean>
  onLifecycle: (model: Model, action: 'load' | 'unload', profile: ModelProfile) => Promise<void>
}) {
  const [formOpen, setFormOpen] = useState(false)
  const [modelId, setModelId] = useState('')
  const [name, setName] = useState('')
  const [workload, setWorkload] = useState('')
  const [ramGib, setRamGib] = useState('')
  const [gpuNeeds, setGpuNeeds] = useState<Array<{ deviceId: string; gib: string }>>([])
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState('')
  const gpus = host?.gpus ?? []
  const canRegister = fresh && !!host
  const gigabyte = 1024 ** 3
  const ramBytes = Number(ramGib) * gigabyte
  const gpuMap: Record<string, number> = {}
  let validGpuRows = true
  for (const requirement of gpuNeeds) {
    const bytes = Number(requirement.gib) * gigabyte
    if (!requirement.deviceId || !Number.isSafeInteger(Math.round(bytes)) || bytes <= 0 || gpuMap[requirement.deviceId]) validGpuRows = false
    if (requirement.deviceId && Number.isSafeInteger(Math.round(bytes)) && bytes > 0) gpuMap[requirement.deviceId] = Math.round(bytes)
  }
  const formValid = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(modelId.trim())
    && name.trim().length > 0 && name.trim().length <= 200 && workload.trim().length > 0 && workload.trim().length <= 40
    && Number.isSafeInteger(Math.round(ramBytes)) && ramBytes > 0 && validGpuRows
    && gpuNeeds.every((need) => need.deviceId && gpus.some((gpu) => gpu.id === need.deviceId))

  const resetForm = () => { setModelId(''); setName(''); setWorkload(''); setRamGib(''); setGpuNeeds([]); setFormError('') }
  const addGpuNeed = () => {
    const selected = new Set(gpuNeeds.map((need) => need.deviceId))
    const first = gpus.find((gpu) => !selected.has(gpu.id))
    if (first) setGpuNeeds((items) => [...items, { deviceId: first.id, gib: '' }])
  }
  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setFormError('')
    if (!canRegister) { setFormError('Connect to a host with a fresh telemetry sample before registering a profile.'); return }
    if (!formValid) { setFormError('Enter a valid profile ID, model name, workload, and positive memory requirements for reported devices.'); return }
    setSubmitting(true)
    const ok = await onRegister({ id: modelId.trim(), name: name.trim(), workload: workload.trim(), ram_peak_bytes: Math.round(ramBytes), gpu_vram_bytes_by_id: gpuMap, mode: 'simulation' })
    setSubmitting(false)
    if (ok) { resetForm(); setFormOpen(false) }
  }

  const operatingHost = fresh && host?.loading_enabled === true && host.host.role === 'desktop' && host.host.scope === 'host' && host.ram !== null
  const stateLabel = (state: string) => ({ unloaded: 'Unloaded', checking: 'Checking capacity', loading: 'Loading simulation worker', simulation_ready: 'Simulation ready', unloading: 'Unloading simulation worker', error: 'Worker error', unavailable: 'Unavailable' }[state] ?? state.replaceAll('_', ' '))

  return <section id="models" className="models-section" aria-labelledby="profile-heading">
    <div className="section-heading model-heading"><div><h2 id="profile-heading">Model profiles</h2><p>Register memory requirements, then exercise capacity checks</p></div><button className="button button-primary" onClick={() => { setFormOpen(!formOpen); setFormError('') }} disabled={!canRegister} title={!canRegister ? 'A fresh connected host sample is needed to bind exact GPU IDs.' : undefined}><Plus size={15} /> Register profile</button></div>
    <div className="simulation-notice"><span className="simulation-badge">SIMULATION WORKER</span><strong>No inference</strong><span>This M2 worker tests admission and lifecycle only. It does not read model weights, run commands, or generate output.</span></div>
    {!fresh && <div className="profile-gate"><AlertCircle size={16} /><span>Connect to a host with fresh telemetry before registering a profile or using Load/Unload.</span></div>}
    {catalogError && <div className="inline-alert"><AlertCircle size={17} /><span>{catalogError}</span></div>}
    {actionError && <div className="inline-alert"><AlertCircle size={17} /><span>{actionError}</span></div>}
    {formOpen && <form className="profile-form" onSubmit={submit} aria-label="Register simulation model profile">
      <div className="profile-form-heading"><div><strong>New simulation profile</strong><small>Memory values are explicit peak requirements. They are not inferred from model files.</small></div><span className="simulation-badge">SIMULATION ONLY</span></div>
      <div className="profile-form-grid">
        <label className="field"><span>PROFILE ID</span><input className="text-input" required minLength={1} maxLength={64} pattern="[A-Za-z0-9][A-Za-z0-9._-]{0,63}" value={modelId} onChange={(event) => setModelId(event.target.value)} placeholder="my-model-profile" /><small>Letters, numbers, dot, underscore, and hyphen.</small></label>
        <label className="field"><span>MODEL NAME</span><input className="text-input" required maxLength={200} value={name} onChange={(event) => setName(event.target.value)} placeholder="A label you choose" /></label>
        <label className="field"><span>WORKLOAD</span><input className="text-input" required maxLength={40} value={workload} onChange={(event) => setWorkload(event.target.value)} placeholder="Your workload label" /><small>Free text. No model or runtime is assumed.</small></label>
        <label className="field"><span>PEAK SYSTEM RAM (GiB)</span><input className="text-input" type="number" required min="0.000001" step="any" value={ramGib} onChange={(event) => setRamGib(event.target.value)} placeholder="For example, 12" /><small>{ramBytes > 0 && Number.isSafeInteger(Math.round(ramBytes)) ? `${Math.round(ramBytes).toLocaleString()} bytes (GiB × 1,073,741,824)` : 'Enter a positive RAM requirement.'}</small></label>
      </div>
      <div className="gpu-requirements-head"><div><strong>Per-device VRAM requirements</strong><small>Select the UUID reported by this connected host for each GPU requirement.</small></div><button className="button button-secondary" type="button" onClick={addGpuNeed} disabled={!gpus.length || gpuNeeds.length >= gpus.length}>Add GPU requirement</button></div>
      {gpuNeeds.length === 0 && <p className="gpu-form-empty">No GPU requirement added. Use this only if the simulation profile does not need VRAM.</p>}
      <div className="gpu-requirements">{gpuNeeds.map((need, index) => {
        const usedElsewhere = new Set(gpuNeeds.filter((_, other) => other !== index).map((item) => item.deviceId))
        return <div className="gpu-requirement-row" key={index}>
          <label className="field"><span>GPU DEVICE {index + 1}</span><select className="text-input" aria-label={`GPU device ${index + 1}`} required value={need.deviceId} onChange={(event) => setGpuNeeds((items) => items.map((item, row) => row === index ? { ...item, deviceId: event.target.value } : item))}><option value="">Choose a reported GPU</option>{gpus.filter((gpu) => !usedElsewhere.has(gpu.id)).map((gpu) => <option key={gpu.id} value={gpu.id}>{gpu.name} · {gpu.id}</option>)}</select></label>
          <label className="field"><span>PEAK VRAM (GiB)</span><input className="text-input" type="number" required min="0.000001" step="any" aria-label={`Peak VRAM GiB for GPU ${index + 1}`} value={need.gib} onChange={(event) => setGpuNeeds((items) => items.map((item, row) => row === index ? { ...item, gib: event.target.value } : item))} placeholder="For example, 8" /><small>{Number(need.gib) > 0 && Number.isSafeInteger(Math.round(Number(need.gib) * gigabyte)) ? `${Math.round(Number(need.gib) * gigabyte).toLocaleString()} bytes` : 'Enter a positive VRAM requirement.'}</small></label>
          <button className="remove-requirement" type="button" aria-label={`Remove GPU requirement ${index + 1}`} onClick={() => setGpuNeeds((items) => items.filter((_, row) => row !== index))}><X size={16} /></button>
        </div>
      })}</div>
      {formError && <div className="form-error" role="alert"><AlertCircle size={15} />{formError}</div>}
      <div className="profile-form-actions"><span>Server admission checks remain authoritative for every load.</span><div><button className="button button-secondary" type="button" onClick={() => { resetForm(); setFormOpen(false) }}>Cancel</button><button className="button button-primary" type="submit" disabled={!formValid || !canRegister || submitting}>{submitting ? 'Registering…' : 'Register simulation profile'}</button></div></div>
    </form>}
    {profiles === null && !catalogError ? <div className="empty-models"><div className="empty-illustration"><Database size={22} /></div><div><strong>Profile catalog is waiting</strong><p>Connect to a host to read its registered profiles from the server.</p></div></div> : profiles?.length === 0 ? <div className="empty-models"><div className="empty-illustration"><Database size={22} /></div><div><strong>No registered profiles</strong><p>Register an explicit memory profile to try the test worker.</p></div><div className="empty-status">EMPTY CATALOG</div></div> : <div className="profile-list">{(profiles ?? []).map((profile) => {
      const model = models?.find((item) => item.id === profile.model_id)
      const requiredGpuIds = Object.keys(profile.gpu_vram_bytes_by_id)
      const missingGpu = requiredGpuIds.find((id) => !gpus.some((gpu) => gpu.id === id))
      const selectedGpusValid = requiredGpuIds.every((id) => {
        const gpu = gpus.find((item) => item.id === id)
        return !!gpu?.memory && !gpu.error
      })
      const canLoad = !!operatingHost && !!host?.ram && !!model?.loading_enabled && selectedGpusValid && ['unloaded', 'error'].includes(model.state) && pendingModelId !== model.id
      const canUnload = !!operatingHost && model?.state === 'simulation_ready' && pendingModelId !== model.id
      const disabledReason = !fresh ? 'A fresh telemetry sample is required.'
        : !host?.loading_enabled ? host?.loading_reason ?? 'The host has not confirmed lifecycle eligibility.'
        : !operatingHost ? 'Lifecycle testing requires a desktop host measured directly in host scope.'
          : !host?.ram ? 'System RAM telemetry is unavailable.'
        : ['unloaded', 'error'].includes(model?.state ?? '') && missingGpu ? `Required GPU UUID is not present: ${missingGpu}`
          : ['unloaded', 'error'].includes(model?.state ?? '') && !selectedGpusValid ? 'Required GPU memory telemetry is unavailable.'
                : model?.loading_reason ?? `Action unavailable while state is ${model?.state ?? 'unknown'}.`
      return <article className="profile-card" key={profile.model_id}>
        <div className="profile-card-main"><div className="model-icon"><Cpu size={18} /></div><div className="profile-card-title"><div><strong>{profile.name}</strong><span className="profile-id">{profile.model_id} · {profile.workload}</span></div><span className={`model-state state-${model?.state ?? 'unknown'}`}>{pendingModelId === model?.id ? 'Working…' : stateLabel(model?.state ?? 'unknown')}</span></div></div>
        <div className="profile-data-grid"><div><span>PEAK SYSTEM RAM</span><strong>{formatBytes(profile.ram_peak_bytes)}</strong></div><div><span>GPU MEMORY TARGETS</span><strong>{requiredGpuIds.length || 'None'}</strong></div><div><span>EXECUTION</span><strong className="sim-execution">Fake worker · no inference</strong></div></div>
        {requiredGpuIds.length > 0 && <div className="profile-gpu-list">{requiredGpuIds.map((id) => { const gpu = gpus.find((item) => item.id === id); return <div key={id}><span>{gpu?.name ?? 'Unreported GPU'}</span><code>{id}</code><strong>{formatBytes(profile.gpu_vram_bytes_by_id[id])}</strong></div> })}</div>}
        {!model && <p className="profile-warning">The host profile exists, but its model lifecycle state is not in the model catalog.</p>}
        {refusals[profile.model_id] && <RefusalDetails refusal={refusals[profile.model_id]} />}
        <div className="profile-card-footer"><span className="worker-caption"><span className="simulation-badge">SIMULATION</span> No model weights or outputs are used.</span>{model && <div className="profile-actions">{['unloaded', 'error'].includes(model.state) ? <button className="button button-primary" disabled={!canLoad} title={!canLoad ? disabledReason : 'Server checks capacity before starting the fake worker.'} onClick={() => void onLifecycle(model, 'load', profile)}><ArrowUpRight size={14} />{model.state === 'error' ? 'Retry simulation' : 'Load simulation'}</button> : model.state === 'simulation_ready' ? <button className="button button-secondary" disabled={!canUnload} title={!canUnload ? disabledReason : 'Stop the fake worker.'} onClick={() => void onLifecycle(model, 'unload', profile)}><X size={14} />Unload simulation</button> : <button className="button button-secondary" disabled title={disabledReason}>{stateLabel(model.state)}</button>}</div>}</div>
      </article>
    })}</div>}
    <div className="model-footnote"><CircleHelp size={14} /><span>Load requests are checked again by the host. Browser state is never the capacity authority.</span></div>
    {operations.length > 0 && <section className="operations-section" aria-labelledby="operations-heading"><div className="section-heading"><div><h3 id="operations-heading">Recent worker operations</h3><p>Status is polled from the host; no progress percentage is invented.</p></div></div><div className="operation-list">{operations.map((operation) => <div className="operation-row" key={operation.id}><span className={`operation-mark op-${operation.status}`}><Activity size={15} /></span><div className="operation-copy"><strong>{operation.simulation ? (operation.action === 'load' ? 'Load simulation' : 'Unload simulation') : (operation.action === 'load' ? 'Start' : 'Stop')} · {operation.status.replaceAll('_', ' ')}</strong><small>{operation.model_id} · operation {operation.id}</small>{operation.error_message && <small className="operation-error">{operation.error_code ? `${operation.error_code}: ` : ''}{operation.error_message}</small>}</div><span className="simulation-badge">{operation.simulation ? 'NO INFERENCE' : 'MODEL SERVER'}</span></div>)}</div></section>}
  </section>
}

function defaultLaunch(runtime: Runtime, presetKey: string): Launch {
  const preset = runtime.presets[presetKey]
  const settings: Record<string, SettingValue> = {}
  for (const setting of preset?.settings ?? []) settings[setting.key] = setting.default
  // Reuse the last start's choices when it used the same preset.
  if (runtime.last_launch?.preset === presetKey) {
    for (const [key, value] of Object.entries(runtime.last_launch.settings)) if (key in settings) settings[key] = value
    return { preset: presetKey, settings, gpus: [...runtime.last_launch.gpus] }
  }
  return { preset: presetKey, settings, gpus: [...(preset?.gpus ?? [])] }
}

function settingProblem(setting: RuntimeSetting, value: SettingValue) {
  if (setting.kind === 'bool' || setting.kind === 'choice') return ''
  if (value === null) return setting.kind === 'optional_int' ? '' : 'Required.'
  if (typeof value !== 'number' || !Number.isInteger(value)) return 'Enter a whole number.'
  if (setting.minimum !== null && value < setting.minimum) return `At least ${setting.minimum}.`
  if (setting.maximum !== null && value > setting.maximum) return `At most ${setting.maximum}.`
  return ''
}

type GenerateHandlers = {
  jobs: Job[]; jobErrors: Record<string, string>
  onGenerate: (runtime: Runtime, inputs: Record<string, string | number | null>) => Promise<boolean>
  fileUrl: (job: Job, output: JobOutput) => Promise<string>
}

function RuntimePanel({ runtimes, models, host, fresh, pendingModelId, refusals, messages, onRun, ...generate }: {
  runtimes: Runtime[] | null; models: Model[] | null; host?: Host; fresh: boolean; pendingModelId: string | null
  refusals: Record<string, Refusal>; messages: Record<string, string>
  onRun: (runtime: Runtime, action: 'start' | 'stop', launch?: Launch) => Promise<void>
} & GenerateHandlers) {
  if (!runtimes || runtimes.length === 0) return null
  return <section className="models-section runtime-section" aria-labelledby="runtime-heading">
    <div className="section-heading model-heading"><div><h2 id="runtime-heading">Model servers</h2><p>Real models that run on this machine. Starting one checks free RAM and VRAM first.</p></div></div>
    {runtimes.map((runtime) => <RuntimeCard key={runtime.id} runtime={runtime} model={models?.find((item) => item.id === runtime.id)} host={host} fresh={fresh} pending={pendingModelId === runtime.id} refusal={refusals[runtime.id]} message={messages[runtime.id]} onRun={onRun} {...generate} />)}
  </section>
}

const makeLabel: Record<string, string> = { audio: 'Make a song', image: 'Make a picture', video: 'Make a video' }

function GenerateForm({ runtime, generation, onGenerate, error }: { runtime: Runtime; generation: Generation; error?: string; onGenerate: GenerateHandlers['onGenerate'] }) {
  const [values, setValues] = useState<Record<string, string>>(() => Object.fromEntries(generation.inputs.map((field) => [field.key, field.default == null ? '' : String(field.default)])))
  const [advanced, setAdvanced] = useState(false)
  const [sending, setSending] = useState(false)
  const problem = (field: InputField) => {
    const raw = values[field.key] ?? ''
    if (!raw.trim()) return field.required ? 'Required.' : ''
    if ((field.kind === 'text' || field.kind === 'textarea') && field.max_length && raw.length > field.max_length) return `At most ${field.max_length} characters.`
    if (field.kind === 'int' || field.kind === 'seed') {
      const number = Number(raw)
      if (!Number.isInteger(number)) return 'Enter a whole number.'
      if ((field.minimum !== null && number < field.minimum) || (field.maximum !== null && number > field.maximum)) return `Between ${field.minimum} and ${field.maximum}.`
    }
    return ''
  }
  const valid = generation.inputs.every((field) => !problem(field))
  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!valid) return
    const inputs: Record<string, string | number | null> = {}
    for (const field of generation.inputs) {
      const raw = (values[field.key] ?? '').trim()
      if (!raw) continue
      inputs[field.key] = field.kind === 'int' || field.kind === 'seed' ? Number(raw) : raw
    }
    setSending(true)
    await onGenerate(runtime, inputs)
    setSending(false)
  }
  const renderField = (field: InputField) => {
    const id = `${runtime.id}-input-${field.key}`
    const value = values[field.key] ?? ''
    const set = (next: string) => setValues((current) => ({ ...current, [field.key]: next }))
    return <label className={`field ${field.kind === 'textarea' ? 'field-wide' : ''}`} key={field.key} htmlFor={id}>
      <span>{field.label.toUpperCase()}{field.required ? '' : ' (OPTIONAL)'}</span>
      {field.kind === 'textarea' ? <textarea id={id} className="text-input generate-textarea" rows={10} maxLength={field.max_length ?? undefined} placeholder={field.placeholder ?? undefined} value={value} onChange={(event) => set(event.target.value)} />
        : field.kind === 'choice' ? <select id={id} className="text-input" value={value} onChange={(event) => set(event.target.value)}>{field.options.map((option) => <option key={option} value={option}>{option}</option>)}</select>
          : <input id={id} className="text-input" type={field.kind === 'text' ? 'text' : 'number'} step={field.kind === 'text' ? undefined : 1} maxLength={field.max_length ?? undefined} placeholder={field.placeholder ?? (field.kind === 'seed' ? 'Random' : undefined)} value={value} onChange={(event) => set(event.target.value)} />}
      <small className={problem(field) && value ? 'field-problem' : ''}>{(value && problem(field)) || field.help}</small>
    </label>
  }
  const basic = generation.inputs.filter((field) => !field.advanced)
  const extra = generation.inputs.filter((field) => field.advanced)
  return <form className="generate-form" onSubmit={submit} aria-label={makeLabel[generation.output_kind] ?? 'Make something'}>
    <div className="generate-fields">{basic.map(renderField)}</div>
    {extra.length > 0 && <><button type="button" className="text-button" aria-expanded={advanced} onClick={() => setAdvanced(!advanced)}><ChevronDown size={14} className={advanced ? 'chevron-open' : ''} /> More options</button>
      {advanced && <div className="generate-fields">{extra.map(renderField)}</div>}</>}
    {error && <div className="form-error" role="alert"><AlertCircle size={15} />{error}</div>}
    <div className="generate-actions"><button className="button button-primary" type="submit" disabled={!valid || sending}><Sparkles size={15} />{sending ? 'Sending…' : makeLabel[generation.output_kind] ?? 'Make it'}</button></div>
  </form>
}

function JobList({ jobs, fileUrl }: { jobs: Job[]; fileUrl: GenerateHandlers['fileUrl'] }) {
  if (jobs.length === 0) return null
  return <div className="job-list" aria-label="Results">{jobs.map((job) => <JobRow key={job.id} job={job} fileUrl={fileUrl} />)}</div>
}

function JobRow({ job, fileUrl }: { job: Job; fileUrl: GenerateHandlers['fileUrl'] }) {
  const [urls, setUrls] = useState<Record<string, string>>({})
  const [error, setError] = useState('')
  const media = job.outputs.filter((output) => /^(audio|image|video)\//.test(output.mime))
  useEffect(() => {
    if (job.status !== 'done') return
    let cancelled = false
    const made: string[] = []
    void Promise.all(media.map(async (output) => {
      const url = await fileUrl(job, output)
      made.push(url)
      if (!cancelled) setUrls((current) => ({ ...current, [output.name]: url }))
    })).catch((reason) => { if (!cancelled) setError(reason instanceof Error ? reason.message : 'The file could not be loaded.') })
    return () => { cancelled = true; made.forEach((url) => URL.revokeObjectURL(url)) }
    // Load each finished job's files once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job.id, job.status])
  const title = typeof job.inputs.style === 'string' ? job.inputs.style : typeof job.inputs.prompt === 'string' ? job.inputs.prompt : 'Untitled'
  const statusText = { queued: 'Waiting its turn', running: job.progress ?? 'Working', done: job.progress ?? 'Done', failed: 'Did not work' }[job.status] ?? job.status
  return <article className={`job-row job-${job.status}`}>
    <div className="job-head"><strong>{title}</strong><span className={`model-state state-${job.status === 'done' ? 'ready' : job.status === 'failed' ? 'error' : 'loading'}`}>{statusText}</span></div>
    {job.status === 'failed' && job.error_message && <small className="operation-error">{job.error_message}</small>}
    {error && <small className="operation-error">{error}</small>}
    {media.map((output) => <div className="job-media" key={output.name}>
      {urls[output.name] ? (output.mime.startsWith('audio/') ? <audio controls src={urls[output.name]} aria-label={`Play ${title}`} />
        : output.mime.startsWith('image/') ? <img src={urls[output.name]} alt={title} />
          : <video controls src={urls[output.name]} />) : <small>Loading…</small>}
      {urls[output.name] && <a className="text-button" href={urls[output.name]} download={output.name}>Download {output.name}</a>}
    </div>)}
  </article>
}

function RuntimeCard({ runtime, model, host, fresh, pending, refusal, message, onRun, jobs, jobErrors, onGenerate, fileUrl }: {
  runtime: Runtime; model?: Model; host?: Host; fresh: boolean; pending: boolean; refusal?: Refusal; message?: string
  onRun: (runtime: Runtime, action: 'start' | 'stop', launch?: Launch) => Promise<void>
} & GenerateHandlers) {
  const initialPreset = runtime.last_launch?.preset && runtime.presets[runtime.last_launch.preset] ? runtime.last_launch.preset : runtime.default_preset
  const [launch, setLaunch] = useState<Launch>(() => defaultLaunch(runtime, initialPreset))
  const [advanced, setAdvanced] = useState(false)
  const preset = runtime.presets[launch.preset]
  const state = model?.state ?? 'unknown'
  const stopped = ['unloaded', 'error'].includes(state)
  const running = ['ready', 'cleanup_failed'].includes(state)
  const problems = Object.fromEntries((preset?.settings ?? []).map((setting) => [setting.key, settingProblem(setting, launch.settings[setting.key] ?? null)]))
  const valid = !!preset && launch.gpus.length > 0 && Object.values(problems).every((problem) => !problem)
  const canStart = fresh && host?.loading_enabled === true && stopped && valid && !pending
  const gpuName = (index: number) => preset?.allowed_gpus.find((gpu) => gpu.index === index)?.name ?? `GPU ${index}`
  const budget = launch.settings.resident_budget_gib
  const ramNeed = (preset?.estimate.ram_gib ?? 0) + (typeof budget === 'number' ? budget : 0)
  const stateText = ({ unloaded: 'Stopped', loading: 'Loading', ready: 'Running', unloading: 'Stopping', error: 'Stopped after an error', cleanup_failed: 'Stop did not finish' } as Record<string, string>)[state] ?? state
  const setValue = (key: string, value: SettingValue) => setLaunch((current) => ({ ...current, settings: { ...current.settings, [key]: value } }))
  const choosePreset = (key: string) => setLaunch(defaultLaunch(runtime, key))
  const reset = () => setLaunch(defaultLaunch({ ...runtime, last_launch: null }, launch.preset))

  return <article className="profile-card runtime-card">
    <div className="profile-card-main"><div className="model-icon"><Server size={18} /></div><div className="profile-card-title"><div><strong>{runtime.name}</strong><span className="profile-id">{runtime.workload} · port {runtime.port}</span></div><span className={`model-state state-${state}`}>{pending ? 'Working…' : stateText}</span></div></div>

    <fieldset className="runtime-choice" disabled={!stopped || pending}>
      <legend>Model</legend>
      {Object.entries(runtime.presets).map(([key, item]) => <label key={key} className={`runtime-option ${launch.preset === key ? 'runtime-option-on' : ''}`}><input type="radio" name={`${runtime.id}-preset`} checked={launch.preset === key} onChange={() => choosePreset(key)} /><span>{item.name}</span></label>)}
    </fieldset>

    {preset && <fieldset className="runtime-choice" disabled={!stopped || pending}>
      <legend>GPUs</legend>
      {preset.allowed_gpus.map((gpu) => <label key={gpu.index} className={`runtime-option ${launch.gpus.includes(gpu.index) ? 'runtime-option-on' : ''}`}>{runtime.max_gpus === 1
        ? <input type="radio" name={`${runtime.id}-gpu`} checked={launch.gpus.includes(gpu.index)} onChange={() => setLaunch((current) => ({ ...current, gpus: [gpu.index] }))} />
        : <input type="checkbox" checked={launch.gpus.includes(gpu.index)} onChange={(event) => setLaunch((current) => ({ ...current, gpus: event.target.checked ? [...current.gpus, gpu.index].sort() : current.gpus.filter((item) => item !== gpu.index) }))} />}<span>{gpu.name}</span></label>)}
      {launch.gpus.length === 0 && <small className="field-problem">Choose at least one GPU.</small>}
    </fieldset>}

    {preset && <p className="runtime-estimate">Needs about {launch.gpus.map((index) => `${preset.estimate.gpu_min_free_gib[String(index)] ?? 0} GiB free on the ${gpuName(index)}`).join(', ')} and {ramNeed} GiB of RAM. These are estimates; Basalt uses whatever VRAM is free beyond its reserve.</p>}

    {preset && <div className="runtime-advanced">
      <button type="button" className="text-button" aria-expanded={advanced} onClick={() => setAdvanced(!advanced)}><ChevronDown size={14} className={advanced ? 'chevron-open' : ''} /> Advanced settings</button>
      {advanced && <div className="runtime-settings">
        {preset.settings.map((setting) => {
          const value = launch.settings[setting.key] ?? null
          const id = `${runtime.id}-${setting.key}`
          return <label className="field" key={setting.key} htmlFor={id}>
            <span>{setting.label.toUpperCase()}{setting.unit ? ` (${setting.unit})` : ''}</span>
            {setting.kind === 'bool' ? <input id={id} type="checkbox" disabled={!stopped || pending} checked={value === true} onChange={(event) => setValue(setting.key, event.target.checked)} />
              : setting.kind === 'choice' ? <select id={id} className="text-input" disabled={!stopped || pending} value={String(value ?? '')} onChange={(event) => setValue(setting.key, event.target.value)}>{(setting.options ?? []).map((option) => <option key={option} value={option}>{option}</option>)}</select>
              : <input id={id} className="text-input" type="number" step={1} min={setting.minimum ?? undefined} max={setting.maximum ?? undefined} disabled={!stopped || pending}
                  placeholder={setting.kind === 'optional_int' ? 'Automatic' : undefined} value={value === null ? '' : String(value)}
                  onChange={(event) => setValue(setting.key, event.target.value === '' ? null : Number(event.target.value))} />}
            <small className={problems[setting.key] ? 'field-problem' : ''}>{problems[setting.key] || setting.help}</small>
            {setting.key === 'ram_reserve_mib' && value === 0 && <small className="field-warning">The RAM guard is off. Fine when Basalt is the only thing running; risky when other models or games need RAM.</small>}
          </label>
        })}
        <div className="runtime-settings-actions"><button type="button" className="button button-secondary" disabled={!stopped || pending} onClick={reset}>Reset to defaults</button></div>
      </div>}
    </div>}

    {refusal && <RefusalDetails refusal={refusal} gpus={host?.gpus} />}
    {message && <p className="runtime-message" aria-live="polite">{message}</p>}
    {runtime.generation && state === 'ready' && <GenerateForm runtime={runtime} generation={runtime.generation} onGenerate={onGenerate} error={jobErrors[runtime.id]} />}
    {runtime.generation && <JobList jobs={jobs.filter((job) => job.model_id === runtime.id)} fileUrl={fileUrl} />}
    <div className="profile-card-footer"><span className="worker-caption">{running && model ? 'Running. Stop it to free its RAM and VRAM.' : stopped ? 'Stopped. Nothing is using memory.' : 'Working. This can take several minutes.'}</span><div className="profile-actions">
      {stopped && <button className="button button-primary" disabled={!canStart} title={!fresh ? 'A fresh telemetry sample is required.' : !host?.loading_enabled ? host?.loading_reason : !valid ? 'Fix the highlighted settings first.' : undefined} onClick={() => void onRun(runtime, 'start', launch)}><ArrowUpRight size={14} />{state === 'error' ? 'Start again' : 'Start'}</button>}
      {running && <button className="button button-secondary" disabled={pending || !fresh} onClick={() => void onRun(runtime, 'stop')}><X size={14} />Stop</button>}
      {!stopped && !running && <button className="button button-secondary" disabled>{stateText}…</button>}
    </div></div>
  </article>
}

function RefusalDetails({ refusal, gpus }: { refusal: Refusal; gpus?: Gpu[] }) {
  const resourceName = (resource: string) => {
    if (resource === 'ram') return 'System RAM'
    const gpu = resource.startsWith('gpu:') ? gpus?.find((item) => item.id === resource.slice(4)) : undefined
    return gpu ? gpu.name : resource
  }
  return <div className="refusal-details" role="alert"><div><AlertCircle size={15} /><strong>{refusal.code}</strong><span>{refusal.message}</span></div>{refusal.resources?.map((resource, index) => <div className="refusal-resource" key={`${resource.resource}-${index}`}><strong>{resourceName(resource.resource)}</strong><span>Required {formatBytes(resource.required_bytes)}</span><span>Available {formatBytes(resource.available_bytes)}</span>{resource.headroom_bytes !== undefined && <span>Headroom {formatBytes(resource.headroom_bytes)}</span>}</div>)}</div>
}
