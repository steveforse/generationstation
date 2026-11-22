import { readFileSync } from 'node:fs'
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
    id: 'basalt', kind: 'basalt', plugin: 'Basalt', name: 'Basalt', description: 'Runs a large language model for chat and coding.', workload: 'text', port: 8160, default_preset: 'ds41', last_launch: null,
    presets: {
      ds41: { name: 'DeepSeek V4.1 Flash', gpus: [0, 1], allowed_gpus: gpus, estimate: { ram_gib: 16, gpu_min_free_gib: { 0: 24, 1: 10 } }, settings: [
        setting('vram_reserve_mib', 'VRAM left free on the main card', 'int', 700, { minimum: 256, maximum: 32768, unit: 'MiB' }),
        setting('resident_budget_gib', 'RAM for overflow experts', 'optional_int', 48, { minimum: 1, maximum: 1024, unit: 'GiB' }),
        setting('ram_reserve_mib', 'RAM left for Windows', 'int', 0, { minimum: 0, maximum: 262144, unit: 'MiB' }),
      ] },
      fn: { name: 'Qwen3.8 Flash-Next', description: 'Fixture note about Flash-Next.', gpus: [0, 1], allowed_gpus: gpus, estimate: { ram_gib: 40, gpu_min_free_gib: { 0: 24, 1: 10 } }, settings: [
        setting('kv', 'KV cache precision', 'choice', 'int8', { options: ['int8', 'q4_0'] }),
        setting('vram_reserve_mib', 'VRAM left free on the main card', 'int', 700, { minimum: 256, maximum: 32768, unit: 'MiB' }),
        setting('resident_experts', 'Keep overflow experts in RAM', 'bool', true),
      ] },
    },
  }
}

function videoRuntimeFixture() {
  const field = (key: string, label: string, kind: string, extra: Record<string, unknown> = {}) => ({
    key, label, kind, required: false, default: null, minimum: null, maximum: null, max_length: null, options: [], placeholder: null, help: `${label} help`, advanced: false, ...extra,
  })
  const common = [field('quality', 'Quality', 'choice', { options: ['quick', 'best'], default: 'quick' }), field('seed', 'Seed', 'seed', { minimum: 0, maximum: 2147483647, advanced: true })]
  return {
    id: 'minimax_h3', kind: 'minimax_h3', plugin: 'MiniMax H3', name: 'MiniMax H3 videos', description: 'Makes short video clips.', workload: 'video', port: 8190, default_preset: 'uncensored', last_launch: { preset: 'uncensored', settings: {}, gpus: [0] }, max_gpus: 1,
    presets: { uncensored: { name: 'MiniMax H3 Uncensored', gpus: [0], allowed_gpus: [{ index: 0, name: 'Fixture GPU' }], estimate: { ram_gib: 60, gpu_min_free_gib: { 0: 28 } }, settings: [] } },
    generation: { output_kind: 'video', inputs: [], timings: [{ seconds: 39, first_seconds: 92, when: { mode: 'text', quality: 'quick' }, preset: null, gpu: 0, note: null }], modes: [
      { key: 'text', label: 'From a description', help: 'Write what happens.', inputs: [field('prompt', 'Description', 'textarea', { required: true, max_length: 3000 }),
        field('resolution', 'Resolution', 'choice', { options: ['720p', '540p', 'custom'], default: '540p' }),
        field('shape', 'Shape', 'choice', { options: ['landscape 16:9', 'portrait 9:16', 'square 1:1'], default: 'landscape 16:9' }),
        field('width', 'Custom width', 'int', { minimum: 256, maximum: 1344, default: 960, show_when: { resolution: 'custom' }, ratio_partner: 'height', ratio_role: 'width', shape_field: 'shape' }),
        field('height', 'Custom height', 'int', { minimum: 256, maximum: 1344, default: 544, show_when: { resolution: 'custom' }, ratio_partner: 'width', ratio_role: 'height', shape_field: 'shape' }), ...common] },
      { key: 'frames', label: 'From pictures', help: 'Start from a picture, end on one, or both.', inputs: [
        field('first', 'First frame', 'files', { accept: ['image'], max_count: 1 }), field('last', 'Last frame', 'files', { accept: ['image'], max_count: 1 }),
        field('prompt', 'What happens', 'textarea', { required: true, max_length: 3000 }),
        field('shape', 'Shape', 'choice', { options: ['match picture', 'landscape 16:9', 'portrait 9:16'], default: 'match picture' }),
        field('first_crop', 'First frame framing', 'crop', { target: 'first', shape_field: 'shape' }), ...common] },
    ] },
  }
}

function songRuntimeFixture() {
  const field = (key: string, label: string, kind: string, extra: Record<string, unknown> = {}) => ({
    key, label, kind, required: false, default: null, minimum: null, maximum: null, max_length: null, options: [], placeholder: null, help: `${label} help`, advanced: false, ...extra,
  })
  return {
    id: 'yue2', kind: 'yue2', plugin: 'YuE2', name: 'YuE2 songs', description: 'Makes complete songs from lyrics and a style.', workload: 'music', port: 8170, default_preset: 'songs', last_launch: null, max_gpus: 1,
    presets: { songs: { name: 'YuE2 3B', gpus: [1], allowed_gpus: [{ index: 0, name: 'Fixture GPU' }, { index: 1, name: 'Second GPU' }], estimate: { ram_gib: 24, gpu_min_free_gib: { 0: 14, 1: 14 } }, settings: [] } },
    generation: { output_kind: 'audio', inputs: [
      field('style', 'Style', 'text', { required: true, max_length: 400, placeholder: 'Upbeat indie pop' }),
      field('lyrics', 'Lyrics', 'textarea', { required: true, max_length: 8000 }),
      field('mode', 'Melody planning', 'choice', { options: ['full', 'melody', 'off'], default: 'full', advanced: true }),
      field('seed', 'Seed', 'seed', { minimum: 0, maximum: 2147483647, advanced: true }),
    ], timings: [{ seconds: 41, first_seconds: null, when: {}, preset: null, gpu: null, note: 'for a verse and chorus' }] },
  }
}

async function installM2Api(page: Page, options: { initialProfile?: boolean; refuseLoad?: boolean; initialState?: string; runtime?: boolean; refuseStart?: boolean; songs?: boolean; songState?: string; videos?: boolean } = {}) {
  const profiles = options.initialProfile ? [profileRecord()] : []
  const models: Array<Record<string, unknown>> = options.initialProfile ? [modelRecord(profiles[0], options.initialState ?? 'unloaded')] : []
  if (options.runtime) models.push({ id: 'basalt', name: 'Basalt', workload: 'text', state: 'unloaded', loading_enabled: false, profile: { id: null, revision: null } })
  const operations: Array<Record<string, unknown>> = []
  let rejected = !!options.refuseLoad
  let refuseStart = !!options.refuseStart
  let postProfileBody: Record<string, unknown> | null = null
  let loadProfileId: unknown = null
  let startBody: Record<string, unknown> | null = null
  await page.route('**/api/runtimes', (route) => route.fulfill({ json: { runtimes: [...(options.runtime ? [runtimeFixture()] : []), ...(options.songs ? [songRuntimeFixture()] : []), ...(options.videos ? [videoRuntimeFixture()] : [])] } }))
  await page.route('**/api/runtimes/*/estimate', (route) => {
    const body = route.request().postDataJSON() as { preset: string; settings: Record<string, unknown>; gpus: number[] }
    const runtime = route.request().url().includes('/runtimes/basalt/') ? runtimeFixture() : songRuntimeFixture()
    const preset = (runtime.presets as Record<string, { estimate: { ram_gib: number; gpu_min_free_gib: Record<number, number> } }>)[body.preset]
    const budget = typeof body.settings.resident_budget_gib === 'number' ? body.settings.resident_budget_gib : 0
    const ids = [gpuUuid, 'GPU-second']
    return route.fulfill({ json: {
      ram_bytes: (preset.estimate.ram_gib + budget) * 1024 ** 3,
      gpu_vram_bytes_by_id: Object.fromEntries(body.gpus.map((index) => [ids[index], preset.estimate.gpu_min_free_gib[index] * 1024 ** 3])),
      ram_headroom_bytes: 4 * 1024 ** 3, gpu_headroom_bytes: 2 * 1024 ** 3, reserved_ram_bytes: 0, reserved_gpu_vram_bytes_by_id: {},
    } })
  })
  if (options.videos) models.push({ id: 'minimax_h3', name: 'MiniMax H3 videos', workload: 'video', state: 'ready', loading_enabled: false, profile: { id: null, revision: null } })
  const uploads: Array<{ name: string; type: string }> = []
  await page.route('**/api/uploads?name=*', async (route) => {
    const name = new URL(route.request().url()).searchParams.get('name') ?? ''
    if (name.endsWith('.gif')) { await route.fulfill({ status: 422, json: { detail: 'That type of file is not accepted.' } }); return }
    uploads.push({ name, type: route.request().headers()['content-type'] })
    await route.fulfill({ status: 201, json: { id: `${uploads.length}`.padStart(32, 'a'), name, kind: 'image', mime: 'image/png', bytes: 8 } })
  })
  if (options.songs) models.push({ id: 'yue2', name: 'YuE2 songs', workload: 'music', state: options.songState ?? 'ready', loading_enabled: false, profile: { id: null, revision: null } })
  const jobs: Array<Record<string, unknown>> = []
  let jobBody: Record<string, unknown> | null = null
  let nextJob = 1
  // One job at a time, like a worker: each poll moves the queue along (queued -> running -> done after 3 polls).
  const advance = () => {
    const running = jobs.find((job) => job.status === 'running')
    if (running) {
      running.ticks = (running.ticks as number) + 1
      if ((running.ticks as number) >= 3) Object.assign(running, { status: 'done', progress: 'Done: 1 seconds, seed 42', outputs: [{ name: 'song.wav', mime: 'audio/wav', bytes: 44 }], finished_at: '2026-11-12T00:01:00Z',
        details: { seed: 42, mode: 'full', audio_seconds: 49, seconds: 41.2 }, launch: { preset: 'songs', settings: {}, gpus: [1] } })
      return
    }
    const next = [...jobs].reverse().find((job) => job.status === 'queued')
    if (next) Object.assign(next, { status: 'running', progress: 'Composing the song', ticks: 0 })
  }
  await page.route('**/api/jobs?limit=100', (route) => { advance(); return route.fulfill({ json: { jobs } }) })
  await page.route('**/api/models/*/jobs', async (route) => {
    jobBody = route.request().postDataJSON() as Record<string, unknown>
    const id = `job-0000000${nextJob++}`
    const job = { id, model_id: route.request().url().split('/models/')[1].split('/')[0], inputs: { mode: 'full', ...(jobBody.inputs as object) }, status: 'queued', progress: null, outputs: [], error_message: null, created_at: `2026-11-12T00:00:0${nextJob}Z`, finished_at: null, ticks: 0 }
    jobs.unshift(job)
    await route.fulfill({ status: 202, json: job })
  })
  await page.route('**/api/jobs/*/cancel', async (route) => {
    const job = jobs.find((item) => route.request().url().includes(`/jobs/${item.id}/`))!
    Object.assign(job, { status: 'cancelled', progress: 'Cancelled', finished_at: '2026-11-12T00:00:30Z' })
    await route.fulfill({ json: job })
  })
  await page.route(/\/api\/jobs\/job-\d+$/, async (route) => {
    const index = jobs.findIndex((item) => route.request().url().endsWith(`/jobs/${item.id}`))
    if (route.request().method() === 'DELETE') {
      jobs.splice(index, 1)
      await route.fulfill({ json: { id: 'deleted', deleted: true } })
      return
    }
    await route.fulfill({ json: jobs[index] })
  })
  await page.route('**/api/jobs/*/files/song.wav', (route) => route.fulfill({ status: 200, contentType: 'audio/wav', body: Buffer.alloc(44) }))
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
  return { profiles, models, operations, get postProfileBody() { return postProfileBody }, get loadProfileId() { return loadProfileId }, get startBody() { return startBody }, get jobBody() { return jobBody }, uploads }
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

async function connectFixtures(page: Page, label = 'Fixture desktop', stale = false, options: { initialProfile?: boolean; refuseLoad?: boolean; initialState?: string; runtime?: boolean; refuseStart?: boolean; songs?: boolean; songState?: string; videos?: boolean } = {}) {
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
  await nav.getByRole('link', { name: /Models/ }).click()
  await expect(page.getByRole('heading', { name: 'Models', level: 1 })).toBeVisible()
  await expect(page).toHaveURL(/#\/hosts\/local\/models$/)
  await expect(page.getByLabel('Basalt', { exact: true })).toBeVisible()
  await page.screenshot({ path: 'test-results/screenshots/models-page.png', fullPage: true })
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
  await go(page, '#/hosts/local/models')
  await expect(page.getByRole('heading', { name: 'Models', level: 1 })).toBeVisible()
  const nav = page.getByRole('navigation', { name: 'Main navigation' })
  await expect(nav.getByRole('link', { name: /Basalt/ })).toHaveCount(0)
  await expect(nav.getByRole('link', { name: /Test profiles|Capacity test/ })).toHaveCount(0)
  await expect(page.getByRole('link', { name: 'Capacity test profiles' })).toHaveAttribute('href', '#/hosts/local/profiles')
  const resources = page.getByLabel('Fixture desktop resource usage')
  await expect(resources.getByText('System memory')).toBeVisible()
  await expect(resources.getByText('Fixture GPU')).toBeVisible()
  await expect(page.getByText('Stopped', { exact: true })).toBeVisible()
  await expect(page.getByText('Runs a large language model for chat and coding.')).toBeVisible()
  await expect(page.getByText('Fixture note about Flash-Next.')).toHaveCount(0)
  await page.getByRole('radio', { name: 'Qwen3.8 Flash-Next' }).check()
  await expect(page.getByText('Fixture note about Flash-Next.')).toBeVisible()
  await page.getByRole('checkbox', { name: 'Second GPU' }).uncheck()
  const fit = page.getByLabel('Basalt if started')
  await expect(fit.locator('.runtime-fit-row').filter({ hasText: 'RAM' }).first()).toContainText('needs 40 GiB16 GiB free after 4 GiB headroom24 GiB short')
  await expect(fit.locator('.runtime-fit-row').filter({ hasText: 'Fixture GPU VRAM' })).toContainText('needs 24 GiB26 GiB free after 2 GiB headroomFits')
  const ramPreview = page.getByRole('progressbar', { name: 'System memory used' }).getByLabel(/Basalt if started/)
  await expect(ramPreview).toHaveAttribute('data-tip', 'Basalt if started · needs 40 GiB · won’t fit')
  await expect(page.getByRole('progressbar', { name: 'Fixture GPU used' }).getByLabel('Basalt if started · needs 24 GiB')).toBeVisible()
  await expect(page.getByText(/Basalt then uses whatever VRAM is free beyond its reserve/)).toBeVisible()
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
  await expect(nav.getByRole('link', { name: /Models/ })).toContainText('1 on')
  await expect(page.getByRole('link', { name: 'Open Basalt' })).toHaveCount(0)
  await page.getByRole('button', { name: 'Stop', exact: true }).click()
  await expect(page.getByText('Stopped.', { exact: true })).toBeVisible()
  await expect(page.getByText('Stop · unloaded')).toBeVisible()
  await page.screenshot({ path: 'test-results/screenshots/models-history.png', fullPage: true })
  await expect(page.getByRole('button', { name: 'Start', exact: true })).toBeEnabled()
})

test('blocks a start until advanced settings and GPU choice are valid, and warns about the RAM guard', async ({ page }) => {
  const api = await connectFixtures(page, 'Fixture desktop', false, { runtime: true })
  await go(page, '#/hosts/local/models')
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
  await go(page, '#/hosts/local/models')
  await page.getByRole('button', { name: 'Start', exact: true }).click()
  const refusal = page.getByRole('alert').filter({ hasText: 'INSUFFICIENT_VRAM' })
  await expect(refusal).toBeVisible()
  await expect(refusal.getByText('Fixture GPU')).toBeVisible()
  await expect(refusal.getByText('Required 24 GiB')).toBeVisible()
  await expect(page.getByText(gpuUuid)).toHaveCount(0)
})

test('makes a song, keeps it in the sidebar with how it was made, reuses its settings and deletes it', async ({ page }) => {
  const api = await connectFixtures(page, 'Fixture desktop', false, { songs: true })
  await go(page, '#/hosts/local/models')
  await expect(page.getByRole('radio', { name: 'Second GPU' })).toBeChecked()
  await page.getByRole('link', { name: 'Open YuE2 songs' }).click()
  await expect(page).toHaveURL(/#\/hosts\/local\/services\/yue2$/)
  await expect(page.getByText('Running', { exact: true })).toBeVisible()
  await expect(page.getByRole('radio')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Stop', exact: true })).toHaveCount(0)
  const form = page.getByRole('form', { name: 'Make a song' })
  await expect(form.getByRole('button', { name: 'Make a song' })).toBeDisabled()
  await form.getByLabel(/^STYLE/).fill('Upbeat indie pop, female vocals')
  await form.getByLabel(/^LYRICS/).fill('[Verse]\nSunlight on the kitchen floor\n\n[Chorus]\nSing it back to me')
  await form.getByRole('button', { name: 'More options' }).click()
  await form.getByLabel(/^SEED/).fill('42')
  await expect(form.getByText('Usually about 41 s, for a verse and chorus.')).toBeVisible()
  const styleHelp = form.getByRole('button', { name: 'What Style does' })
  await expect(form.getByText('Style help')).toBeHidden()
  await styleHelp.hover()
  await expect(form.getByRole('tooltip').filter({ hasText: 'Style help' })).toBeVisible()
  await expect(styleHelp).toHaveAccessibleDescription('Style help')
  await page.mouse.move(0, 0)
  await expect(form.getByText('Style help')).toBeHidden()
  await form.getByRole('button', { name: 'What Seed does' }).focus()
  await expect(form.getByText('Seed help')).toBeVisible()
  await page.screenshot({ path: 'test-results/screenshots/help-tip.png' })
  await form.getByRole('button', { name: 'What Seed does' }).press('Escape')
  await expect(form.getByText('Seed help')).toBeHidden()
  await page.screenshot({ path: 'test-results/screenshots/make-a-song.png', fullPage: true })
  await form.getByRole('button', { name: 'Make a song' }).click()
  const rail = page.getByRole('complementary', { name: 'Your songs' })
  const item = rail.getByRole('button', { name: /^Upbeat indie pop, female vocals/ })
  await expect(item).toContainText(/Queued · next|Composing · Composing the song/)
  expect(api.jobBody).toEqual({ inputs: { style: 'Upbeat indie pop, female vocals', lyrics: '[Verse]\nSunlight on the kitchen floor\n\n[Chorus]\nSing it back to me', mode: 'full', seed: 42 } })
  await expect(item).toContainText('41 s', { timeout: 15_000 })
  await item.click()
  const modal = page.getByRole('dialog', { name: 'Upbeat indie pop, female vocals' })
  const detail = modal.getByRole('article', { name: /^song: Upbeat indie pop/ })
  await expect(detail.getByText('took 41 s')).toBeVisible()
  await expect(page.getByLabel('Play Upbeat indie pop, female vocals')).toBeVisible()
  await expect(detail.getByRole('link', { name: 'song.wav' })).toBeVisible()
  await expect(detail.getByText('Sing it back to me')).toBeVisible()
  await expect(detail.getByText('YuE2 3B')).toBeVisible()
  await expect(detail.getByText('Second GPU')).toBeVisible()
  await page.screenshot({ path: 'test-results/screenshots/song-result.png' })
  await modal.getByRole('button', { name: 'Close' }).click()
  await expect(modal).toBeHidden()
  await page.screenshot({ path: 'test-results/screenshots/song-rail.png', fullPage: true })
  await go(page, '#/overview')
  await expect(page.getByText('RECENT RESULTS')).toBeVisible()
  await go(page, '#/hosts/local/services/yue2')
  await form.getByLabel(/^STYLE/).fill('changed')
  await item.click()
  await detail.getByRole('button', { name: 'Use these settings' }).click()
  await expect(modal).toBeHidden()
  await expect(form.getByLabel(/^STYLE/)).toHaveValue('Upbeat indie pop, female vocals')
  await expect(form.getByLabel(/^SEED/)).toHaveValue('42')
  await item.click()
  await detail.getByRole('button', { name: 'Delete' }).click()
  await expect(detail.getByText('Delete this song and its files?')).toBeVisible()
  await detail.getByRole('button', { name: 'Delete', exact: true }).click()
  await expect(rail.getByText('Nothing yet. What you make appears here.')).toBeVisible()
  await expect(modal).toBeHidden()
})

test('queues further songs behind the one being made and cancels a queued one', async ({ page }) => {
  await connectFixtures(page, 'Fixture desktop', false, { songs: true })
  await go(page, '#/hosts/local/services/yue2')
  const form = page.getByRole('form', { name: 'Make a song' })
  await form.getByLabel(/^STYLE/).fill('First song')
  await form.getByLabel(/^LYRICS/).fill('la')
  await form.getByRole('button', { name: 'Make a song' }).click()
  await form.getByLabel(/^STYLE/).fill('Second song')
  await expect(form.getByText('One is ahead in the queue; this one starts after it.')).toBeVisible()
  await form.getByRole('button', { name: 'Add to queue' }).click()
  const rail = page.getByRole('complementary', { name: 'Your songs' })
  const second = rail.getByRole('button', { name: /^Second song/ })
  await expect(rail.getByRole('button', { name: /^First song/ })).toContainText('Composing · Composing the song')
  await expect(second).toContainText('Queued · next')
  await expect(rail.getByText('1 composing · 1 queued')).toBeVisible()
  await page.screenshot({ path: 'test-results/screenshots/song-queue.png' })
  await rail.getByRole('button', { name: 'Cancel Second song' }).click()
  await expect(second).toContainText('Cancelled')
  await expect(rail.getByRole('button', { name: 'Cancel Second song' })).toHaveCount(0)
  await expect(rail.getByRole('button', { name: /^First song/ })).toContainText('41 s', { timeout: 15_000 })
})

test('makes a video from pictures in its own tab, with one picture per end', async ({ page }) => {
  const api = await connectFixtures(page, 'Fixture desktop', false, { videos: true })
  await go(page, '#/hosts/local/services/minimax_h3')
  const tabs = page.getByRole('tablist', { name: 'How to make it' })
  await expect(tabs.getByRole('tab', { name: 'From a description' })).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByText('Usually about 39 s on the Fixture GPU.', { exact: false })).toBeVisible()
  const textPanel = page.getByRole('tabpanel', { name: 'From a description' })
  await textPanel.getByLabel(/^DESCRIPTION/).fill('kept while I switch tabs')
  await expect(textPanel.getByLabel(/^CUSTOM WIDTH/)).toHaveCount(0)
  await textPanel.getByLabel(/^RESOLUTION/).selectOption('custom')
  await expect(textPanel.getByLabel(/^CUSTOM WIDTH/)).toHaveValue('960')
  await expect(textPanel.getByLabel(/^CUSTOM HEIGHT/)).toHaveValue('540')  // re-derived from 16:9
  await textPanel.getByLabel(/^CUSTOM WIDTH/).fill('1280')
  await expect(textPanel.getByLabel(/^CUSTOM HEIGHT/)).toHaveValue('720')
  await textPanel.getByLabel(/^CUSTOM HEIGHT/).fill('360')
  await expect(textPanel.getByLabel(/^CUSTOM WIDTH/)).toHaveValue('640')
  await textPanel.getByLabel(/^SHAPE/).selectOption('square 1:1')
  await expect(textPanel.getByLabel(/^CUSTOM HEIGHT/)).toHaveValue('640')
  await textPanel.getByRole('button', { name: 'Locked to the shape’s proportions' }).click()
  await textPanel.getByLabel(/^CUSTOM WIDTH/).fill('800')
  await expect(textPanel.getByLabel(/^CUSTOM HEIGHT/)).toHaveValue('640')  // unlocked: unchanged
  await textPanel.getByLabel(/^CUSTOM WIDTH/).fill('100')
  await expect(textPanel.getByRole('button', { name: 'Make a video' })).toBeDisabled()  // below the minimum
  await textPanel.getByLabel(/^RESOLUTION/).selectOption('540p')
  await expect(textPanel.getByLabel(/^CUSTOM WIDTH/)).toHaveCount(0)
  await expect(textPanel.getByRole('button', { name: 'Make a video' })).toBeEnabled()  // hidden fields do not count
  await tabs.getByRole('tab', { name: 'From pictures' }).click()
  const panel = page.getByRole('tabpanel', { name: 'From pictures' })
  await expect(panel.getByText('Start from a picture, end on one, or both.')).toBeVisible()
  const png = { name: 'start.png', mimeType: 'image/png', buffer: Buffer.from('89504e470d0a1a0a0000', 'hex') }
  const [chooser] = await Promise.all([page.waitForEvent('filechooser'), panel.getByRole('button', { name: 'Add picture: First frame' }).click()])
  await chooser.setFiles(png)
  await expect(panel.getByRole('img', { name: 'start.png' })).toBeVisible()
  await expect(panel.getByRole('button', { name: 'Add picture: First frame' })).toHaveCount(0)  // the first frame takes one picture
  const [wrong] = await Promise.all([page.waitForEvent('filechooser'), panel.getByRole('button', { name: 'Add picture: Last frame' }).click()])
  await wrong.setFiles({ name: 'end.gif', mimeType: 'image/gif', buffer: Buffer.from('474946383961', 'hex') })
  await expect(panel.getByText('Not a picture this accepts.')).toBeVisible()
  await expect(panel.getByRole('button', { name: 'Make a video' })).toBeDisabled()
  await panel.getByRole('button', { name: 'Remove end.gif' }).click()
  await panel.getByLabel(/^WHAT HAPPENS/).fill('She turns toward the window and smiles.')
  await page.screenshot({ path: 'test-results/screenshots/video-from-pictures.png', fullPage: true })
  await panel.getByRole('button', { name: 'Make a video' }).click()
  await expect.poll(() => api.jobBody).not.toBeNull()
  expect(api.jobBody).toEqual({ inputs: { mode: 'frames', first: ['a'.repeat(31) + '1'], prompt: 'She turns toward the window and smiles.', shape: 'match picture', quality: 'quick' } })
  expect(api.uploads).toEqual([{ name: 'start.png', type: 'image/png' }])
  await tabs.getByRole('tab', { name: 'From a description' }).click()
  await expect(page.getByRole('tabpanel', { name: 'From a description' }).getByLabel(/^DESCRIPTION/)).toHaveValue('kept while I switch tabs')
})

test('frames a wide picture for a portrait clip on a preview: drag, keys and zoom', async ({ page }) => {
  const api = await connectFixtures(page, 'Fixture desktop', false, { videos: true })
  await go(page, '#/hosts/local/services/minimax_h3')
  await page.getByRole('tab', { name: 'From pictures' }).click()
  const panel = page.getByRole('tabpanel', { name: 'From pictures' })
  const [chooser] = await Promise.all([page.waitForEvent('filechooser'), panel.getByRole('button', { name: 'Add picture: First frame' }).click()])
  await chooser.setFiles({ name: 'wide.png', mimeType: 'image/png', buffer: readFileSync(new URL('./fixtures/wide.png', import.meta.url)) })
  await expect(panel.getByRole('slider', { name: /Framing for First frame/ })).toHaveCount(0)  // 'match picture' needs no framing
  await expect(panel.getByLabel(/^SHAPE/).locator('option:checked')).toHaveText('Match picture')
  await panel.getByLabel(/^SHAPE/).selectOption('portrait 9:16')
  await expect(panel.getByLabel(/^SHAPE/).locator('option:checked')).toHaveText('Portrait 9:16')
  const box = panel.getByRole('slider', { name: /Framing for First frame/ })
  await expect(box).toBeVisible()
  await expect(box).toHaveAttribute('aria-valuetext', /^36% from the left, 0% from the top, 100% size$/)
  await box.focus()
  await box.press('Shift+ArrowLeft')
  await expect(box).toHaveAttribute('aria-valuetext', /^26% from the left/)
  const area = await box.boundingBox()
  await page.mouse.move(area!.x + area!.width / 2, area!.y + area!.height / 2)
  await page.mouse.down()
  await page.mouse.move(area!.x + area!.width / 2 + 2000, area!.y + area!.height / 2)
  await page.mouse.up()
  await expect(box).toHaveAttribute('aria-valuetext', /^72% from the left/)  // dragged against the right edge
  await panel.getByRole('slider', { name: 'Framing size for First frame' }).fill('50')
  await expect(box).toHaveAttribute('aria-valuetext', /50% size$/)
  await page.screenshot({ path: 'test-results/screenshots/framing.png', fullPage: true })
  await panel.getByLabel(/^WHAT HAPPENS/).fill('The sun sets.')
  await panel.getByRole('button', { name: 'Make a video' }).click()
  await expect.poll(() => api.jobBody).not.toBeNull()
  const inputs = (api.jobBody as unknown as { inputs: Record<string, string> }).inputs
  expect(inputs.shape).toBe('portrait 9:16')
  const [x, y, w, h] = inputs.first_crop.split(',').map(Number)
  expect(w * 40 / (h * 20)).toBeCloseTo(9 / 16, 2)
  // zooming keeps the centre the box was dragged to
  expect([x + w / 2, y, h]).toEqual([expect.closeTo(0.8594, 3), expect.closeTo(0.25, 3), expect.closeTo(0.5, 3)])
  await panel.getByLabel(/^SHAPE/).selectOption('landscape 16:9')
  await expect(box).toHaveAttribute('aria-valuetext', /100% size$/)  // a box for another shape starts over
})

test('keeps a stopped song service free of load controls and points to the Models page', async ({ page }) => {
  await connectFixtures(page, 'Fixture desktop', false, { songs: true, songState: 'unloaded' })
  await go(page, '#/hosts/local/services/yue2')
  await expect(page.getByText('YuE2 songs is not running. Start it on the Models page first.')).toBeVisible()
  await expect(page.getByText('Makes complete songs from lyrics and a style.')).toBeVisible()
  await expect(page.getByRole('form', { name: 'Make a song' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Start', exact: true })).toHaveCount(0)
  await page.getByRole('link', { name: 'Go to Models' }).click()
  await expect(page.getByRole('heading', { name: 'Models', level: 1 })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Start', exact: true })).toBeVisible()
})

test('shows each running model\'s share of RAM and VRAM in the bars and on its card', async ({ page }) => {
  await connectFixtures(page, 'Fixture desktop', false, { songs: true })
  const withUsage = { ...fixtureHost(), sequence: 2, model_memory: { yue2: { ram_bytes: 6 * 1024 ** 3, gpus: { [gpuUuid]: 3 * 1024 ** 3 }, error: null } } }
  await expect.poll(() => pushFrame(page, withUsage)).toBe(true)
  await go(page, '#/hosts/local/models')
  await expect(page.getByLabel('YuE2 songs memory use')).toHaveText('Using 6 GiB of RAM · 3 GiB on the Fixture GPU')
  const resources = page.getByLabel('Fixture desktop resource usage')
  const ram = resources.getByRole('progressbar', { name: 'System memory used' }).getByLabel('YuE2 songs: 6 GiB')
  await ram.hover()
  await expect(ram).toHaveAttribute('data-tip', 'YuE2 songs · 6 GiB')
  await expect(resources.getByRole('progressbar', { name: 'System memory used' }).getByLabel('Other programs: 6 GiB')).toBeVisible()
  await expect(resources.getByRole('progressbar', { name: 'Fixture GPU used' }).getByLabel('YuE2 songs: 3 GiB')).toBeVisible()
  await page.screenshot({ path: 'test-results/screenshots/model-memory.png' })
})

test('explains when the host service is too old to preview a start', async ({ page }) => {
  await connectFixtures(page, 'Fixture desktop', false, { songs: true, songState: 'unloaded' })
  await page.route('**/api/runtimes/*/estimate', (route) => route.fulfill({ status: 404, json: { detail: 'API route not found' } }))
  await go(page, '#/hosts/local/models')
  await expect(page.getByRole('status').filter({ hasText: 'Restart the Generation Station service' })).toBeVisible()
})

test('keeps host memory pinned beside the model list while scrolling on a wide screen', async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 })
  await connectFixtures(page, 'Fixture desktop', false, { runtime: true, songs: true, songState: 'unloaded' })
  await keepFresh(page)
  await go(page, '#/hosts/local/models')
  const rail = page.getByLabel('Fixture desktop resource usage')
  await expect(rail.getByText('System memory')).toBeVisible()
  await expect(page.getByLabel('YuE2 songs if started')).toBeVisible()
  const before = await rail.boundingBox()
  await page.getByLabel('YuE2 songs', { exact: true }).getByRole('button', { name: 'Start', exact: true }).scrollIntoViewIfNeeded()
  await page.mouse.wheel(0, 3000)
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(200)
  const after = await rail.boundingBox()
  expect(before && after && after.x).toBe(before?.x)
  expect(after!.y).toBeGreaterThanOrEqual(0)
  expect(after!.y).toBeLessThan(60)
  await page.screenshot({ path: 'test-results/screenshots/models-rail-scrolled.png' })
})
