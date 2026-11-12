import { expect, test, type Page, type Route } from '@playwright/test'

const token = 'test-token-with-enough-length-for-fixture-only'
const gpuUuid = 'GPU-5b5f7f4e-0000-0000-0000-000000000000'
const profileUuid = '11111111-2222-4333-8444-555555555555'

function fixtureHost(label = 'Fixture desktop', stale = false, instance = 'fixture-instance') {
  return {
    instance_id: instance,
    host: { hostname: label.toLowerCase().replaceAll(' ', '-'), os: 'Windows', label, role: 'desktop', scope: 'host' },
    ram: { total_bytes: 32 * 1024 ** 3, available_bytes: 20 * 1024 ** 3, used_bytes: 12 * 1024 ** 3 },
    ram_error: null,
    gpus: [{ id: gpuUuid, index: 0, name: 'Fixture GPU', memory: { total_bytes: 32 * 1024 ** 3, available_bytes: 28 * 1024 ** 3, used_bytes: 4 * 1024 ** 3 }, error: null }],
    gpu_error: null,
    observed_at: '2026-10-08T00:00:00+00:00', sequence: 1, age_seconds: 0,
    stale, stale_after_seconds: 2, status: stale ? 'stale' : 'live', loading_enabled: !stale,
    loading_reason: stale ? 'A fresh host sample is required.' : 'The desktop host has fresh telemetry.',
  }
}

function profileRecord(modelId = 'fixture-model') {
  return { id: profileUuid, model_id: modelId, name: 'Fixture model', workload: 'browser fixture', ram_peak_bytes: 4 * 1024 ** 3, gpu_vram_bytes_by_id: { [gpuUuid]: 2 * 1024 ** 3 }, mode: 'simulation', revision: 1 }
}

function modelRecord(profile: ReturnType<typeof profileRecord>, state = 'unloaded') {
  return { id: profile.model_id, name: profile.name, workload: profile.workload, state, loading_enabled: ['unloaded', 'error'].includes(state), loading_reason: 'Fresh desktop telemetry is available.', profile: { id: profile.id, revision: profile.revision } }
}

function runtimeFixture() {
  const setting = (key: string, label: string, kind: string, value: unknown, extra: Record<string, unknown> = {}) => ({
    key, label, kind, default: value, minimum: null, maximum: null, unit: null, help: `${label} help`, options: null, ...extra,
  })
  const gpus = [{ index: 0, name: 'Fixture GPU' }, { index: 1, name: 'Second GPU' }]
  return {
    id: 'basalt', kind: 'basalt', plugin: 'Basalt', name: 'Basalt', workload: 'text', port: 8160, default_preset: 'ds41', last_launch: null,
    presets: {
      ds41: { name: 'DeepSeek V4.1 Flash', gpus: [0, 1], allowed_gpus: gpus, estimate: { ram_gib: 16, gpu_min_free_gib: { 0: 24, 1: 10 } }, settings: [
        setting('vram_reserve_mib', 'VRAM left free on the main card', 'int', 700, { minimum: 256, maximum: 32768, unit: 'MiB' }),
        setting('resident_budget_gib', 'RAM for overflow experts', 'optional_int', 48, { minimum: 1, maximum: 1024, unit: 'GiB' }),
        setting('ram_reserve_mib', 'RAM left for Windows', 'int', 0, { minimum: 0, maximum: 262144, unit: 'MiB' }),
      ] },
      fn: { name: 'Qwen3.8 Flash-Next', gpus: [0, 1], allowed_gpus: gpus, estimate: { ram_gib: 40, gpu_min_free_gib: { 0: 24, 1: 10 } }, settings: [
        setting('kv', 'KV cache precision', 'choice', 'int8', { options: ['int8', 'q4_0'] }),
        setting('vram_reserve_mib', 'VRAM left free on the main card', 'int', 700, { minimum: 256, maximum: 32768, unit: 'MiB' }),
        setting('resident_experts', 'Keep overflow experts in RAM', 'bool', true),
      ] },
    },
  }
}

function songRuntimeFixture() {
  const field = (key: string, label: string, kind: string, extra: Record<string, unknown> = {}) => ({
    key, label, kind, required: false, default: null, minimum: null, maximum: null, max_length: null, options: [], placeholder: null, help: `${label} help`, advanced: false, ...extra,
  })
  return {
    id: 'yue2', kind: 'yue2', plugin: 'YuE2', name: 'YuE2 songs', workload: 'music', port: 8170, default_preset: 'songs', last_launch: null, max_gpus: 1,
    presets: { songs: { name: 'YuE2 3B', gpus: [1], allowed_gpus: [{ index: 0, name: 'Fixture GPU' }, { index: 1, name: 'Second GPU' }], estimate: { ram_gib: 24, gpu_min_free_gib: { 0: 14, 1: 14 } }, settings: [] } },
    generation: { output_kind: 'audio', inputs: [
      field('style', 'Style', 'text', { required: true, max_length: 400, placeholder: 'Upbeat indie pop' }),
      field('lyrics', 'Lyrics', 'textarea', { required: true, max_length: 8000 }),
      field('mode', 'Melody planning', 'choice', { options: ['full', 'melody', 'off'], default: 'full', advanced: true }),
      field('seed', 'Seed', 'seed', { minimum: 0, maximum: 2147483647, advanced: true }),
    ] },
  }
}

async function installM2Api(page: Page, options: { initialProfile?: boolean; refuseLoad?: boolean; initialState?: string; runtime?: boolean; refuseStart?: boolean; songs?: boolean } = {}) {
  const profiles = options.initialProfile ? [profileRecord()] : []
  const models: Array<Record<string, unknown>> = options.initialProfile ? [modelRecord(profiles[0], options.initialState ?? 'unloaded')] : []
  if (options.runtime) models.push({ id: 'basalt', name: 'Basalt', workload: 'text', state: 'unloaded', loading_enabled: false, profile: { id: null, revision: null } })
  const operations: Array<Record<string, unknown>> = []
  let rejected = !!options.refuseLoad
  let refuseStart = !!options.refuseStart
  let postProfileBody: Record<string, unknown> | null = null
  let loadProfileId: unknown = null
  let startBody: Record<string, unknown> | null = null
  await page.route('**/api/runtimes', (route) => route.fulfill({ json: { runtimes: options.runtime ? [runtimeFixture()] : options.songs ? [songRuntimeFixture()] : [] } }))
  if (options.songs) models.push({ id: 'yue2', name: 'YuE2 songs', workload: 'music', state: 'ready', loading_enabled: false, profile: { id: null, revision: null } })
  const jobs: Array<Record<string, unknown>> = []
  let jobBody: Record<string, unknown> | null = null
  await page.route('**/api/jobs?limit=20', (route) => route.fulfill({ json: { jobs } }))
  await page.route('**/api/models/*/jobs', async (route) => {
    jobBody = route.request().postDataJSON() as Record<string, unknown>
    const job = { id: 'job-00000001', model_id: 'yue2', inputs: { mode: 'full', ...(jobBody.inputs as object) }, status: 'queued', progress: null, outputs: [], error_message: null, created_at: '2026-11-12T00:00:00Z', finished_at: null }
    jobs.unshift(job)
    await route.fulfill({ status: 202, json: job })
  })
  await page.route('**/api/jobs/job-00000001', async (route) => {
    const job = jobs[0]
    if (job.status === 'queued') Object.assign(job, { status: 'running', progress: 'Composing the song' })
    else Object.assign(job, { status: 'done', progress: 'Done: 1 seconds, seed 42', outputs: [{ name: 'song.wav', mime: 'audio/wav', bytes: 44 }], finished_at: '2026-11-12T00:01:00Z' })
    await route.fulfill({ json: job })
  })
  await page.route('**/api/jobs/job-00000001/files/song.wav', (route) => route.fulfill({ status: 200, contentType: 'audio/wav', body: Buffer.alloc(44) }))
  await page.route('**/api/runtimes/*/start', async (route) => {
    startBody = route.request().postDataJSON() as Record<string, unknown>
    if (refuseStart) {
      refuseStart = false
      await route.fulfill({ status: 409, json: { detail: { code: 'INSUFFICIENT_VRAM', message: 'The requested model exceeds available VRAM on one or more assigned GPUs.', operation_id: 'refused-1', resources: [{ resource: `gpu:${gpuUuid}`, required_bytes: 24 * 1024 ** 3, available_bytes: 10 * 1024 ** 3, headroom_bytes: 2 * 1024 ** 3 }] } } })
      return
    }
    const operation = { id: 'operation-start-1', model_id: 'basalt', action: 'load', status: 'loading', simulation: false, worker_type: 'runtime', launch: startBody }
    operations.unshift(operation)
    const model = models.find((item) => item.id === 'basalt')
    if (model) model.state = 'loading'
    await route.fulfill({ status: 202, json: operation })
  })
  await page.route('**/api/models', (route) => route.fulfill({ json: { models } }))
  await page.route('**/api/profiles', async (route) => {
    if (route.request().method() === 'GET') { await route.fulfill({ json: { profiles } }); return }
    postProfileBody = route.request().postDataJSON()
    const body = postProfileBody as Record<string, unknown>
    const created = { id: profileUuid, model_id: body.id, name: body.name, workload: body.workload,
      ram_peak_bytes: body.ram_peak_bytes, gpu_vram_bytes_by_id: body.gpu_vram_bytes_by_id,
      mode: body.mode, revision: 1 }
    profiles.push(created as ReturnType<typeof profileRecord>)
    models.push(modelRecord(created as ReturnType<typeof profileRecord>))
    await route.fulfill({ status: 201, json: { profile: created } })
  })
  await page.route('**/api/operations?limit=100', (route) => route.fulfill({ json: { operations } }))
  await page.route('**/api/operations/*', async (route) => {
    const id = route.request().url().split('/').pop() ?? ''
    const operation = operations.find((item) => item.id === id)
    if (!operation) { await route.fulfill({ status: 404, json: { detail: 'Operation not found.' } }); return }
    if (operation.action === 'load' && operation.status === 'loading') {
      operation.status = operation.simulation === false ? 'ready' : 'simulation_ready'
      const model = models.find((item) => item.id === operation.model_id)
      if (model) { model.state = operation.status; model.loading_enabled = false }
    } else if (operation.action === 'unload' && operation.status === 'unloading') {
      operation.status = 'unloaded'
      const model = models.find((item) => item.id === operation.model_id)
      if (model) { model.state = 'unloaded'; model.loading_enabled = true }
    }
    await route.fulfill({ json: operation })
  })
  await page.route('**/api/models/*/load', async (route) => {
    const body = route.request().postDataJSON() as Record<string, unknown>
    loadProfileId = body.profile_id
    if (rejected) {
      await route.fulfill({ status: 409, json: { detail: { code: 'INSUFFICIENT_VRAM', message: 'This profile exceeds currently available GPU memory.', resources: [{ resource: `gpu:${gpuUuid}`, required_bytes: 6 * 1024 ** 3, available_bytes: 3 * 1024 ** 3, headroom_bytes: 2 * 1024 ** 3 }] } } })
      rejected = false
      return
    }
    const operation = { id: 'operation-load-1', model_id: 'fixture-model', profile_id: body.profile_id, profile_revision: 1, action: 'load', status: 'loading', simulation: true, worker_type: 'fake' }
    operations.unshift(operation)
    await route.fulfill({ status: 202, json: operation })
  })
  await page.route('**/api/models/*/unload', async (route) => {
    const runtime = route.request().url().includes('/api/models/basalt/')
    const operation = runtime
      ? { id: 'operation-stop-1', model_id: 'basalt', action: 'unload', status: 'unloading', simulation: false, worker_type: 'runtime' }
      : { id: 'operation-unload-1', model_id: 'fixture-model', profile_id: profileUuid, profile_revision: 1, action: 'unload', status: 'unloading', simulation: true, worker_type: 'fake' }
    operations.unshift(operation)
    const model = models.find((item) => item.id === operation.model_id)
    if (model && runtime) model.state = 'unloading'
    await route.fulfill({ status: 202, json: operation })
  })
  return { profiles, models, operations, get postProfileBody() { return postProfileBody }, get loadProfileId() { return loadProfileId }, get startBody() { return startBody }, get jobBody() { return jobBody } }
}

async function installSseMock(page: Page) {
  await page.addInitScript(() => {
    const scope = window as Window & { __gsStreamCount?: number; __gsStreams?: Array<{ controller: ReadableStreamDefaultController<Uint8Array>; active: boolean }> }
    const streams: Array<{ controller: ReadableStreamDefaultController<Uint8Array>; active: boolean }> = []
    scope.__gsStreams = streams
    scope.__gsStreamCount = 0
    window.addEventListener('gs:push-frame', (event) => {
      const detail = (event as CustomEvent<string>).detail
      const latest = streams.at(-1)
      if (!latest?.active) return
      latest.controller.enqueue(new TextEncoder().encode(`event: host\r\ndata: ${detail}\r\n\r\n`))
    })
    window.addEventListener('gs:close-stream', () => {
      const latest = streams.at(-1)
      if (latest?.active) { latest.active = false; latest.controller.close() }
    })
    const originalFetch = window.fetch.bind(window)
    window.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
      if (url.endsWith('/api/events')) {
        scope.__gsStreamCount = (scope.__gsStreamCount ?? 0) + 1
        const entry: { controller: ReadableStreamDefaultController<Uint8Array>; active: boolean } = { controller: null as unknown as ReadableStreamDefaultController<Uint8Array>, active: true }
        const body = new ReadableStream<Uint8Array>({
          start(controller) { entry.controller = controller; streams.push(entry) },
          cancel() { entry.active = false },
        })
        return new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
      }
      return originalFetch(input, init)
    }) as typeof window.fetch
  })
}

async function pushFrame(page: Page, value: unknown) {
  return page.evaluate((data) => {
    const entries = (window as Window & { __gsStreams?: Array<{ active: boolean }> }).__gsStreams ?? []
    if (!entries.at(-1)?.active) return false
    window.dispatchEvent(new CustomEvent('gs:push-frame', { detail: JSON.stringify(data) }))
    return true
  }, value)
}

async function streamCount(page: Page) {
  return page.evaluate(() => (window as Window & { __gsStreamCount?: number }).__gsStreamCount ?? 0)
}


const REJECTED = 'The access token was rejected. Check it on the Connections page.'

async function go(page: Page, hash: string) {
  await page.evaluate((value) => { window.location.hash = value }, hash)
}

async function signIn(page: Page, value = token, address?: string) {
  await page.goto('/#/connections')
  if (address !== undefined) await page.getByLabel('Server address').fill(address)
  await page.getByLabel('Access token').fill(value)
  await page.getByRole('button', { name: 'Save and connect' }).click()
}

async function connectFixtures(page: Page, label = 'Fixture desktop', stale = false, options: { initialProfile?: boolean; refuseLoad?: boolean; initialState?: string; runtime?: boolean; refuseStart?: boolean; songs?: boolean } = {}) {
  await installSseMock(page)
  const api = await installM2Api(page, options)
  const host = fixtureHost(label, stale)
  await page.route('**/api/host', async (route: Route) => {
    if (route.request().headers().authorization !== `Bearer ${token}`) {
      await route.fulfill({ status: 401, json: { detail: 'Unauthorized' } })
      return
    }
    await route.fulfill({ json: host })
  })
  await signIn(page)
  await expect.poll(() => streamCount(page)).toBe(1)
  await expect.poll(() => pushFrame(page, host)).toBe(true)
  return api
}

/** Stream fresh samples the way the real host does, for tests that span several polls. */
async function keepFresh(page: Page) {
  await page.evaluate((data) => {
    window.setInterval(() => window.dispatchEvent(new CustomEvent('gs:push-frame', { detail: JSON.stringify(data) })), 500)
  }, fixtureHost())
}

test('shows an honest disconnected screen on desktop and narrow mobile', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1050 })
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Overview', level: 1 })).toBeVisible()
  await expect(page.getByText('This computer').first()).toBeVisible()
  await expect(page.getByRole('main').getByText('Not connected', { exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: /Open Connections/ })).toBeVisible()
  await expect(page.getByText('No registered profiles')).toHaveCount(0)
  await page.screenshot({ path: 'test-results/screenshots/disconnected-desktop.png', fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.getByRole('heading', { name: 'Overview', level: 1 })).toBeVisible()
  await page.screenshot({ path: 'test-results/screenshots/disconnected-mobile.png', fullPage: true })
})

test('connects from the Connections page, remembers the host on this device, and shows it on the Overview', async ({ page }) => {
  await connectFixtures(page, 'Fixture desktop', false, { runtime: true })
  await expect(page.getByText('Live telemetry is streaming from the host.')).toBeVisible()
  const saved = await page.evaluate(() => JSON.parse(localStorage.getItem('generation-station.hosts') ?? '[]'))
  expect(saved).toEqual([{ id: 'local', label: '', url: '', token }])
  expect(page.url()).not.toContain(token)
  await page.getByRole('link', { name: 'Overview' }).click()
  await expect(page.getByLabel('Fixture desktop resource usage')).toBeVisible()
  await expect(page.getByText('12 GiB')).toBeVisible()
  await expect(page.getByText('32 GiB').first()).toBeVisible()
  await expect(page.getByText('4 GiB')).toBeVisible()
  await expect(page.getByLabel('Fixture desktop services').getByText('Basalt')).toBeVisible()
  const nav = page.getByRole('navigation', { name: 'Main navigation' })
  await expect(nav.getByText('FIXTURE DESKTOP')).toBeVisible()
  await nav.getByRole('link', { name: /Basalt/ }).click()
  await expect(page.getByRole('heading', { name: 'Basalt', level: 1 })).toBeVisible()
  await expect(page).toHaveURL(/#\/hosts\/local\/services\/basalt$/)
  await page.screenshot({ path: 'test-results/screenshots/service-page.png', fullPage: true })
})

test('reconnects saved hosts on the next visit without asking for the token again', async ({ page }) => {
  await connectFixtures(page)
  await page.reload()
  await expect.poll(() => streamCount(page)).toBe(1)
  await expect.poll(() => pushFrame(page, fixtureHost())).toBe(true)
  await page.goto('/#/connections')
  await expect(page.getByRole('button', { name: 'Disconnect' })).toBeVisible()
  await expect(page.getByLabel('Access token')).toHaveCount(0)
})

test('adds a second host and keeps both in the sidebar; forgetting one removes it and its token', async ({ page }) => {
  await connectFixtures(page)
  await page.getByRole('button', { name: 'Add host' }).click()
  await page.getByLabel('Host name').fill('Proxmox')
  await page.getByLabel('Server address').fill('http://proxmox.test:8000')
  await page.getByLabel('Access token').last().fill('second-host-token-with-enough-length-0000')
  await page.getByRole('button', { name: 'Save and connect' }).click()
  const nav = page.getByRole('navigation', { name: 'Main navigation' })
  await expect(nav.getByText('PROXMOX')).toBeVisible()
  await expect(nav.getByText('FIXTURE DESKTOP')).toBeVisible()
  const card = page.getByLabel('Host Proxmox')
  await card.getByRole('button', { name: 'Forget' }).click()
  await card.getByRole('button', { name: 'Forget it' }).click()
  await expect(nav.getByText('PROXMOX')).toHaveCount(0)
  const saved = await page.evaluate(() => localStorage.getItem('generation-station.hosts') ?? '')
  expect(saved).not.toContain('second-host-token')
})

test('registers an explicit profile and binds VRAM to the selected reported UUID', async ({ page }) => {
  const api = await connectFixtures(page)
  await go(page, '#/hosts/local/profiles')
  await expect(page.getByText('No registered profiles')).toBeVisible()
  await page.getByRole('button', { name: 'Register profile' }).click()
  await expect(page.getByRole('form', { name: 'Register simulation model profile' })).toBeVisible()
  await page.getByLabel('PROFILE ID').fill('my-fixture-profile')
  await page.getByLabel('MODEL NAME').fill('A model label')
  await page.getByLabel('WORKLOAD').fill('a workload chosen by the user')
  await page.getByLabel('PEAK SYSTEM RAM (GiB)').fill('6.5')
  await page.getByRole('button', { name: 'Add GPU requirement' }).click()
  await page.getByLabel('GPU device 1').selectOption(gpuUuid)
  await page.getByLabel('Peak VRAM GiB for GPU 1').fill('4')
  await page.getByRole('button', { name: 'Register simulation profile' }).click()
  await expect(page.getByText('A model label')).toBeVisible()
  expect(api.postProfileBody).toMatchObject({ id: 'my-fixture-profile', name: 'A model label', workload: 'a workload chosen by the user', mode: 'simulation', ram_peak_bytes: 6.5 * 1024 ** 3, gpu_vram_bytes_by_id: { [gpuUuid]: 4 * 1024 ** 3 } })
  await expect(page.getByText('Fake worker · no inference')).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.getByRole('button', { name: 'Load simulation' })).toBeEnabled()
  await page.screenshot({ path: 'test-results/screenshots/fixture-profile-mobile.png', fullPage: true })
})

test('loads by capacity-approved request, polls simulation-ready, and unloads the fake worker', async ({ page }) => {
  const api = await connectFixtures(page, 'Fixture desktop', false, { initialProfile: true })
  await go(page, '#/hosts/local/profiles')
  await page.getByRole('button', { name: 'Load simulation' }).click()
  expect(api.loadProfileId).toBe(profileUuid)
  await expect(page.getByText('Load simulation · simulation ready')).toBeVisible()
  await page.getByRole('button', { name: 'Unload simulation' }).click()
  await expect(page.getByText('Unload simulation · unloaded')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Load simulation' })).toBeEnabled()
})

test('renders server-side capacity refusal code and per-resource requirement details', async ({ page }) => {
  await connectFixtures(page, 'Fixture desktop', false, { initialProfile: true, refuseLoad: true })
  await go(page, '#/hosts/local/profiles')
  await page.getByRole('button', { name: 'Load simulation' }).click()
  await expect(page.getByText('INSUFFICIENT_VRAM')).toBeVisible()
  await expect(page.getByText('Required 6 GiB')).toBeVisible()
  await expect(page.getByText('Available 3 GiB')).toBeVisible()
  await expect(page.getByText('Headroom 2 GiB')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Load simulation' })).toBeEnabled()
})

test('allows retry after a fully cleaned-up worker error state', async ({ page }) => {
  await connectFixtures(page, 'Fixture desktop', false, { initialProfile: true, initialState: 'error' })
  await go(page, '#/hosts/local/profiles')
  await expect(page.getByText('Worker error')).toBeVisible()
  await page.getByRole('button', { name: 'Retry simulation' }).click()
  await expect(page.getByText('Load simulation · simulation ready')).toBeVisible()
})

test('marks stale telemetry, blocks actions, and clears measurements on disconnect', async ({ page }) => {
  await connectFixtures(page, 'Fixture desktop', true, { initialProfile: true })
  await expect(page.getByText('Telemetry stale')).toBeVisible()
  await go(page, '#/hosts/local/profiles')
  await expect(page.getByRole('button', { name: 'Load simulation' })).toBeDisabled()
  await go(page, '#/overview')
  await expect(page.getByText('Last known measurement').first()).toBeVisible()
  await go(page, '#/connections')
  await page.getByRole('button', { name: 'Disconnect' }).click()
  await expect(page.getByText('Disconnected.', { exact: true })).toBeVisible()
  await go(page, '#/overview')
  await expect(page.getByText('Fixture desktop')).toHaveCount(0)
  await expect(page.getByText('Last known measurement')).toHaveCount(0)
})

test('marks fresh partial GPU telemetry clearly and shows the reported device error', async ({ page }) => {
  const host = fixtureHost('Partial telemetry desktop')
  host.status = 'degraded'
  host.gpu_error = 'NVML telemetry is unavailable.'
  host.loading_enabled = false
  host.gpus = [{ id: gpuUuid, index: 0, name: 'Fixture GPU', memory: null, error: 'Driver did not expose memory counters.' }]
  await installSseMock(page)
  await installM2Api(page)
  await page.route('**/api/host', (route) => route.fulfill({ json: host }))
  await signIn(page)
  await expect.poll(() => streamCount(page)).toBe(1)
  await expect.poll(() => pushFrame(page, host)).toBe(true)
  await expect(page.getByText('Live · partial telemetry')).toBeVisible()
  await go(page, '#/overview')
  await expect(page.getByText('PARTIAL').first()).toBeVisible()
  await expect(page.getByText('Driver did not expose memory counters.')).toBeVisible()
})

test('rejects invalid access tokens without opening the event stream', async ({ page }) => {
  let eventCalls = 0
  await page.route('**/api/host', (route) => route.fulfill({ status: 401, json: { detail: 'Unauthorized' } }))
  await page.route('**/api/events', async (route) => { eventCalls += 1; await route.fulfill({ status: 401 }) })
  await signIn(page, 'wrong-token')
  await expect(page.getByText(REJECTED)).toBeVisible()
  expect(eventCalls).toBe(0)
})

test('editing a host address drops the old host data and connects to the new address', async ({ page }) => {
  await installSseMock(page)
  await installM2Api(page)
  await page.route('**/api/host', async (route) => {
    const label = route.request().url().includes('two.test') ? 'Second desktop' : 'First desktop'
    await route.fulfill({ json: fixtureHost(label, false, label) })
  })
  await signIn(page, token, 'http://one.test:8100')
  await expect.poll(() => streamCount(page)).toBe(1)
  await expect.poll(() => pushFrame(page, fixtureHost('First desktop', false, 'First desktop'))).toBe(true)
  await expect(page.getByText('First desktop').first()).toBeVisible()
  await page.getByRole('button', { name: 'Edit' }).click()
  await page.getByLabel('Server address').fill('http://two.test:8100')
  await page.getByRole('button', { name: 'Save and connect' }).click()
  await expect(page.getByText('First desktop')).toHaveCount(0)
  await expect.poll(() => streamCount(page)).toBe(2)
  await expect.poll(() => pushFrame(page, fixtureHost('Second desktop', false, 'Second desktop'))).toBe(true)
  await expect(page.getByText('Second desktop').first()).toBeVisible()
  const saved = await page.evaluate(() => JSON.parse(localStorage.getItem('generation-station.hosts') ?? '[]'))
  expect(saved[0].url).toBe('http://two.test:8100')
  expect(page.url()).not.toContain(token)
})

test('reconnects after a stream outage longer than the watchdog and accepts the new sample', async ({ page }) => {
  const initial = fixtureHost('Initial desktop')
  const recovered = { ...fixtureHost('Recovered desktop', false, 'new-service-instance'), sequence: 2,
    ram: { total_bytes: 32 * 1024 ** 3, available_bytes: 15 * 1024 ** 3, used_bytes: 17 * 1024 ** 3 } }
  await installSseMock(page)
  await installM2Api(page)
  await page.route('**/api/host', (route) => route.fulfill({ json: initial }))
  await signIn(page)
  await expect.poll(() => streamCount(page)).toBe(1)
  await go(page, '#/overview')
  await expect(page.getByText('STALE').first()).toBeVisible({ timeout: 5000 })
  await expect.poll(() => streamCount(page), { timeout: 20_000 }).toBeGreaterThanOrEqual(2)
  await expect.poll(() => pushFrame(page, recovered)).toBe(true)
  await expect(page.getByText('Recovered desktop').first()).toBeVisible()
  await expect(page.getByText('17 GiB')).toBeVisible()
})

test('starts a model server with the chosen model, GPUs and advanced settings, then stops it', async ({ page }) => {
  const api = await connectFixtures(page, 'Fixture desktop', false, { runtime: true })
  await keepFresh(page)
  await go(page, '#/hosts/local/services/basalt')
  await expect(page.getByRole('heading', { name: 'Basalt', level: 1 })).toBeVisible()
  await expect(page.getByText('Stopped', { exact: true })).toBeVisible()
  await page.getByRole('radio', { name: 'Qwen3.8 Flash-Next' }).check()
  await page.getByRole('checkbox', { name: 'Second GPU' }).uncheck()
  await expect(page.getByText(/Needs about 24 GiB free on the Fixture GPU and 40 GiB of RAM/)).toBeVisible()
  await page.getByRole('button', { name: 'Advanced settings' }).click()
  await page.getByLabel(/VRAM LEFT FREE ON THE MAIN CARD/).fill('1024')
  await page.getByLabel(/KV CACHE PRECISION/).selectOption('q4_0')
  await page.getByLabel(/KEEP OVERFLOW EXPERTS IN RAM/).uncheck()
  await page.screenshot({ path: 'test-results/screenshots/model-server-advanced.png', fullPage: true })
  await page.getByRole('button', { name: 'Start', exact: true }).click()
  await expect(page.getByText('Ready.')).toBeVisible()
  expect(api.startBody).toEqual({ preset: 'fn', gpus: [0], settings: { kv: 'q4_0', vram_reserve_mib: 1024, resident_experts: false } })
  await expect(page.getByText('Running', { exact: true })).toBeVisible()
  await expect(page.getByText('Start · ready')).toBeVisible()
  await expect(page.getByRole('navigation', { name: 'Main navigation' }).getByRole('link', { name: /Basalt/ })).toContainText('on')
  await page.getByRole('button', { name: 'Stop', exact: true }).click()
  await expect(page.getByText('Stopped.', { exact: true })).toBeVisible()
  await expect(page.getByText('Stop · unloaded')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Start', exact: true })).toBeEnabled()
})

test('blocks a start until advanced settings and GPU choice are valid, and warns about the RAM guard', async ({ page }) => {
  const api = await connectFixtures(page, 'Fixture desktop', false, { runtime: true })
  await go(page, '#/hosts/local/services/basalt')
  await page.getByRole('button', { name: 'Advanced settings' }).click()
  await expect(page.getByText(/The RAM guard is off/)).toBeVisible()
  await page.getByLabel(/VRAM LEFT FREE ON THE MAIN CARD/).fill('100')
  await expect(page.getByText('At least 256.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Start', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: 'Reset to defaults' }).click()
  await expect(page.getByRole('button', { name: 'Start', exact: true })).toBeEnabled()
  await page.getByRole('checkbox', { name: 'Fixture GPU' }).uncheck()
  await page.getByRole('checkbox', { name: 'Second GPU' }).uncheck()
  await expect(page.getByText('Choose at least one GPU.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Start', exact: true })).toBeDisabled()
  expect(api.startBody).toBeNull()
})

test('shows a model server capacity refusal with the GPU name instead of its UUID', async ({ page }) => {
  await connectFixtures(page, 'Fixture desktop', false, { runtime: true, refuseStart: true })
  await go(page, '#/hosts/local/services/basalt')
  await page.getByRole('button', { name: 'Start', exact: true }).click()
  const refusal = page.getByRole('alert').filter({ hasText: 'INSUFFICIENT_VRAM' })
  await expect(refusal).toBeVisible()
  await expect(refusal.getByText('Fixture GPU')).toBeVisible()
  await expect(refusal.getByText('Required 24 GiB')).toBeVisible()
  await expect(page.getByText(gpuUuid)).toHaveCount(0)
})

test('makes a song from lyrics and style, shows progress, then plays and offers the file', async ({ page }) => {
  const api = await connectFixtures(page, 'Fixture desktop', false, { songs: true })
  await go(page, '#/hosts/local/services/yue2')
  await expect(page.getByText('Running', { exact: true })).toBeVisible()
  await expect(page.getByRole('radio', { name: 'Second GPU' })).toBeChecked()
  const form = page.getByRole('form', { name: 'Make a song' })
  await expect(form.getByRole('button', { name: 'Make a song' })).toBeDisabled()
  await form.getByLabel(/^STYLE/).fill('Upbeat indie pop, female vocals')
  await form.getByLabel(/^LYRICS/).fill('[Verse]\nSunlight on the kitchen floor\n\n[Chorus]\nSing it back to me')
  await form.getByRole('button', { name: 'More options' }).click()
  await form.getByLabel(/^SEED/).fill('42')
  await page.screenshot({ path: 'test-results/screenshots/make-a-song.png', fullPage: true })
  await form.getByRole('button', { name: 'Make a song' }).click()
  await expect(page.getByText('Waiting its turn').or(page.getByText('Composing the song'))).toBeVisible()
  expect(api.jobBody).toEqual({ inputs: { style: 'Upbeat indie pop, female vocals', lyrics: '[Verse]\nSunlight on the kitchen floor\n\n[Chorus]\nSing it back to me', mode: 'full', seed: 42 } })
  await expect(page.getByText('Done: 1 seconds, seed 42')).toBeVisible({ timeout: 15_000 })
  await expect(page.getByLabel('Play Upbeat indie pop, female vocals')).toBeVisible()
  await expect(page.getByRole('link', { name: 'Download song.wav' })).toBeVisible()
  await go(page, '#/overview')
  await expect(page.getByText('RECENT RESULTS')).toBeVisible()
})
