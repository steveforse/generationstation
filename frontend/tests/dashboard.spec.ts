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

async function installM2Api(page: Page, options: { initialProfile?: boolean; refuseLoad?: boolean; initialState?: string; runtime?: boolean; refuseStart?: boolean } = {}) {
  const profiles = options.initialProfile ? [profileRecord()] : []
  const models: Array<Record<string, unknown>> = options.initialProfile ? [modelRecord(profiles[0], options.initialState ?? 'unloaded')] : []
  if (options.runtime) models.push({ id: 'basalt', name: 'Basalt', workload: 'text', state: 'unloaded', loading_enabled: false, profile: { id: null, revision: null } })
  const operations: Array<Record<string, unknown>> = []
  let rejected = !!options.refuseLoad
  let refuseStart = !!options.refuseStart
  let postProfileBody: Record<string, unknown> | null = null
  let loadProfileId: unknown = null
  let startBody: Record<string, unknown> | null = null
  await page.route('**/api/runtimes', (route) => route.fulfill({ json: { runtimes: options.runtime ? [runtimeFixture()] : [] } }))
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
  return { profiles, models, operations, get postProfileBody() { return postProfileBody }, get loadProfileId() { return loadProfileId }, get startBody() { return startBody } }
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

async function connectFixtures(page: Page, label = 'Fixture desktop', stale = false, options: { initialProfile?: boolean; refuseLoad?: boolean; initialState?: string; runtime?: boolean; refuseStart?: boolean } = {}) {
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
  await page.goto('/')
  await page.getByLabel('Access token').fill(token)
  await page.getByRole('button', { name: 'Connect to host' }).click()
  await expect.poll(() => streamCount(page)).toBe(1)
  await expect.poll(() => pushFrame(page, host)).toBe(true)
  return api
}

test('shows an honest disconnected screen on desktop and narrow mobile', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1050 })
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'System overview' })).toBeVisible()
  await expect(page.getByText('No host selected')).toBeVisible()
  await expect(page.getByText('Connect to view measurements')).toHaveCount(2)
  await expect(page.getByText('No registered profiles')).toHaveCount(0)
  await page.screenshot({ path: 'test-results/screenshots/disconnected-desktop.png', fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.getByRole('heading', { name: 'System overview' })).toBeVisible()
  await expect(page.getByLabel('Resource usage')).toBeVisible()
  await page.screenshot({ path: 'test-results/screenshots/disconnected-mobile.png', fullPage: true })
})

test('authenticates, renders measured host values, and leaves the profile catalog empty without inventing entries', async ({ page }) => {
  await connectFixtures(page)
  await expect(page.getByText('Fixture desktop')).toBeVisible()
  await expect(page.getByText('12 GiB')).toBeVisible()
  await expect(page.getByText('32 GiB').first()).toBeVisible()
  await expect(page.getByText('4 GiB')).toBeVisible()
  await expect(page.getByText('No registered profiles')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Register profile' })).toBeEnabled()
  await expect(page.getByText('Live telemetry is streaming from the host.')).toBeVisible()
  expect(await page.evaluate(() => localStorage.getItem('generation-station.server-url'))).toBe('')
  expect(await page.evaluate(() => Object.keys(localStorage).some((key) => /token/i.test(key)))).toBe(false)
})

test('registers an explicit profile and binds VRAM to the selected reported UUID', async ({ page }) => {
  const api = await connectFixtures(page)
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
  await expect(page.getByText('No model weights or outputs are used.')).toBeVisible()
  await page.screenshot({ path: 'test-results/screenshots/fixture-profile-desktop.png', fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.getByRole('button', { name: 'Load simulation' })).toBeEnabled()
  await page.screenshot({ path: 'test-results/screenshots/fixture-profile-mobile.png', fullPage: true })
})

test('loads by capacity-approved request, polls simulation-ready, and unloads the fake worker', async ({ page }) => {
  const api = await connectFixtures(page, 'Fixture desktop', false, { initialProfile: true })
  await expect(page.getByRole('button', { name: 'Load simulation' })).toBeEnabled()
  await page.getByRole('button', { name: 'Load simulation' }).click()
  expect(api.loadProfileId).toBe(profileUuid)
  await expect(page.getByText('Load simulation · simulation ready')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Unload simulation' })).toBeEnabled()
  await page.getByRole('button', { name: 'Unload simulation' }).click()
  await expect(page.getByText('Unload simulation · unloaded')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Load simulation' })).toBeEnabled()
})

test('renders server-side capacity refusal code and per-resource requirement details', async ({ page }) => {
  await connectFixtures(page, 'Fixture desktop', false, { initialProfile: true, refuseLoad: true })
  await page.getByRole('button', { name: 'Load simulation' }).click()
  await expect(page.getByText('INSUFFICIENT_VRAM')).toBeVisible()
  await expect(page.getByText('Required 6 GiB')).toBeVisible()
  await expect(page.getByText('Available 3 GiB')).toBeVisible()
  await expect(page.getByText('Headroom 2 GiB')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Load simulation' })).toBeEnabled()
})

test('allows retry after a fully cleaned-up worker error state', async ({ page }) => {
  await connectFixtures(page, 'Fixture desktop', false, { initialProfile: true, initialState: 'error' })
  await expect(page.getByText('Worker error')).toBeVisible()
  await page.getByRole('button', { name: 'Retry simulation' }).click()
  await expect(page.getByText('Load simulation · simulation ready')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Unload simulation' })).toBeEnabled()
})

test('clears old measurements on disconnect and marks telemetry stale', async ({ page }) => {
  await connectFixtures(page, 'Fixture desktop', true, { initialProfile: true })
  await expect(page.getByText('Telemetry stale')).toBeVisible()
  await expect(page.getByText('Last known measurement').first()).toBeVisible()
  await expect(page.getByRole('button', { name: 'Load simulation' })).toBeDisabled()
  await page.getByRole('button', { name: 'Disconnect' }).first().click()
  await expect(page.getByText('Disconnected. Host measurements and model data have been cleared.')).toBeVisible()
  await expect(page.getByText('Fixture desktop')).toHaveCount(0)
  await expect(page.getByText('Connect to view measurements')).toHaveCount(2)
})

test('marks fresh partial GPU telemetry clearly and shows the reported device error', async ({ page }) => {
  const host = fixtureHost('Partial telemetry desktop')
  host.status = 'degraded'
  host.gpu_error = 'NVML telemetry is unavailable.'
  host.loading_enabled = false
  host.gpus = [{ id: gpuUuid, name: 'Fixture GPU', memory: null, error: 'Driver did not expose memory counters.' }]
  await installSseMock(page)
  await installM2Api(page)
  await page.route('**/api/host', (route) => route.fulfill({ json: host }))
  await page.goto('/')
  await page.getByLabel('Access token').fill(token)
  await page.getByRole('button', { name: 'Connect to host' }).click()
  await expect.poll(() => streamCount(page)).toBe(1)
  await expect.poll(() => pushFrame(page, host)).toBe(true)
  await expect(page.getByText('Live · partial telemetry')).toBeVisible()
  await expect(page.getByText('PARTIAL').first()).toBeVisible()
  await expect(page.getByText('Driver did not expose memory counters.')).toBeVisible()
})

test('rejects invalid access tokens without opening the event stream', async ({ page }) => {
  let eventCalls = 0
  await page.route('**/api/host', (route) => route.fulfill({ status: 401, json: { detail: 'Unauthorized' } }))
  await page.route('**/api/events', async (route) => { eventCalls += 1; await route.fulfill({ status: 401 }) })
  await page.goto('/')
  await page.getByLabel('Access token').fill('wrong-token')
  await page.getByRole('button', { name: 'Connect to host' }).click()
  await expect(page.getByText('The access token was rejected. Check the token and reconnect.')).toBeVisible()
  expect(eventCalls).toBe(0)
})

test('drops the first host immediately when the server address changes', async ({ page }) => {
  await installSseMock(page)
  await installM2Api(page)
  await page.route('**/api/host', async (route) => {
    const label = route.request().url().includes('two.test') ? 'Second desktop' : 'First desktop'
    await route.fulfill({ json: fixtureHost(label, false, label) })
  })
  await page.goto('/')
  await page.getByLabel('Server address').fill('http://one.test:8100')
  await page.getByLabel('Access token').fill(token)
  await page.getByRole('button', { name: 'Connect to host' }).click()
  await expect.poll(() => streamCount(page)).toBe(1)
  await expect.poll(() => pushFrame(page, fixtureHost('First desktop', false, 'First desktop'))).toBe(true)
  await expect(page.getByText('First desktop')).toBeVisible()
  await page.getByLabel('Server address').fill('http://two.test:8100')
  await expect(page.getByText('First desktop')).toHaveCount(0)
  await expect(page.getByText('No host selected')).toBeVisible()
  await page.getByRole('button', { name: 'Connect to host' }).click()
  await expect.poll(() => streamCount(page)).toBe(2)
  await expect.poll(() => pushFrame(page, fixtureHost('Second desktop', false, 'Second desktop'))).toBe(true)
  await expect(page.getByText('Second desktop')).toBeVisible()
  expect(await page.evaluate(() => localStorage.getItem('generation-station.server-url'))).toBe('http://two.test:8100')
  expect(page.url()).not.toContain(token)
})

test('reconnects after a stream outage longer than the watchdog and accepts the new sample', async ({ page }) => {
  const initial = fixtureHost('Initial desktop')
  const recovered = { ...fixtureHost('Recovered desktop', false, 'new-service-instance'), sequence: 2,
    ram: { total_bytes: 32 * 1024 ** 3, available_bytes: 15 * 1024 ** 3, used_bytes: 17 * 1024 ** 3 } }
  await installSseMock(page)
  await installM2Api(page)
  await page.route('**/api/host', (route) => route.fulfill({ json: initial }))
  await page.goto('/')
  await page.getByLabel('Access token').fill(token)
  await page.getByRole('button', { name: 'Connect to host' }).click()
  await expect.poll(() => streamCount(page)).toBe(1)
  await expect(page.getByText('STALE').first()).toBeVisible({ timeout: 5000 })
  await expect.poll(() => streamCount(page), { timeout: 20_000 }).toBeGreaterThanOrEqual(2)
  await expect.poll(() => pushFrame(page, recovered)).toBe(true)
  await expect(page.getByText('Recovered desktop')).toBeVisible()
  await expect(page.getByText('17 GiB')).toBeVisible()
  await expect(page.getByText('Live telemetry is streaming from the host.')).toBeVisible()
})

test('starts a model server with the chosen model, GPUs and advanced settings, then stops it', async ({ page }) => {
  const api = await connectFixtures(page, 'Fixture desktop', false, { runtime: true })
  // Starting and stopping spans several polls; stream fresh samples the way the real host does.
  await page.evaluate((data) => {
    window.setInterval(() => window.dispatchEvent(new CustomEvent('gs:push-frame', { detail: JSON.stringify(data) })), 500)
  }, fixtureHost())
  await expect(page.getByRole('heading', { name: 'Model servers' })).toBeVisible()
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
  await expect(page.getByText('MODEL SERVER', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Stop', exact: true }).click()
  await expect(page.getByText('Stopped.', { exact: true })).toBeVisible()
  await expect(page.getByText('Stop · unloaded')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Start', exact: true })).toBeEnabled()
})

test('blocks a start until advanced settings and GPU choice are valid, and warns about the RAM guard', async ({ page }) => {
  const api = await connectFixtures(page, 'Fixture desktop', false, { runtime: true })
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
  await page.getByRole('button', { name: 'Start', exact: true }).click()
  const refusal = page.getByRole('alert').filter({ hasText: 'INSUFFICIENT_VRAM' })
  await expect(refusal).toBeVisible()
  await expect(refusal.getByText('Fixture GPU')).toBeVisible()
  await expect(refusal.getByText('Required 24 GiB')).toBeVisible()
  await expect(page.getByText(gpuUuid)).toHaveCount(0)
  await expect(page.getByText('Stopped', { exact: true })).toBeVisible()
})
