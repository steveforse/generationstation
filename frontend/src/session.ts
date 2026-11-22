import {
  apiUrl, idempotencyKey, isCatalog, isHost, isJob, isJobs, isOperation, isOperations, isProfiles, isRefusal,
  isRuntimes, isTerminalOperation, normalizeBase, parseSseBlock, readWithWatchdog, requestApi, sseBoundary,
} from './api'
import type { SavedHost } from './hosts'
import {
  ApiError, type Connection, type Job, type JobOutput, type Launch, type Model, type ModelProfile, type NewProfile,
  type Operation, type Refusal, type Runtime, type RuntimeEstimate, type Snapshot, type UploadRecord,
} from './types'

/** How many recent results to keep in view (the results sidebar lists them). */
const JOB_LIMIT = 100

export type SessionState = {
  connection: Connection
  message: string
  snapshot: Snapshot | null
  models: Model[] | null
  profiles: ModelProfile[] | null
  runtimes: Runtime[] | null
  operations: Operation[]
  jobs: Job[]
  catalogError: string
  actionError: string
  pendingModelId: string | null
  refusals: Record<string, Refusal>
  runtimeMessages: Record<string, string>
  jobErrors: Record<string, string>
}

const initialState = (message = 'Open Connections to connect this host.'): SessionState => ({
  connection: 'idle', message, snapshot: null, models: null, profiles: null, runtimes: null, operations: [], jobs: [],
  catalogError: '', actionError: '', pendingModelId: null, refusals: {}, runtimeMessages: {}, jobErrors: {},
})

const REJECTED = 'The access token was rejected. Check it on the Connections page.'

/** One host's connection: telemetry stream, catalog, and every action against that host. */
export class HostSession {
  state: SessionState = initialState()
  private listeners = new Set<() => void>()
  private controller: AbortController | null = null
  private generation = 0
  private instanceId: string | null = null
  private busyTimer: number | null = null
  private jobTimer: number | null = null

  constructor(public host: SavedHost) {}

  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener) } }
  getState = () => this.state

  private set(patch: Partial<SessionState> | ((state: SessionState) => Partial<SessionState>)) {
    const next = typeof patch === 'function' ? patch(this.state) : patch
    this.state = { ...this.state, ...next }
    this.listeners.forEach((listener) => listener())
  }

  private base() { return normalizeBase(this.host.url) }
  private token() { return this.host.token.trim() }

  /** Fresh means connected with a recent sample; actions that change state require it. */
  fresh() {
    const snapshot = this.state.snapshot
    if (this.state.connection !== 'connected' || !snapshot || snapshot.data.stale || snapshot.data.age_seconds === null) return false
    const age = snapshot.data.age_seconds + (performance.now() - snapshot.arrivedAt) / 1000
    return age < snapshot.data.stale_after_seconds
  }

  update(host: SavedHost) {
    const changed = host.url !== this.host.url || host.token !== this.host.token
    this.host = host
    if (changed && this.state.connection !== 'idle') this.disconnect('Connection settings changed. Connect again.')
  }

  disconnect(message = 'Disconnected.') {
    this.controller?.abort()
    this.controller = null
    this.generation += 1
    this.instanceId = null
    if (this.busyTimer !== null) { window.clearTimeout(this.busyTimer); this.busyTimer = null }
    if (this.jobTimer !== null) { window.clearTimeout(this.jobTimer); this.jobTimer = null }
    this.state = initialState(message)
    this.listeners.forEach((listener) => listener())
  }

  async connect() {
    this.disconnect('Checking the host and opening its telemetry stream…')
    const generation = this.generation
    const controller = new AbortController()
    this.controller = controller
    this.set({ connection: 'connecting' })
    let base: string
    try { base = this.base() } catch (error) {
      this.set({ connection: 'error', message: error instanceof Error ? error.message : 'Invalid server address.' })
      return
    }
    if (!this.token()) {
      this.set({ connection: 'error', message: 'Enter the access token configured on the host.' })
      return
    }
    const headers = { Authorization: `Bearer ${this.token()}` }
    const current = () => !controller.signal.aborted && this.generation === generation
    const assertCurrent = () => { if (!current()) throw new DOMException('Aborted', 'AbortError') }
    const fetchJson = async (path: string) => {
      const request = new AbortController()
      const abortRequest = () => request.abort()
      controller.signal.addEventListener('abort', abortRequest, { once: true })
      const timeout = window.setTimeout(abortRequest, 10_000)
      try {
        const response = await fetch(apiUrl(base, path), { headers, signal: request.signal, cache: 'no-store' })
        if (response.status === 401) throw new Error(REJECTED)
        if (!response.ok) throw new Error(`Host request failed (${response.status}).`)
        try { return await response.json() } catch { throw new Error('This address did not return a valid Generation Station API response.') }
      } catch (error) {
        if (!controller.signal.aborted && request.signal.aborted) throw new Error('Host request timed out. Check the address and try again.')
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
      this.instanceId = initial.instance_id
      this.set({ snapshot: { data: initial, arrivedAt: performance.now() }, message: 'Host found. Waiting for the next live telemetry sample…' })
      void this.refreshCatalog()
      let retry = 0
      while (current()) {
        const stream = new AbortController()
        let reader: ReadableStreamDefaultReader<Uint8Array> | null = null
        const abortStream = () => stream.abort()
        controller.signal.addEventListener('abort', abortStream, { once: true })
        try {
          const headerTimeout = window.setTimeout(() => stream.abort(), 10_000)
          let response: Response
          try {
            response = await fetch(apiUrl(base, '/api/events'), { headers: { ...headers, Accept: 'text/event-stream' }, signal: stream.signal, cache: 'no-store' })
          } finally { window.clearTimeout(headerTimeout) }
          if (response.status === 401) throw new Error(REJECTED)
          if (!response.ok || !response.body) throw new Error(`Telemetry stream failed (${response.status}).`)
          let lastValid = performance.now()
          this.set({ message: 'Stream open. Waiting for a valid host measurement…' })
          retry = 0
          reader = response.body.getReader()
          const decoder = new TextDecoder()
          let buffer = ''
          while (true) {
            if (performance.now() - lastValid > Math.max(12_000, initial.stale_after_seconds * 1000 + 1_500)) {
              throw new Error('No fresh host sample arrived before the telemetry watchdog expired.')
            }
            const next = await readWithWatchdog(reader.read(), stream, 12_000)
            if (next.done) throw new Error('Telemetry stream closed by the host.')
            buffer += decoder.decode(next.value, { stream: true })
            if (buffer.length > 1_000_000) throw new Error('Telemetry stream event exceeded the allowed size.')
            let boundary = sseBoundary(buffer)
            while (boundary) {
              const parsed = parseSseBlock(buffer.slice(0, boundary.index))
              buffer = buffer.slice(boundary.index + boundary[0].length)
              if (parsed?.event === 'host') {
                let data: unknown
                try { data = JSON.parse(parsed.data) } catch { throw new Error('The host sent malformed telemetry JSON.') }
                if (!isHost(data)) throw new Error('The host sent an invalid telemetry sample.')
                assertCurrent()
                const changedInstance = this.instanceId !== data.instance_id
                this.instanceId = data.instance_id
                lastValid = performance.now()
                this.set({ snapshot: { data, arrivedAt: performance.now() }, connection: 'connected', message: 'Live telemetry is streaming from the host.' })
                if (changedInstance) { this.set({ models: null, profiles: null }); void this.refreshCatalog() }
              }
              boundary = sseBoundary(buffer)
            }
          }
        } catch (error) {
          if (!current()) break
          if (error instanceof Error && error.message === REJECTED) { this.set({ connection: 'error', message: REJECTED }); break }
          retry += 1
          this.set({ connection: 'reconnecting', message: `Telemetry stream interrupted. Reconnecting (attempt ${retry})…` })
          await new Promise((resolve) => window.setTimeout(resolve, Math.min(1_000 * 2 ** Math.min(retry - 1, 4), 12_000)))
        } finally {
          if (reader) void reader.cancel().catch(() => undefined)
          stream.abort()
          controller.signal.removeEventListener('abort', abortStream)
        }
      }
    } catch (error) {
      if (!current()) return
      this.set({ connection: 'error', message: error instanceof Error ? error.message : 'Could not connect to the host.' })
    }
  }

  private context() {
    if (!this.controller) return null
    return { generation: this.generation, signal: this.controller.signal, base: this.base(), token: this.token() }
  }

  private stillCurrent(generation: number, signal: AbortSignal) { return !signal.aborted && this.generation === generation }

  async refreshCatalog() {
    const ctx = this.context()
    if (!ctx) return
    const { generation, signal, base, token } = ctx
    try {
      const [models, profiles] = await Promise.all([
        requestApi(base, token, '/api/models', {}, signal), requestApi(base, token, '/api/profiles', {}, signal),
      ])
      if (!this.stillCurrent(generation, signal)) return
      if (!isCatalog(models) || !isProfiles(profiles)) throw new Error('The host returned an invalid model catalog.')
      this.set({ models: models.models, catalogError: '',
        profiles: profiles.profiles.map((p) => ({ ...p, id: p.id || p.model_id, model_id: p.model_id || p.id })) })
      const [operations, runtimes, jobs] = await Promise.all([
        requestApi(base, token, '/api/operations?limit=100', {}, signal).catch(() => null),
        requestApi(base, token, '/api/runtimes', {}, signal).catch(() => null),
        requestApi(base, token, `/api/jobs?limit=${JOB_LIMIT}`, {}, signal).catch(() => null),
      ])
      if (!this.stillCurrent(generation, signal)) return
      this.set((state) => ({
        operations: isOperations(operations) ? operations.operations.slice(0, 8) : state.operations,
        runtimes: isRuntimes(runtimes) ? runtimes.runtimes : (state.runtimes ?? []),
        jobs: isJobs(jobs) ? jobs.jobs : state.jobs,
      }))
      this.scheduleBusyPoll()
      this.scheduleJobPoll()
    } catch (error) {
      if (!this.stillCurrent(generation, signal)) return
      if (error instanceof ApiError && error.status === 401) { this.disconnect(REJECTED); this.set({ connection: 'error' }); return }
      this.set({ models: null, profiles: null, catalogError: error instanceof Error ? error.message : 'The model catalog is unavailable.' })
    }
  }

  /** While a runtime starts or stops (it can take many minutes), keep its state current. */
  private scheduleBusyPoll() {
    if (this.busyTimer !== null) { window.clearTimeout(this.busyTimer); this.busyTimer = null }
    const { models, runtimes } = this.state
    const busy = !!models?.some((model) => runtimes?.some((runtime) => runtime.id === model.id) && ['loading', 'unloading'].includes(model.state))
    if (busy) this.busyTimer = window.setTimeout(() => { this.busyTimer = null; void this.refreshCatalog() }, 3_000)
  }

  /** While anything is queued or being made, refresh the results every few seconds (the queue, progress, cancels). */
  private scheduleJobPoll() {
    if (this.jobTimer !== null) return
    if (!this.state.jobs.some((job) => job.status === 'queued' || job.status === 'running')) return
    this.jobTimer = window.setTimeout(async () => {
      this.jobTimer = null
      const ctx = this.context()
      // Keep going while the telemetry stream reconnects: results come over plain requests, and a failed one is retried.
      if (!ctx) return  // disconnected; connecting again refreshes the results and restarts this
      const jobs = await requestApi(ctx.base, ctx.token, `/api/jobs?limit=${JOB_LIMIT}`, {}, ctx.signal).catch(() => null)
      if (!this.stillCurrent(ctx.generation, ctx.signal)) return
      if (isJobs(jobs)) this.set({ jobs: jobs.jobs })
      this.scheduleJobPoll()
    }, 3_000)
  }

  /** Cancel a queued or running job. Returns an error message, or '' when the host accepted it. */
  async cancelJob(job: Job) {
    const ctx = this.context()
    if (!ctx) return 'Not connected to the host.'
    try {
      const next = await requestApi(ctx.base, ctx.token, `/api/jobs/${encodeURIComponent(job.id)}/cancel`, { method: 'POST' }, ctx.signal)
      if (isJob(next)) this.set((state) => ({ jobs: state.jobs.map((other) => other.id === next.id ? next : other) }))
      this.scheduleJobPoll()
      return ''
    } catch (error) {
      if (this.handleAuthError(error)) return 'Not connected to the host.'
      return error instanceof Error ? error.message : 'It could not be cancelled.'
    }
  }

  private handleAuthError(error: unknown) {
    if (error instanceof ApiError && error.status === 401) { this.disconnect(REJECTED); this.set({ connection: 'error' }); return true }
    return false
  }

  async runRuntime(runtime: Runtime, action: 'start' | 'stop', launch?: Launch) {
    const ctx = this.context()
    if (!ctx || !this.fresh()) return
    const { generation, signal, base, token } = ctx
    const say = (text: string) => this.set((state) => ({ runtimeMessages: { ...state.runtimeMessages, [runtime.id]: text } }))
    this.set((state) => {
      const refusals = { ...state.refusals }
      delete refusals[runtime.id]
      return { pendingModelId: runtime.id, actionError: '', refusals }
    })
    say(action === 'start' ? 'Checking capacity…' : 'Stopping…')
    try {
      const path = action === 'start' ? `/api/runtimes/${encodeURIComponent(runtime.id)}/start` : `/api/models/${encodeURIComponent(runtime.id)}/unload`
      const accepted = await requestApi(base, token, path, {
        method: 'POST', headers: { 'Idempotency-Key': idempotencyKey() },
        ...(action === 'start' && launch ? { body: JSON.stringify({ preset: launch.preset, settings: launch.settings, gpus: launch.gpus }) } : {}),
      }, signal)
      if (!isOperation(accepted)) throw new Error('The host returned an invalid operation.')
      let latest: Operation = accepted
      const save = (operation: Operation) => this.set((state) => ({ operations: [operation, ...state.operations.filter((item) => item.id !== operation.id)].slice(0, 8) }))
      save(latest)
      await this.refreshCatalog()
      const started = performance.now()
      while (!isTerminalOperation(latest.status)) {
        const minutes = Math.floor((performance.now() - started) / 60_000)
        say(action === 'start' ? `Loading ${runtime.presets[launch?.preset ?? runtime.default_preset]?.name ?? runtime.name}… ${minutes ? `${minutes} min so far. ` : ''}Large models can take 5–20 minutes.` : 'Stopping…')
        await new Promise((resolve) => window.setTimeout(resolve, 2_000))
        if (!this.stillCurrent(generation, signal)) return
        const result = await requestApi(base, token, `/api/operations/${encodeURIComponent(latest.id)}`, {}, signal)
        if (!isOperation(result)) throw new Error('The host returned an invalid operation status.')
        latest = result
        save(latest)
      }
      say(latest.status === 'ready' ? 'Ready.' : latest.status === 'unloaded' ? 'Stopped.'
        : `${latest.status.replaceAll('_', ' ')}${latest.error_message ? `: ${latest.error_message}` : ''}`)
      await this.refreshCatalog()
    } catch (error) {
      if (!this.stillCurrent(generation, signal) || this.handleAuthError(error)) return
      const detail = error instanceof ApiError ? error.body.detail : undefined
      if (error instanceof ApiError && error.status === 409 && isRefusal(detail) && detail.resources?.length) {
        this.set((state) => ({ refusals: { ...state.refusals, [runtime.id]: detail } }))
        say('')
      } else say(error instanceof Error ? error.message : 'The host could not complete this operation.')
    } finally {
      if (this.generation === generation) this.set({ pendingModelId: null })
    }
  }

  async runJob(runtime: Runtime, inputs: Record<string, string | number | string[] | null>) {
    const ctx = this.context()
    if (!ctx || this.state.connection !== 'connected') return false
    const { generation, signal, base, token } = ctx
    this.set((state) => ({ jobErrors: { ...state.jobErrors, [runtime.id]: '' } }))
    try {
      const accepted = await requestApi(base, token, `/api/models/${encodeURIComponent(runtime.id)}/jobs`, { method: 'POST', body: JSON.stringify({ inputs }) }, signal)
      if (!isJob(accepted)) throw new Error('The host returned an invalid job.')
      const job: Job = accepted
      this.set((state) => ({ jobs: [job, ...state.jobs.filter((other) => other.id !== job.id)].slice(0, JOB_LIMIT) }))
      this.scheduleJobPoll()
      return true
    } catch (error) {
      if (!this.stillCurrent(generation, signal) || this.handleAuthError(error)) return false
      this.set((state) => ({ jobErrors: { ...state.jobErrors, [runtime.id]: error instanceof Error ? error.message : 'The job could not be started.' } }))
      return false
    }
  }

  /** Delete a finished result and its files on the host. Returns an error message, or '' when deleted. */
  async deleteJob(job: Job) {
    const ctx = this.context()
    if (!ctx) return 'Not connected to the host.'
    try {
      await requestApi(ctx.base, ctx.token, `/api/jobs/${encodeURIComponent(job.id)}`, { method: 'DELETE' }, ctx.signal)
    } catch (error) {
      if (!(error instanceof ApiError && error.status === 404)) {
        if (this.handleAuthError(error)) return 'Not connected to the host.'
        return error instanceof Error ? error.message : 'It could not be deleted.'
      }
    }
    this.set((state) => ({ jobs: state.jobs.filter((other) => other.id !== job.id) }))
    return ''
  }

  /** Ask the host what a start with these choices would need. Display only; Start is checked again. */
  async estimateRuntime(runtime: Runtime, launch: Launch, signal?: AbortSignal): Promise<RuntimeEstimate> {
    const ctx = this.context()
    if (!ctx) throw new Error('Not connected.')
    let body: unknown
    try {
      body = await requestApi(ctx.base, ctx.token, `/api/runtimes/${encodeURIComponent(runtime.id)}/estimate`, {
        method: 'POST', body: JSON.stringify({ preset: launch.preset, settings: launch.settings, gpus: launch.gpus }),
      }, signal ?? ctx.signal)
    } catch (error) {
      // A service started before this feature existed has no estimate route.
      if (error instanceof ApiError && error.status === 404 && error.body.detail === 'API route not found') {
        throw new Error('This host’s service is older than this page, so it can’t preview a start. Restart the Generation Station service to update it.')
      }
      throw error
    }
    if (!isEstimate(body)) throw new Error('The host returned an invalid estimate.')
    return body
  }

  /** Upload a file for a request (a reference picture, video or audio); the job refers to it by ID. */
  async uploadFile(file: File): Promise<UploadRecord> {
    const ctx = this.context()
    if (!ctx) throw new Error('Not connected to the host.')
    const response = await fetch(apiUrl(ctx.base, `/api/uploads?name=${encodeURIComponent(file.name)}`), {
      method: 'POST', body: file, signal: ctx.signal,
      headers: { Authorization: `Bearer ${ctx.token}`, 'Content-Type': file.type || 'application/octet-stream' },
    })
    const body = await response.json().catch(() => null) as { detail?: unknown } & Partial<UploadRecord> | null
    if (!response.ok || !body || typeof body.id !== 'string') {
      throw new Error(typeof body?.detail === 'string' ? body.detail : `The file could not be uploaded (${response.status}).`)
    }
    return body as UploadRecord
  }

  /** A job's reference file (picture, video, audio), as a local object URL. */
  async inputUrl(job: Job, name: string) {
    return URL.createObjectURL(await this.inputBlob(job, name))
  }

  async inputBlob(job: Job, name: string) {
    const ctx = this.context()
    if (!ctx) throw new Error('Not connected.')
    const response = await fetch(apiUrl(ctx.base, `/api/jobs/${encodeURIComponent(job.id)}/inputs/${encodeURIComponent(name)}`), {
      headers: { Authorization: `Bearer ${ctx.token}` }, signal: ctx.signal, cache: 'no-store',
    })
    if (!response.ok) throw new Error(`The file could not be loaded (${response.status}).`)
    return response.blob()
  }

  /** Files need the access token, so fetch them and hand the browser a local object URL. */
  async fileUrl(job: Job, output: JobOutput) {
    const ctx = this.context()
    if (!ctx) throw new Error('Not connected.')
    const response = await fetch(apiUrl(ctx.base, `/api/jobs/${encodeURIComponent(job.id)}/files/${encodeURIComponent(output.name)}`), {
      headers: { Authorization: `Bearer ${ctx.token}` }, signal: ctx.signal, cache: 'no-store',
    })
    if (!response.ok) throw new Error(`The file could not be loaded (${response.status}).`)
    return URL.createObjectURL(await response.blob())
  }

  async registerProfile(profile: NewProfile) {
    const ctx = this.context()
    if (!ctx || !this.fresh()) return false
    const { generation, signal, base, token } = ctx
    this.set({ catalogError: '', actionError: '' })
    try {
      await requestApi(base, token, '/api/profiles', { method: 'POST', body: JSON.stringify(profile) }, signal)
      await this.refreshCatalog()
      return true
    } catch (error) {
      if (!this.stillCurrent(generation, signal) || this.handleAuthError(error)) return false
      this.set({ actionError: error instanceof Error ? error.message : 'Could not register the simulation profile.' })
      return false
    }
  }

  async runLifecycle(model: Model, action: 'load' | 'unload', profile: ModelProfile) {
    const ctx = this.context()
    if (!ctx || !this.fresh()) return
    const { generation, signal, base, token } = ctx
    this.set((state) => {
      const refusals = { ...state.refusals }
      delete refusals[model.id]
      return { pendingModelId: model.id, actionError: '', refusals }
    })
    try {
      const accepted = await requestApi(base, token, `/api/models/${encodeURIComponent(model.id)}/${action}`, {
        method: 'POST', headers: { 'Idempotency-Key': idempotencyKey() },
        ...(action === 'load' ? { body: JSON.stringify({ profile_id: profile.id }) } : {}),
      }, signal) as Record<string, unknown>
      const operationId = typeof accepted.operation_id === 'string' ? accepted.operation_id : accepted.id
      if (typeof operationId !== 'string') throw new Error('The host did not return an operation ID.')
      let latest: Operation = {
        id: operationId, model_id: model.id, action, status: String(accepted.status ?? (action === 'load' ? 'loading' : 'unloading')),
        simulation: accepted.simulation === true, worker_type: String(accepted.worker_type ?? 'fake'),
      }
      if (!isOperation(latest)) throw new Error('The host returned a non-simulation lifecycle operation.')
      const save = (operation: Operation) => this.set((state) => ({ operations: [operation, ...state.operations.filter((item) => item.id !== operation.id)].slice(0, 8) }))
      save(latest)
      for (let attempt = 0; attempt < 60 && !isTerminalOperation(latest.status); attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 350))
        if (!this.stillCurrent(generation, signal)) return
        const result = await requestApi(base, token, `/api/operations/${encodeURIComponent(latest.id)}`, {}, signal)
        if (!isOperation(result)) throw new Error('The host returned an invalid operation status.')
        latest = result
        save(latest)
      }
      if (!isTerminalOperation(latest.status)) this.set({ actionError: 'The worker operation is still in progress. Its latest state is shown below.' })
      await this.refreshCatalog()
    } catch (error) {
      if (!this.stillCurrent(generation, signal) || this.handleAuthError(error)) return
      if (error instanceof ApiError && error.status === 409) {
        const value = isRefusal(error.body.detail) ? error.body.detail : isRefusal(error.body) ? error.body as Refusal : null
        if (value) this.set((state) => ({ refusals: { ...state.refusals, [model.id]: value } }))
        else this.set({ actionError: error.message })
      } else this.set({ actionError: error instanceof Error ? error.message : 'The host could not complete this operation.' })
    } finally {
      if (this.generation === generation) this.set({ pendingModelId: null })
    }
  }
}

function isByteMap(value: unknown): value is Record<string, number> {
  return !!value && typeof value === 'object' && Object.values(value).every((bytes) => typeof bytes === 'number' && Number.isFinite(bytes) && bytes >= 0)
}

function isEstimate(value: unknown): value is RuntimeEstimate {
  if (!value || typeof value !== 'object') return false
  const estimate = value as Record<string, unknown>
  const bytes = (key: string) => typeof estimate[key] === 'number' && Number.isFinite(estimate[key]) && (estimate[key] as number) >= 0
  return ['ram_bytes', 'ram_headroom_bytes', 'gpu_headroom_bytes', 'reserved_ram_bytes'].every(bytes)
    && isByteMap(estimate.gpu_vram_bytes_by_id) && isByteMap(estimate.reserved_gpu_vram_bytes_by_id)
}
