import { expect, test, type Page, type Route } from '@playwright/test'

const token = 'test-token-with-enough-length-for-fixture-only'

function fixtureHost(label = 'Fixture desktop', stale = false, instance = 'fixture-instance') {
  return {
    instance_id: instance,
    host: { hostname: label.toLowerCase().replaceAll(' ', '-'), os: 'Windows', label, role: 'desktop', scope: 'host' },
    ram: { total_bytes: 32 * 1024 ** 3, available_bytes: 20 * 1024 ** 3, used_bytes: 12 * 1024 ** 3 },
    ram_error: null,
    gpus: [{ id: 'gpu-fixture-0', name: 'Fixture GPU', memory: { total_bytes: 32 * 1024 ** 3, available_bytes: 28 * 1024 ** 3, used_bytes: 4 * 1024 ** 3 }, error: null }],
    gpu_error: null,
    observed_at: '2026-10-08T00:00:00+00:00', sequence: 1, age_seconds: 0,
    stale, stale_after_seconds: 2, status: stale ? 'stale' : 'live', loading_enabled: false,
    loading_reason: 'Unavailable in the preview.',
  }
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

async function connectFixtures(page: Page, label = 'Fixture desktop', stale = false) {
  await installSseMock(page)
  const host = fixtureHost(label, stale)
  await page.route('**/api/host', async (route: Route) => {
    if (route.request().headers().authorization !== `Bearer ${token}`) {
      await route.fulfill({ status: 401, json: { detail: 'Unauthorized' } })
      return
    }
    await route.fulfill({ json: host })
  })
  await page.route('**/api/models', (route) => route.fulfill({ json: { models: [] } }))
  await page.goto('/')
  await page.getByLabel('Access token').fill(token)
  await page.getByRole('button', { name: 'Connect to host' }).click()
  await expect.poll(() => streamCount(page)).toBe(1)
  await expect.poll(() => pushFrame(page, host)).toBe(true)
}

test('shows an honest disconnected screen on desktop and narrow mobile', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1050 })
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'System overview' })).toBeVisible()
  await expect(page.getByText('No host selected')).toBeVisible()
  await expect(page.getByText('Connect to view measurements')).toHaveCount(2)
  await expect(page.getByText('No models installed yet')).toHaveCount(0)
  await page.screenshot({ path: 'test-results/screenshots/disconnected-desktop.png', fullPage: true })
  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.getByRole('heading', { name: 'System overview' })).toBeVisible()
  await expect(page.getByLabel('Resource usage')).toBeVisible()
  await page.screenshot({ path: 'test-results/screenshots/disconnected-mobile.png', fullPage: true })
})

test('authenticates, renders measured host values, and leaves models empty without inventing entries', async ({ page }) => {
  await connectFixtures(page)
  await expect(page.getByText('Fixture desktop')).toBeVisible()
  await expect(page.getByText('12 GiB')).toBeVisible()
  await expect(page.getByText('32 GiB').first()).toBeVisible()
  await expect(page.getByText('4 GiB')).toBeVisible()
  await expect(page.getByText('No models installed yet')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Add model' })).toBeDisabled()
  await expect(page.getByText('Live telemetry is streaming from the host.')).toBeVisible()
  expect(await page.evaluate(() => localStorage.getItem('generation-station.server-url'))).toBe('')
  expect(await page.evaluate(() => Object.keys(localStorage).some((key) => /token/i.test(key)))).toBe(false)
})

test('clears old measurements on disconnect and marks telemetry stale', async ({ page }) => {
  await connectFixtures(page, 'Fixture desktop', true)
  await expect(page.getByText('Telemetry stale')).toBeVisible()
  await expect(page.getByText('Last known measurement').first()).toBeVisible()
  await page.getByRole('button', { name: 'Disconnect' }).first().click()
  await expect(page.getByText('Disconnected. Host measurements and model data have been cleared.')).toBeVisible()
  await expect(page.getByText('Fixture desktop')).toHaveCount(0)
  await expect(page.getByText('Connect to view measurements')).toHaveCount(2)
})

test('marks fresh partial GPU telemetry clearly and shows the reported device error', async ({ page }) => {
  const host = fixtureHost('Partial telemetry desktop')
  host.status = 'degraded'
  host.gpu_error = 'NVML telemetry is unavailable.'
  host.gpus = [{ id: 'gpu-fixture-0', name: 'Fixture GPU', memory: null, error: 'Driver did not expose memory counters.' }]
  await installSseMock(page)
  await page.route('**/api/host', (route) => route.fulfill({ json: host }))
  await page.route('**/api/models', (route) => route.fulfill({ json: { models: [] } }))
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
  await page.route('**/api/host', async (route) => {
    const label = route.request().url().includes('two.test') ? 'Second desktop' : 'First desktop'
    await route.fulfill({ json: fixtureHost(label, false, label) })
  })
  await page.route('**/api/models', (route) => route.fulfill({ json: { models: [] } }))
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
  await page.route('**/api/host', (route) => route.fulfill({ json: initial }))
  await page.route('**/api/models', (route) => route.fulfill({ json: { models: [] } }))
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
