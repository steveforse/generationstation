import { ApiError, type ApiErrorBody, type Host, type Job, type Memory, type Model, type ModelProfile, type Operation, type Refusal, type Runtime } from './types'

export function formatBytes(value?: number | null) {
  if (value == null || !Number.isFinite(value) || value < 0) return 'Unavailable'
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']
  if (value < 1024) return `${value} B`
  let amount = value
  let unit = 0
  while (amount >= 1024 && unit < units.length - 1) { amount /= 1024; unit += 1 }
  return `${amount.toFixed(amount < 10 ? 1 : 0).replace(/\.0$/, '')} ${units[unit]}`
}

export function humanAge(seconds: number | null) {
  if (seconds == null || !Number.isFinite(seconds)) return 'No sample yet'
  // Samples arrive every second or two; only mention the age once it is noticeably old, to avoid flicker.
  if (seconds < 5) return ''
  return `Updated ${Math.floor(seconds)}s ago`
}

export function normalizeBase(url: string) {
  const trimmed = url.trim()
  if (!trimmed) return ''
  const parsed = new URL(trimmed)
  if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error('Use an http:// or https:// server address.')
  if (parsed.username || parsed.password || parsed.search || parsed.hash || (parsed.pathname !== '/' && parsed.pathname !== '')) {
    throw new Error('Enter the server origin only, without a path, query, or credentials.')
  }
  return parsed.toString().replace(/\/$/, '')
}

export function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function validMemory(value: unknown): value is Memory {
  if (!value || typeof value !== 'object') return false
  const { total_bytes: total, available_bytes: available, used_bytes: used } = value as Record<string, unknown>
  return isFiniteNumber(total) && total > 0 && isFiniteNumber(available) && available >= 0 && available <= total
    && isFiniteNumber(used) && used >= 0 && used <= total
}

export function isHost(value: unknown): value is Host {
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

export function isCatalog(value: unknown): value is { models: Model[] } {
  if (!value || typeof value !== 'object' || !Array.isArray((value as Record<string, unknown>).models)) return false
  return ((value as { models: unknown[] }).models).every((entry) => !!entry && typeof entry === 'object'
    && typeof (entry as Record<string, unknown>).id === 'string'
    && typeof (entry as Record<string, unknown>).name === 'string'
    && typeof (entry as Record<string, unknown>).workload === 'string'
    && typeof (entry as Record<string, unknown>).state === 'string'
    && typeof (entry as Record<string, unknown>).loading_enabled === 'boolean')
}

export function isProfiles(value: unknown): value is { profiles: ModelProfile[] } {
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

export function isOperation(value: unknown): value is Operation {
  if (!value || typeof value !== 'object') return false
  const operation = value as Record<string, unknown>
  return typeof operation.id === 'string' && typeof operation.model_id === 'string'
    && typeof operation.action === 'string' && typeof operation.status === 'string'
    && ((operation.simulation === true && operation.worker_type === 'fake')
      || (operation.simulation === false && operation.worker_type === 'runtime'))
}

export function isOperations(value: unknown): value is { operations: Operation[] } {
  return !!value && typeof value === 'object' && Array.isArray((value as Record<string, unknown>).operations)
    && ((value as { operations: unknown[] }).operations).every(isOperation)
}

export function isJob(value: unknown): value is Job {
  if (!value || typeof value !== 'object') return false
  const job = value as Record<string, unknown>
  return typeof job.id === 'string' && typeof job.model_id === 'string' && typeof job.status === 'string'
    && Array.isArray(job.outputs) && !!job.inputs && typeof job.inputs === 'object'
}

export function isJobs(value: unknown): value is { jobs: Job[] } {
  return !!value && typeof value === 'object' && Array.isArray((value as Record<string, unknown>).jobs)
    && ((value as { jobs: unknown[] }).jobs).every(isJob)
}

export function isRuntimes(value: unknown): value is { runtimes: Runtime[] } {
  if (!value || typeof value !== 'object' || !Array.isArray((value as Record<string, unknown>).runtimes)) return false
  return ((value as { runtimes: unknown[] }).runtimes).every((entry) => {
    if (!entry || typeof entry !== 'object') return false
    const runtime = entry as Record<string, unknown>
    return typeof runtime.id === 'string' && typeof runtime.name === 'string' && typeof runtime.default_preset === 'string'
      && !!runtime.presets && typeof runtime.presets === 'object'
  })
}

export function isRefusal(value: unknown): value is Refusal {
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

export function isTerminalOperation(status: string) {
  return ['simulation_ready', 'ready', 'unloaded', 'refused', 'failed', 'cleanup_failed'].includes(status)
}

export function idempotencyKey() {
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  return Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('')
}

export function sseBoundary(value: string) { return /\r\n\r\n|\n\n|\r\r/.exec(value) }

export function readWithWatchdog<T>(promise: Promise<T>, controller: AbortController, milliseconds: number): Promise<T> {
  return new Promise((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      controller.abort()
      reject(new Error('No telemetry arrived before the stream watchdog expired.'))
    }, milliseconds)
    promise.then((value) => { window.clearTimeout(timeout); resolve(value) }, (error) => { window.clearTimeout(timeout); reject(error) })
  })
}

export function apiUrl(base: string, path: string) { return `${base}${path}` }

export async function requestApi(base: string, token: string, path: string, init: RequestInit = {}, parentSignal?: AbortSignal) {
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

export function parseSseBlock(block: string): { event: string; data: string } | null {
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
