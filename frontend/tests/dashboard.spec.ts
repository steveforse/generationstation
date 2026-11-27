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
    id: 'basalt', kind: 'basalt', plugin: 'Basalt', name: 'Basalt', description: 'Runs a large language model for chat and coding.', workload: 'text', port: 8160, default_preset: 'ds41', last_launch: null, chat: true,
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
        field('prompt', 'What happens', 'textarea', { required: true, max_length: 3000, guide: ['Pauses: commas give short pauses.', 'Sounds: [laughter] a laugh.'] }),
        field('shape', 'Shape', 'choice', { options: ['match picture', 'landscape 16:9', 'portrait 9:16'], default: 'match picture' }),
        field('first_crop', 'First frame framing', 'crop', { target: 'first', shape_field: 'shape' }), ...common] },
      { key: 'picture', label: 'A picture', help: 'H3 paints one still picture.', output_kind: 'image', inputs: [field('prompt', 'Description', 'textarea', { required: true, max_length: 3000 }),
        field('size', 'Size', 'choice', { options: ['2 MP', '4 MP', '8 MP'], default: '4 MP' })] },
    ] },
  }
}

/** A text model as the host describes it: one entry, the card decides how it runs, no engine named. */
function llmRuntimeFixture() {
  const setting = (key: string, label: string, kind: string, value: unknown, extra: Record<string, unknown> = {}) => ({
    key, label, kind, default: value, minimum: null, maximum: null, unit: null, help: `${label} help`, options: null, advanced: false, ...extra,
  })
  return {
    license: { use: 'work', weights: 'Apache-2.0', code: 'oMLX: Apache-2.0', note: 'Fine for company use.', url: 'https://example.com/license' },
    assistant: true,
    id: 'inkling2', kind: 'llm', plugin: 'Text model', name: 'Inkling 2 Mini', description: 'A small, fast model that reads pictures.', workload: 'text', port: 8161,
    default_preset: 'main', last_launch: null, chat: true, max_gpus: null,
    presets: { main: { name: 'Inkling 2 Mini', description: 'Good quality. 60-90 tok/s. About 24 GiB of memory.', gpus: [1], allowed_gpus: [{ index: 0, name: 'Fixture GPU' }, { index: 1, name: 'Second GPU' }],
      estimate: { ram_gib: 6, gpu_min_free_gib: { 0: 24, 1: 12.5 } }, max_gpus: 1,
      card_notes: { 1: 'The standard model on the second card.', 0: 'An uncensored version on the first card.' },
      settings: [
        setting('max_context', 'Context length', 'int', 131072, { minimum: 4096, maximum: 1048576, unit: 'tokens', advanced: true }),
        setting('vision', 'Read pictures', 'choice', 'card', { options: ['card', 'off'], option_labels: { card: 'On', off: 'Off' } }),
        setting('kv', 'Memory precision', 'choice', 'fp8', { options: ['fp8', 'fp16'], advanced: true }),
        setting('vram_reserve_mib', 'VRAM left free on the card', 'int', 700, { minimum: 256, maximum: 32768, unit: 'MiB', advanced: true }),
      ] } },
  }
}

function speechRuntimeFixture() {
  const field = (key: string, label: string, kind: string, extra: Record<string, unknown> = {}) => ({
    key, label, kind, required: false, default: null, minimum: null, maximum: null, max_length: null, options: [], placeholder: null, help: `${label} help`, advanced: false, ...extra,
  })
  const text = field('prompt', 'What to say', 'textarea', { required: true, max_length: 5000 })
  return {
    id: 'omnivoice', kind: 'omnivoice', plugin: 'OmniVoice', name: 'OmniVoice speech', description: 'Speaks text.', workload: 'speech', port: 8200, default_preset: 'omnivoice', last_launch: { preset: 'omnivoice', settings: {}, gpus: [1] }, max_gpus: 1,
    presets: { omnivoice: { name: 'OmniVoice', gpus: [1], allowed_gpus: [{ index: 1, name: 'Second GPU' }], estimate: { ram_gib: 6, gpu_min_free_gib: { 1: 5 } }, settings: [] } },
    generation: { output_kind: 'audio', inputs: [], make_label: 'Make speech', result_noun: 'recording', timings: [], modes: [
      { key: 'design', label: 'Describe a voice', help: 'Choose traits.', inputs: [field('gender', 'Gender', 'choice', { options: ['any', 'female', 'male'], default: 'any' }), text] },
      { key: 'clone', label: 'From a voice sample', help: 'Give a sample.', inputs: [field('sample', 'Voice sample', 'files', { accept: ['audio'], max_count: 1 }),
        field('sample_text', 'What the sample says', 'text', { max_length: 1000 }), text] },
    ] },
  }
}

/** Half a second of a 220 Hz tone as a WAV: a stand-in for a clip's soundtrack (the browser decodes by content). */
function toneWav() {
  const rate = 24000, count = rate / 2
  const buffer = Buffer.alloc(44 + count * 2)
  buffer.write('RIFF', 0); buffer.writeUInt32LE(36 + count * 2, 4); buffer.write('WAVE', 8); buffer.write('fmt ', 12)
  buffer.writeUInt32LE(16, 16); buffer.writeUInt16LE(1, 20); buffer.writeUInt16LE(1, 22); buffer.writeUInt32LE(rate, 24)
  buffer.writeUInt32LE(rate * 2, 28); buffer.writeUInt16LE(2, 32); buffer.writeUInt16LE(16, 34); buffer.write('data', 36); buffer.writeUInt32LE(count * 2, 40)
  for (let index = 0; index < count; index++) buffer.writeInt16LE(Math.round(Math.sin(2 * Math.PI * 220 * index / rate) * 12000), 44 + index * 2)
  return buffer
}

/** Three speech models: two with an arena score (one an estimate) and one without. */
function ratedSpeechFixtures() {
  const quality = (score: number, estimated = false) => ({ metric: 'Speech arena Elo', score, estimated, source: 'https://example.com/arena', as_of: '2026-11-26', note: estimated ? 'Estimated from a sibling.' : 'From votes.' })
  return [
    { ...speechRuntimeFixture(), id: 'voice-b', name: 'Voice B', quality: quality(1104, true) },
    { ...speechRuntimeFixture(), id: 'voice-a', name: 'Voice A', quality: quality(1278), rankings: [{ metric: 'Naturalness MOS', score: 4.4, estimated: false, source: 'https://example.com/mos', as_of: '2026-11-26', note: 'Listener ratings.' }] },
    { ...speechRuntimeFixture(), id: 'voice-c', name: 'Voice C', rankings: [{ metric: 'Naturalness MOS', score: 4.1, estimated: false, source: 'https://example.com/mos', as_of: '2026-11-26' }] },
  ]
}

function songRuntimeFixture() {
  const field = (key: string, label: string, kind: string, extra: Record<string, unknown> = {}) => ({
    key, label, kind, required: false, default: null, minimum: null, maximum: null, max_length: null, options: [], placeholder: null, help: `${label} help`, advanced: false, ...extra,
  })
  return {
    license: { use: 'personal', weights: 'CC BY-NC 4.0 (non-commercial)', note: 'Non-commercial use only.' },
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

function meetingRuntimeFixture() {
  const field = (key: string, label: string, kind: string, extra: Record<string, unknown> = {}) => ({
    key, label, kind, required: false, default: null, minimum: null, maximum: null, max_length: null, options: [], placeholder: null, help: `${label} help`, advanced: false, ...extra,
  })
  const inputs = [field('recording', 'Recording', 'files', { required: true, accept: ['audio', 'video', 'transcript'], max_count: 1 }),
    field('notes', 'Make', 'choice', { options: ['notes', 'transcript'], default: 'notes', option_labels: { notes: 'Transcript and notes', transcript: 'Transcript only' } })]
  return {
    id: 'meeting_notes', kind: 'meeting_notes', plugin: 'Meeting notes', name: 'Meeting notes', description: 'Turns a meeting recording into notes.', workload: 'text', port: 8230, default_preset: 'qwen', last_launch: null, max_gpus: 1,
    presets: { qwen: { name: 'Fast', gpus: [1], allowed_gpus: [{ index: 0, name: 'Fixture GPU' }, { index: 1, name: 'Second GPU' }], estimate: { ram_gib: 4, gpu_min_free_gib: { 0: 1, 1: 1 } }, settings: [] } },
    generation: { output_kind: 'document', inputs, modes: [{ key: 'notes', label: 'From a recording', help: 'Add a recording.', inputs }], make_label: 'Make notes', result_noun: 'meeting', timings: [] },
  }
}

function decideRuntimeFixture() {
  const field = (key: string, label: string, kind: string, extra: Record<string, unknown> = {}) => ({
    key, label, kind, required: false, default: null, minimum: null, maximum: null, max_length: null, options: [], placeholder: null, help: `${label} help`, advanced: false, ...extra,
  })
  const inputs = [field('state', 'Situation', 'textarea', { required: true, max_length: 20000 }),
    field('question_type', 'Question', 'choice', { options: ['choose', 'yesno', 'score'], default: 'choose', option_labels: { choose: 'Choose between options', yesno: 'Yes or no', score: 'Place on a scale' } })]
  return {
    id: 'decide_karpo', kind: 'decide', plugin: 'Decide', name: 'Karpo 31B', description: 'Answers a question with a probability for each answer.', workload: 'decision', port: 8400, default_preset: 'mxfp4', last_launch: null, max_gpus: 1,
    presets: { mxfp4: { name: 'Karpo 31B', gpus: [1], allowed_gpus: [{ index: 0, name: 'Fixture GPU' }, { index: 1, name: 'Second GPU' }], estimate: { ram_gib: 22, gpu_min_free_gib: { 0: 1, 1: 1 } }, settings: [] } },
    generation: { output_kind: 'document', inputs, modes: [], make_label: 'Decide', result_noun: 'decision', timings: [] },
  }
}

async function installM2Api(page: Page, options: { initialProfile?: boolean; refuseLoad?: boolean; initialState?: string; runtime?: boolean; refuseStart?: boolean; songs?: boolean; songState?: string; videos?: boolean; speech?: boolean; voiceClip?: boolean; chatReady?: boolean; thinking?: { levels: string[]; default: string | null; off: boolean }; llm?: boolean; rated?: boolean; meeting?: boolean; decide?: boolean } = {}) {
  const profiles = options.initialProfile ? [profileRecord()] : []
  const models: Array<Record<string, unknown>> = options.initialProfile ? [modelRecord(profiles[0], options.initialState ?? 'unloaded')] : []
  if (options.runtime) models.push({ id: 'basalt', name: 'Basalt', workload: 'text', state: options.chatReady ? 'ready' : 'unloaded', loading_enabled: false, profile: { id: null, revision: null } })
  const operations: Array<Record<string, unknown>> = []
  let rejected = !!options.refuseLoad
  let refuseStart = !!options.refuseStart
  let postProfileBody: Record<string, unknown> | null = null
  let loadProfileId: unknown = null
  let startBody: Record<string, unknown> | null = null
  await page.route('**/api/runtimes', (route) => route.fulfill({ json: { runtimes: [...(options.runtime ? [{ ...runtimeFixture(), thinking: options.thinking ?? null }] : []), ...(options.songs ? [songRuntimeFixture()] : []), ...(options.videos ? [videoRuntimeFixture()] : []), ...(options.speech ? [speechRuntimeFixture()] : []), ...(options.rated ? ratedSpeechFixtures() : []), ...(options.llm ? [llmRuntimeFixture()] : []), ...(options.meeting ? [meetingRuntimeFixture()] : []), ...(options.decide ? [decideRuntimeFixture(), { ...decideRuntimeFixture(), id: 'decide_small', name: 'Small decider', port: 8403 }] : [])], references: options.rated ? [{ name: 'Hosted Voice', workload: 'speech', scores: [{ metric: 'Speech arena Elo', score: 1310, estimated: false, source: 'https://example.com/arena', as_of: '2026-11-26', note: 'A hosted model.' }] }] : [] } }))
  if (options.rated) for (const runtime of ratedSpeechFixtures()) models.push({ id: runtime.id, name: runtime.name, workload: 'speech', state: 'unloaded', loading_enabled: false, profile: { id: null, revision: null } })
  if (options.llm) models.push({ id: 'inkling2', name: 'Inkling 2 Mini', workload: 'text', state: options.chatReady ? 'ready' : 'unloaded', loading_enabled: false, profile: { id: null, revision: null } })
  await page.route('**/api/runtimes/*/connection', (route) => route.fulfill({ json: { bind: '127.0.0.1', port: 8000, model: route.request().url().includes('/inkling2/') ? 'inkling-2-mini' : null } }))
  await page.route('**/api/runtimes/*/estimate', (route) => {
    const body = route.request().postDataJSON() as { preset: string; settings: Record<string, unknown>; gpus: number[] }
    const url = route.request().url()
    const runtime = url.includes('/runtimes/basalt/') ? runtimeFixture() : url.includes('/runtimes/inkling2/') ? llmRuntimeFixture() : songRuntimeFixture()
    const presets = runtime.presets as Record<string, { estimate: { ram_gib: number; gpu_min_free_gib: Record<number, number> } }>
    const preset = presets[body.preset] ?? Object.values(presets)[0]  // a fixture model without its own key still gets an estimate
    const budget = typeof body.settings.resident_budget_gib === 'number' ? body.settings.resident_budget_gib : 0
    const ids = [gpuUuid, 'GPU-second']
    return route.fulfill({ json: {
      ram_bytes: (preset.estimate.ram_gib + budget) * 1024 ** 3,
      gpu_vram_bytes_by_id: Object.fromEntries(body.gpus.map((index) => [ids[index], preset.estimate.gpu_min_free_gib[index] * 1024 ** 3])),
      ram_headroom_bytes: 4 * 1024 ** 3, gpu_headroom_bytes: 2 * 1024 ** 3, reserved_ram_bytes: 0, reserved_gpu_vram_bytes_by_id: {},
    } })
  })
  if (options.videos) models.push({ id: 'minimax_h3', name: 'MiniMax H3 videos', workload: 'video', state: 'ready', loading_enabled: false, profile: { id: null, revision: null } })
  if (options.speech) models.push({ id: 'omnivoice', name: 'OmniVoice speech', workload: 'speech', state: 'ready', loading_enabled: false, profile: { id: null, revision: null } })
  const uploads: Array<{ name: string; type: string; head?: string }> = []
  await page.route('**/api/uploads?name=*', async (route) => {
    const name = new URL(route.request().url()).searchParams.get('name') ?? ''
    if (name.endsWith('.gif')) { await route.fulfill({ status: 422, json: { detail: 'That type of file is not accepted.' } }); return }
    uploads.push({ name, type: route.request().headers()['content-type'], head: route.request().postDataBuffer()?.subarray(0, 12).toString('latin1') })
    await route.fulfill({ status: 201, json: { id: `${uploads.length}`.padStart(32, 'a'), name, kind: 'image', mime: 'image/png', bytes: 8 } })
  })
  if (options.songs) models.push({ id: 'yue2', name: 'YuE2 songs', workload: 'music', state: options.songState ?? 'ready', loading_enabled: false, profile: { id: null, revision: null } })
  const jobs: Array<Record<string, unknown>> = []
  if (options.decide) {
    models.push({ id: 'decide_karpo', name: 'Karpo 31B', workload: 'decision', state: 'ready', loading_enabled: false, profile: { id: null, revision: null } })
    models.push({ id: 'decide_small', name: 'Small decider', workload: 'decision', state: 'ready', loading_enabled: false, profile: { id: null, revision: null } })
    jobs.push({ id: 'job-00000088', model_id: 'decide_karpo', status: 'done', progress: 'Done', error_message: null,
      inputs: { state: 'I was charged twice.', question_type: 'choose', instructions: 'Which team should handle this?', options: 'billing\nshipping' },
      outputs: ['decision.json', 'result.md'].map((name) => ({ name, mime: name.endsWith('.md') ? 'text/markdown' : 'application/json', bytes: 100 })),
      created_at: '2026-11-27T10:00:00Z', finished_at: '2026-11-27T10:00:01Z', details: { seconds: 0.3, model: 'Karpo 31B' }, launch: { preset: 'mxfp4', settings: {}, gpus: [1] } })
    await page.route('**/api/jobs/*/files/result.md', (route) => route.fulfill({ status: 200, contentType: 'text/markdown', body: '**Which team should handle this?**\n\nAnswer: **billing**\n\n| Option | Probability | |\n| --- | ---: | --- |\n| billing | 94.1% | `###` |\n| shipping | 5.9% | `#` |\n\nConfidence: **88.2%**\n' }))
  }
  if (options.meeting) {
    models.push({ id: 'meeting_notes', name: 'Meeting notes', workload: 'text', state: 'ready', loading_enabled: false, profile: { id: null, revision: null } })
    jobs.push({ id: 'job-00000077', model_id: 'meeting_notes', status: 'done', progress: 'Writing the summary, action items and decisions', error_message: null,
      inputs: { mode: 'notes', recording: [{ name: '01-call.webm', kind: 'video', mime: 'video/webm', original: 'call.webm' }], notes: 'notes', text_model: 'auto', correct: 'yes' },
      outputs: ['transcript.md', 'transcript.srt', 'notes.md', 'actions.csv', 'decisions.csv', 'meeting.json'].map((name) => ({ name, mime: name.endsWith('.md') ? 'text/markdown' : name.endsWith('.csv') ? 'text/csv' : 'application/json', bytes: 100 })),
      created_at: '2026-11-23T10:00:00Z', finished_at: '2026-11-23T10:02:00Z', details: { seconds: 120, audio_seconds: 1500, speakers: 4 }, launch: { preset: 'qwen', settings: {}, gpus: [1] } })
  }
  await page.route('**/api/jobs/*/inputs/*', (route) => route.fulfill({ status: 200, contentType: 'video/webm', body: readFileSync(new URL('./fixtures/black-start.webm', import.meta.url)) }))
  await page.route('**/api/jobs/*/files/notes.md', (route) => route.fulfill({ status: 200, contentType: 'text/markdown', body: '# Meeting notes\n\n## Action items\n\n- [ ] Send the plan — Ben (00:20)\n' }))
  await page.route('**/api/jobs/*/files/transcript.md', (route) => route.fulfill({ status: 200, contentType: 'text/markdown', body: '# Transcript\n\n**[00:00] Speaker 1 (Anna):** Hello, everyone.\n' }))
  await page.route('**/api/jobs/*/files/*.csv', (route) => route.fulfill({ status: 200, contentType: 'text/csv', body: 'Task,Owner\n' }))
  await page.route('**/api/jobs/*/files/*.srt', (route) => route.fulfill({ status: 200, contentType: 'application/x-subrip', body: '1\n' }))
  await page.route('**/api/jobs/*/files/meeting.json', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ revision: 1, speakers: { 'Speaker 1': 'Anna' }, segments: [
    { speaker: 'Speaker 1', start: 0, end: 4, text: 'Hello, everyone.' }, { speaker: 'Ben', start: 5, end: 9, text: 'Send the plan.' }, { speaker: 'Speaker 1', start: 10, end: 14, text: 'Thanks.' }] }) }))
  if (options.voiceClip) jobs.push({ id: 'job-00000099', model_id: 'minimax_h3', status: 'done', progress: 'Done in 39 s, seed 5', error_message: null,
    inputs: { mode: 'text', prompt: 'A woman with a soft Welsh accent sits in a kitchen. She says: "Come in and get warm."', quality: 'quick' },
    outputs: [{ name: 'video-1.mp4', mime: 'video/mp4', bytes: 24044 }], created_at: '2026-11-12T00:00:00Z', finished_at: '2026-11-12T00:00:39Z',
    details: { seed: 5, seconds: 39 }, launch: { preset: 'uncensored', settings: {}, gpus: [0] } })
  await page.route('**/api/jobs/*/files/video-1.mp4', (route) => route.fulfill({ status: 200, contentType: 'video/mp4', body: toneWav() }))
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
  return { profiles, models, operations, get postProfileBody() { return postProfileBody }, get loadProfileId() { return loadProfileId }, get startBody() { return startBody }, get jobBody() { return jobBody }, uploads, jobs }
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

/** Visible text set below 13px (the plan's floor); the 12px numbered chip on file tiles is the one exception. */
async function textUnder13px(page: Page) {
  return page.evaluate(() => {
    const found: string[] = []
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const element = node.parentElement
      if (!element || !node.textContent?.trim() || element.closest('.file-index, .sr-only, [hidden], option')) continue
      const style = getComputedStyle(element)
      const box = element.getBoundingClientRect()
      if (!box.width || !box.height || style.visibility === 'hidden') continue
      if (parseFloat(style.fontSize) < 13) found.push(`${parseFloat(style.fontSize)}px "${node.textContent.trim().slice(0, 30)}"`)
    }
    return found
  })
}

/** Model cards start folded on the Models page; open one to reach its choices, settings and history. */
async function openCard(page: Page, name: string) {
  await page.getByRole('button', { name: `Show details for ${name}` }).click()
}

async function go(page: Page, hash: string) {
  await page.evaluate((value) => { window.location.hash = value }, hash)
}

async function signIn(page: Page, value = token, address?: string) {
  await page.goto('/#/connections')
  if (address !== undefined) await page.getByLabel('Server address').fill(address)
  await page.getByLabel('Access token').fill(value)
  await page.getByRole('button', { name: 'Save and connect' }).click()
}

async function connectFixtures(page: Page, label = 'Fixture desktop', stale = false, options: { initialProfile?: boolean; refuseLoad?: boolean; initialState?: string; runtime?: boolean; refuseStart?: boolean; songs?: boolean; songState?: string; videos?: boolean; speech?: boolean; voiceClip?: boolean; chatReady?: boolean; thinking?: { levels: string[]; default: string | null; off: boolean }; llm?: boolean; rated?: boolean; meeting?: boolean } = {}) {
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
  await expect(nav.getByText('Fixture desktop')).toBeVisible()
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
  await expect(nav.getByText('Proxmox')).toBeVisible()
  await expect(nav.getByText('Fixture desktop')).toBeVisible()
  const card = page.getByLabel('Host Proxmox')
  await card.getByRole('button', { name: 'Forget' }).click()
  await card.getByRole('button', { name: 'Forget it' }).click()
  await expect(nav.getByText('Proxmox')).toHaveCount(0)
  const saved = await page.evaluate(() => localStorage.getItem('generation-station.hosts') ?? '')
  expect(saved).not.toContain('second-host-token')
})

test('marks stale telemetry, blocks actions, and clears measurements on disconnect', async ({ page }) => {
  await connectFixtures(page, 'Fixture desktop', true, { songs: true, songState: 'unloaded' })
  await expect(page.getByText('Telemetry stale')).toBeVisible()
  await go(page, '#/hosts/local/models')
  await expect(page.getByRole('region', { name: 'YuE2 songs' }).getByRole('button', { name: 'Start', exact: true })).toBeDisabled()
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
  await expect.poll(() => pushFrame(page, host)).toBe(true)
  // The host is marked partial in words (its status dot is labelled), and the GPU card's own pill says
  // there is no VRAM figure at all: the only GPU reported no memory counters.
  await expect(page.getByRole('img', { name: 'Live · partial telemetry' })).toBeVisible()
  const gpuCard = page.getByRole('article').filter({ has: page.getByRole('heading', { name: 'Graphics memory' }) })
  await expect(gpuCard.locator('.capacity-label')).toHaveText('No data')
  await expect(gpuCard.getByText('Driver did not expose memory counters.')).toBeVisible()
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
  await expect(page.getByText('Stale').first()).toBeVisible({ timeout: 5000 })
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
  await expect(page.getByRole('navigation', { name: 'Settings' }).getByRole('link', { name: /Capacity test/ })).toHaveCount(0)
  const resources = page.getByLabel('Fixture desktop resource usage')
  await expect(resources.getByText('System memory')).toBeVisible()
  await expect(resources.getByText('Fixture GPU')).toBeVisible()
  // Folded: one row with Start; the description and choices appear when the card is opened.
  await expect(page.getByRole('region', { name: 'Basalt' }).getByRole('button', { name: 'Start', exact: true })).toBeVisible()
  await expect(page.getByText('Runs a large language model for chat and coding.')).toHaveCount(0)
  await openCard(page, 'Basalt')
  await expect(page.getByText('Runs a large language model for chat and coding.')).toBeVisible()
  await expect(page.getByText('Fixture note about Flash-Next.')).toHaveCount(0)
  await page.getByRole('radio', { name: 'Qwen3.8 Flash-Next' }).check()
  await expect(page.getByText('Fixture note about Flash-Next.')).toBeVisible()
  await page.getByRole('checkbox', { name: 'Second GPU' }).uncheck()
  const fit = page.getByLabel('Basalt if started')
  await expect(fit.locator('.runtime-fit-row').filter({ hasText: 'RAM' }).first()).toContainText('40 GiB needed, 16 GiB available24 GiB short')
  await expect(fit.locator('.runtime-fit-row').filter({ hasText: 'Fixture GPU VRAM' })).toContainText('24 GiB needed, 26 GiB availableFits')
  const ramPreview = page.getByRole('progressbar', { name: 'System memory used' }).getByLabel(/Basalt if started/)
  await expect(ramPreview).toHaveAttribute('data-tip', 'Basalt if started · needs 40 GiB · won’t fit')
  await expect(page.getByRole('progressbar', { name: 'Fixture GPU used' }).getByLabel('Basalt if started · needs 24 GiB')).toBeVisible()
  await expect(page.getByText(/A text model then uses whatever VRAM is free beyond what you leave free/)).toBeVisible()
  await page.getByRole('button', { name: 'Advanced settings' }).click()
  await page.getByLabel(/^vram left free on the main card/i).fill('1024')
  await page.getByLabel(/^kv cache precision/i).selectOption('q4_0')
  await page.getByLabel(/^keep overflow experts in ram/i).uncheck()
  await page.screenshot({ path: 'test-results/screenshots/model-server-advanced.png', fullPage: true })
  await page.getByRole('button', { name: 'Start', exact: true }).click()
  await expect(page.getByText('Ready.')).toBeVisible()
  expect(api.startBody).toEqual({ preset: 'fn', gpus: [0], settings: { kv: 'q4_0', vram_reserve_mib: 1024, resident_experts: false } })
  await expect(page.getByText('Running', { exact: true })).toBeVisible()
  // A short history is folded away under "History (n)"; open it to read the entry.
  await page.getByText('History (1)').click()
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
  await openCard(page, 'Basalt')
  await page.getByRole('button', { name: 'Advanced settings' }).click()
  await expect(page.getByText(/The RAM guard is off/)).toBeVisible()
  await page.getByLabel(/^vram left free on the main card/i).fill('100')
  await expect(page.getByText('At least 256.')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Start', exact: true })).toBeDisabled()
  await page.getByRole('button', { name: 'Reset to defaults' }).click()
  await expect(page.getByRole('button', { name: 'Start', exact: true })).toBeEnabled()
  await page.getByRole('checkbox', { name: 'Fixture GPU' }).uncheck()
  await page.getByRole('checkbox', { name: 'Second GPU' }).uncheck()
  await expect(page.getByText('Choose a card', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Start', exact: true })).toBeDisabled()
  expect(api.startBody).toBeNull()
})

test('shows a model server capacity refusal with the GPU name instead of its UUID', async ({ page }) => {
  await connectFixtures(page, 'Fixture desktop', false, { runtime: true, refuseStart: true })
  await go(page, '#/hosts/local/models')
  await page.getByRole('button', { name: 'Start', exact: true }).click()
  const refusal = page.getByRole('alert').filter({ hasText: 'INSUFFICIENT_VRAM' })
  await expect(refusal).toBeVisible()
  expect(await textUnder13px(page)).toEqual([])
  await expect(refusal).toBeVisible()
  await expect(refusal.getByText('Fixture GPU')).toBeVisible()
  await expect(refusal.getByText('Required 24 GiB')).toBeVisible()
  await expect(page.getByText(gpuUuid)).toHaveCount(0)
})

test('makes a song, keeps it in the sidebar with how it was made, reuses its settings and deletes it', async ({ page }) => {
  const api = await connectFixtures(page, 'Fixture desktop', false, { songs: true })
  await go(page, '#/hosts/local/models')
  await openCard(page, 'YuE2 songs')
  await expect(page.getByRole('radio', { name: 'Second GPU' })).toBeChecked()
  await page.getByRole('link', { name: 'Open YuE2 songs' }).click()
  await expect(page).toHaveURL(/#\/hosts\/local\/services\/yue2$/)
  await expect(page.getByText('Running', { exact: true })).toBeVisible()
  await expect(page.getByRole('radio')).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Stop', exact: true })).toHaveCount(0)
  const form = page.getByRole('form', { name: 'Make a song' })
  await expect(form.getByRole('button', { name: 'Make a song' })).toBeDisabled()
  await form.getByLabel(/^style/i).fill('Upbeat indie pop, female vocals')
  await form.getByLabel(/^lyrics/i).fill('[Verse]\nSunlight on the kitchen floor\n\n[Chorus]\nSing it back to me')
  await form.getByRole('button', { name: 'More options' }).click()
  await form.getByLabel(/^seed/i).fill('42')
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
  expect(await textUnder13px(page)).toEqual([])
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
  await expect(detail.getByText('Sing it back to me')).toBeHidden() // the settings are folded away until asked for
  await detail.getByText('Settings and model').click()
  await expect(detail.getByText('Sing it back to me')).toBeVisible()
  await expect(detail.getByText('YuE2 3B')).toBeVisible()
  await expect(detail.getByText('Second GPU')).toBeVisible()
  await page.screenshot({ path: 'test-results/screenshots/song-result.png' })
  expect(await textUnder13px(page)).toEqual([])
  await modal.getByRole('button', { name: 'Close' }).click()
  await expect(modal).toBeHidden()
  await page.screenshot({ path: 'test-results/screenshots/song-rail.png', fullPage: true })
  await go(page, '#/overview')
  await expect(page.getByText('Recent results')).toBeVisible()
  await go(page, '#/hosts/local/services/yue2')
  await form.getByLabel(/^style/i).fill('changed')
  await item.click()
  await detail.getByRole('button', { name: 'Use these settings' }).click()
  await expect(modal).toBeHidden()
  await expect(form.getByLabel(/^style/i)).toHaveValue('Upbeat indie pop, female vocals')
  await expect(form.getByLabel(/^seed/i)).toHaveValue('42')
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
  await form.getByLabel(/^style/i).fill('First song')
  await form.getByLabel(/^lyrics/i).fill('la')
  await form.getByRole('button', { name: 'Make a song' }).click()
  await form.getByLabel(/^style/i).fill('Second song')
  await expect(form.getByText('One is ahead in the queue; this one starts after it.')).toBeVisible()
  await form.getByRole('button', { name: 'Add to queue' }).click()
  const rail = page.getByRole('complementary', { name: 'Your songs' })
  const second = rail.getByRole('button', { name: /^Second song/ })
  await expect(rail.getByRole('button', { name: /^First song/ })).toContainText('Composing · Composing the song')
  await expect(second).toContainText('Queued · next')
  await expect(rail.getByText('1 composing · 1 queued')).toBeVisible()
  await page.screenshot({ path: 'test-results/screenshots/song-queue.png' })
  expect(await textUnder13px(page)).toEqual([])
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
  await textPanel.getByLabel(/^description/i).fill('kept while I switch tabs')
  await expect(textPanel.getByLabel(/^custom width/i)).toHaveCount(0)
  await textPanel.getByLabel(/^resolution/i).selectOption('custom')
  await expect(textPanel.getByLabel(/^custom width/i)).toHaveValue('960')
  await expect(textPanel.getByLabel(/^custom height/i)).toHaveValue('540')  // re-derived from 16:9
  await textPanel.getByLabel(/^custom width/i).fill('1280')
  await expect(textPanel.getByLabel(/^custom height/i)).toHaveValue('720')
  await textPanel.getByLabel(/^custom height/i).fill('360')
  await expect(textPanel.getByLabel(/^custom width/i)).toHaveValue('640')
  await textPanel.getByLabel(/^shape/i).selectOption('square 1:1')
  await expect(textPanel.getByLabel(/^custom height/i)).toHaveValue('640')
  await textPanel.getByRole('button', { name: 'Locked to the shape’s proportions' }).click()
  await textPanel.getByLabel(/^custom width/i).fill('800')
  await expect(textPanel.getByLabel(/^custom height/i)).toHaveValue('640')  // unlocked: unchanged
  await textPanel.getByLabel(/^custom width/i).fill('100')
  await expect(textPanel.getByRole('button', { name: 'Make a video' })).toBeDisabled()  // below the minimum
  await textPanel.getByLabel(/^resolution/i).selectOption('540p')
  await expect(textPanel.getByLabel(/^custom width/i)).toHaveCount(0)
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
  await expect(panel.getByText('commas give short pauses.')).toBeHidden()
  await panel.getByText('Writing guide').click()
  await expect(panel.getByText('commas give short pauses.')).toBeVisible()
  await expect(panel.locator('.field-guide strong').first()).toHaveText('Pauses:')
  await panel.getByLabel(/^what happens/i).fill('She turns toward the window and smiles.')
  await page.screenshot({ path: 'test-results/screenshots/video-from-pictures.png', fullPage: true })
  expect(await textUnder13px(page)).toEqual([])
  await panel.getByRole('button', { name: 'Make a video' }).click()
  await expect.poll(() => api.jobBody).not.toBeNull()
  expect(api.jobBody).toEqual({ inputs: { mode: 'frames', first: ['a'.repeat(31) + '1'], prompt: 'She turns toward the window and smiles.', shape: 'match picture', quality: 'quick' } })
  expect(api.uploads.map(({ name, type }) => ({ name, type }))).toEqual([{ name: 'start.png', type: 'image/png' }])
  await tabs.getByRole('tab', { name: 'From a description' }).click()
  await expect(page.getByRole('tabpanel', { name: 'From a description' }).getByLabel(/^description/i)).toHaveValue('kept while I switch tabs')
})

test('sends a clip\'s voice to a speech model as its sample, with the spoken line as the transcript', async ({ page }) => {
  const api = await connectFixtures(page, 'Fixture desktop', false, { videos: true, speech: true, voiceClip: true })
  await go(page, '#/hosts/local/services/minimax_h3')
  await page.getByRole('complementary').getByRole('button', { name: /^A woman with a soft Welsh accent/ }).click()
  const detail = page.getByRole('dialog').getByRole('article')
  await detail.getByRole('button', { name: 'Use voice in OmniVoice speech' }).click()
  await expect(page).toHaveURL(/#\/hosts\/local\/services\/omnivoice$/)
  await expect(page.getByRole('tab', { name: 'From a voice sample' })).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByRole('button', { name: 'Remove voice-job-0000.wav' })).toBeVisible()
  await expect(page.getByLabel(/^what the sample says/i)).toHaveValue('Come in and get warm.')
  expect(api.uploads.at(-1)).toMatchObject({ name: 'voice-job-0000.wav', type: 'audio/wav' })
  expect(api.uploads.at(-1)?.head).toMatch(/^RIFF.{4}WAVE$/s)
  await page.screenshot({ path: 'test-results/screenshots/voice-sample-handoff.png', fullPage: true })
})

test('frames a wide picture for a portrait clip on a preview: drag, keys and zoom', async ({ page }) => {
  const api = await connectFixtures(page, 'Fixture desktop', false, { videos: true })
  await go(page, '#/hosts/local/services/minimax_h3')
  await page.getByRole('tab', { name: 'From pictures' }).click()
  const panel = page.getByRole('tabpanel', { name: 'From pictures' })
  const [chooser] = await Promise.all([page.waitForEvent('filechooser'), panel.getByRole('button', { name: 'Add picture: First frame' }).click()])
  await chooser.setFiles({ name: 'wide.png', mimeType: 'image/png', buffer: readFileSync(new URL('./fixtures/wide.png', import.meta.url)) })
  await expect(panel.getByRole('slider', { name: /Framing for First frame/ })).toHaveCount(0)  // 'match picture' needs no framing
  await expect(panel.getByLabel(/^shape/i).locator('option:checked')).toHaveText('Match picture')
  await panel.getByLabel(/^shape/i).selectOption('portrait 9:16')
  await expect(panel.getByLabel(/^shape/i).locator('option:checked')).toHaveText('Portrait 9:16')
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
  expect(await textUnder13px(page)).toEqual([])
  await panel.getByLabel(/^what happens/i).fill('The sun sets.')
  await panel.getByRole('button', { name: 'Make a video' }).click()
  await expect.poll(() => api.jobBody).not.toBeNull()
  const inputs = (api.jobBody as unknown as { inputs: Record<string, string> }).inputs
  expect(inputs.shape).toBe('portrait 9:16')
  const [x, y, w, h] = inputs.first_crop.split(',').map(Number)
  expect(w * 40 / (h * 20)).toBeCloseTo(9 / 16, 2)
  // zooming keeps the centre the box was dragged to
  expect([x + w / 2, y, h]).toEqual([expect.closeTo(0.8594, 3), expect.closeTo(0.25, 3), expect.closeTo(0.5, 3)])
  await panel.getByLabel(/^shape/i).selectOption('landscape 16:9')
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

test('leaves a model\'s error out of the sidebar', async ({ page }) => {
  await connectFixtures(page, 'Fixture desktop', false, { songs: true, songState: 'error' })
  await go(page, '#/hosts/local/overview')
  const link = page.getByRole('navigation').getByRole('link', { name: 'YuE2 songs' })
  await expect(link).toBeVisible()
  await expect(link).toHaveAttribute('title', 'YuE2 songs')
  await expect(link.getByText('Error')).toHaveCount(0)
})

test('shows each running model\'s share of RAM and VRAM in the bars and on its card', async ({ page }) => {
  await connectFixtures(page, 'Fixture desktop', false, { songs: true })
  const withUsage = { ...fixtureHost(), sequence: 2, model_memory: { yue2: { ram_bytes: 6 * 1024 ** 3, gpus: { [gpuUuid]: 3 * 1024 ** 3 }, error: null } } }
  await expect.poll(() => pushFrame(page, withUsage)).toBe(true)
  await go(page, '#/hosts/local/models')
  await openCard(page, 'YuE2 songs')
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
  await openCard(page, 'YuE2 songs')
  await expect(page.getByRole('status').filter({ hasText: 'Restart the Generation Station service' })).toBeVisible()
})

test('keeps host memory pinned beside the model list while scrolling on a wide screen', async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 700 })
  await connectFixtures(page, 'Fixture desktop', false, { runtime: true, songs: true, songState: 'unloaded' })
  await keepFresh(page)
  await go(page, '#/hosts/local/models')
  const rail = page.getByLabel('Fixture desktop resource usage')
  await expect(rail.getByText('System memory')).toBeVisible()
  await openCard(page, 'Basalt')  // open both, so the page is long enough to scroll
  await openCard(page, 'YuE2 songs')
  await expect(page.getByRole('region', { name: 'YuE2 songs' }).getByLabel('YuE2 songs if started', { exact: true })).toBeVisible()
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

test('groups the sidebar by what each model makes, with running shown in words', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await connectFixtures(page, 'Fixture desktop', false, { songs: true, videos: true, speech: true })
  await go(page, '#/hosts/local/services/omnivoice')
  const nav = page.getByRole('navigation', { name: 'Main navigation' })
  const groups = nav.getByRole('group')
  await expect(groups).toHaveCount(3)
  expect(await groups.evaluateAll((items) => items.map((item) => item.getAttribute('aria-labelledby') && document.getElementById(item.getAttribute('aria-labelledby')!)?.textContent))).toEqual(['Speech', 'Video', 'Music'])
  await expect(nav.getByRole('group', { name: 'Speech' }).getByRole('link', { name: /OmniVoice speech/ })).toHaveAttribute('aria-current', 'page')
  await expect(nav.getByRole('link', { name: /OmniVoice speech/ })).toContainText('On')
  await page.screenshot({ path: 'test-results/screenshots/sidebar-groups.png', fullPage: true })
  // Keyboard focus shows the accent ring on every nav link, in order.
  const links = await nav.getByRole('link').count()
  const inNav = () => page.evaluate(() => !!document.activeElement?.closest('nav'))
  await nav.getByRole('link').first().focus()
  await page.keyboard.press('Shift+Tab')
  for (let step = 0; step < 10 && !(await inNav()); step++) await page.keyboard.press('Tab')
  for (let index = 0; index < links; index++) {
    if (index > 0) await page.keyboard.press('Tab')
    const ring = await page.evaluate(() => { const element = document.activeElement as HTMLElement; const style = getComputedStyle(element); return element.closest('nav') ? `${style.outlineStyle} ${style.outlineWidth} ${style.outlineColor}` : `not in nav: ${element.tagName}` })
    expect(ring).toBe('solid 2px rgb(90, 63, 212)')
  }
  await page.setViewportSize({ width: 900, height: 900 })
  await expect(nav.getByRole('link', { name: /OmniVoice speech/ })).toBeVisible()
  await page.screenshot({ path: 'test-results/screenshots/sidebar-rail.png' })
})

test.describe('on a phone', () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true })

  test('opens the navigation drawer from the Menu button, keeps focus in it and closes it every way', async ({ page }) => {
    await connectFixtures(page, 'Fixture desktop', false, { songs: true, speech: true })
    await go(page, '#/hosts/local/services/yue2')
    await expect(page.getByRole('heading', { name: 'YuE2 songs', level: 1 })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390)
    const menu = page.getByRole('button', { name: 'Menu' })
    const nav = page.getByRole('navigation', { name: 'Main navigation' })
    await expect(menu).toHaveAttribute('aria-expanded', 'false')
    await expect(nav).toBeHidden()

    await menu.click()
    await expect(menu).toHaveAttribute('aria-expanded', 'true')
    await expect(nav.getByRole('link', { name: /YuE2 songs/ })).toBeVisible()
    await expect.poll(() => page.evaluate(() => !!document.activeElement?.closest('#sidebar'))).toBe(true)
    await expect.poll(() => page.locator('#sidebar').evaluate((element) => element.getBoundingClientRect().left)).toBe(0)  // slid fully in
    await page.screenshot({ path: 'test-results/screenshots/phone-drawer.png' })
    // Focus stays inside while it is open.
    await page.keyboard.press('Shift+Tab')
    expect(await page.evaluate(() => !!document.activeElement?.closest('#sidebar'))).toBe(true)
    for (let step = 0; step < 12; step++) await page.keyboard.press('Tab')
    expect(await page.evaluate(() => !!document.activeElement?.closest('#sidebar'))).toBe(true)
    await page.keyboard.press('Escape')
    await expect(nav).toBeHidden()
    await expect(menu).toBeFocused()

    await menu.click()
    await page.mouse.click(380, 400)  // the backdrop beside the drawer
    await expect(nav).toBeHidden()
    await expect(menu).toBeFocused()

    await menu.click()
    await nav.getByRole('link', { name: 'Overview' }).click()
    await expect(page.getByRole('heading', { name: 'Overview', level: 1 })).toBeVisible()
    await expect(nav).toBeHidden()
    await expect(menu).toHaveAttribute('aria-expanded', 'false')
  })

  test('gives every control a 44px touch target and the results text at least half of its row', async ({ page }) => {
    await connectFixtures(page, 'Fixture desktop', false, { songs: true })
    await go(page, '#/hosts/local/services/yue2')
    const form = page.getByRole('form', { name: 'Make a song' })
    await form.getByLabel(/^style/i).fill('Upbeat indie pop, female vocals')
    await form.getByLabel(/^lyrics/i).fill('la la')
    await form.getByRole('button', { name: 'More options' }).click()
    await form.getByRole('button', { name: 'Make a song' }).click()
    const rail = page.getByRole('complementary', { name: 'Your songs' })
    await expect(rail.getByRole('button', { name: /^Upbeat indie pop/ })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390)
    const small = await page.evaluate(() => {
      const selector = 'main button, main [role=tab], main select, main input:not([type=checkbox]):not([type=radio]):not([type=file]), main textarea, main summary, main a.button, main a.text-button, header button'
      return Array.from(document.querySelectorAll<HTMLElement>(selector)).filter((element) => {
        const box = element.getBoundingClientRect()
        if (!box.width || !box.height) return false
        // A control may draw small and take touches on a larger ::before.
        const before = getComputedStyle(element, '::before')
        const grow = before.content !== 'none' && before.position === 'absolute' ? 16 : 0
        return box.width + grow < 44 || box.height + grow < 44
      }).map((element) => `${element.tagName} ${element.getAttribute('aria-label') ?? element.textContent?.trim().slice(0, 30)}`)
    })
    expect(small).toEqual([])
    const share = await rail.locator('.result-row').first().evaluate((row) => row.querySelector('.result-text')!.getBoundingClientRect().width / row.getBoundingClientRect().width)
    expect(share).toBeGreaterThanOrEqual(0.5)
  })
})

/** A canned answer stream, the way the host sends a chat turn. */
function chatStream(events: Array<[string, unknown]>) {
  return events.map(([event, data]) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join('')
}

function chatMessage(id: string, position: number, role: string, extra: Record<string, unknown> = {}) {
  return { id, position, role, content: '', reasoning: null, attachments: [], tool_calls: [], tool_call_id: null, job_id: null, status: 'done', error_message: null, created_at: '2026-11-22T10:00:00Z', ...extra }
}

test('chats with the text model, which starts a song; conversations can be attached to, renamed and deleted', async ({ page }) => {
  const api = await connectFixtures(page, 'Fixture desktop', false, { runtime: true, chatReady: true, songs: true, voiceClip: true })
  await keepFresh(page)
  const conversation = { id: 'conv-1', title: 'New conversation', model_id: 'basalt', created_at: '2026-11-22T10:00:00Z', updated_at: '2026-11-22T10:00:00Z', busy: false }
  const conversations: Array<typeof conversation> = []
  const messages: Array<Record<string, unknown>> = []
  let sent: Record<string, unknown> | null = null
  await page.route('**/api/conversations', async (route) => {
    if (route.request().method() === 'POST') { conversations.unshift(conversation); await route.fulfill({ status: 201, json: conversation }); return }
    await route.fulfill({ json: { conversations } })
  })
  await page.route('**/api/conversations/conv-1', async (route) => {
    const method = route.request().method()
    if (method === 'PUT') { conversation.title = (route.request().postDataJSON() as { title: string }).title; await route.fulfill({ json: conversation }); return }
    if (method === 'DELETE') { conversations.splice(0); await route.fulfill({ json: { id: 'conv-1', deleted: true } }); return }
    await route.fulfill({ json: { conversation, messages } })
  })
  await page.route('**/api/conversations/conv-1/messages', async (route) => {
    sent = route.request().postDataJSON() as Record<string, unknown>
    conversation.title = 'Write me a short song'
    const song = { id: 'job-00000042', model_id: 'yue2', status: 'queued', progress: null, error_message: null, inputs: { mode: 'full', style: 'dream pop', lyrics: '[Verse]\nla' }, outputs: [], created_at: '2026-11-22T10:00:01Z', finished_at: null }
    api.jobs.unshift(song)
    const user = chatMessage('m1', 1, 'user', { content: 'Write me a short song', attachments: [{ job_id: 'job-00000099', name: 'video-1.mp4', mime: 'video/mp4', model_id: 'minimax_h3' }] })
    const call = chatMessage('m2', 2, 'assistant', { reasoning: 'They want a song.', tool_calls: [{ id: 'c1', name: 'make_yue2__full', arguments: '{}' }] })
    const tool = chatMessage('m3', 3, 'tool', { content: 'Started job job-0000 on YuE2 songs.', tool_call_id: 'c1', job_id: song.id })
    const started = chatMessage('m3b', 3, 'tool', { content: 'YuE2 songs is running on the RTX 4080 (ready in 12 s). Its tools are available now.', note: 'Started YuE2 songs on the RTX 4080', tool_call_id: 'c0' })
    const reply = chatMessage('m4', 4, 'assistant', { content: 'I started a **dream pop** song:\n\n- verse\n- chorus' })
    const shown = chatMessage('m5', 5, 'tool', { content: 'Shown in the chat: job-0000.', note: 'Showing 1 result', tool_call_id: 'c2', attachments: [{ job_id: 'job-00000099', name: 'video-1.mp4' }] })
    messages.push(user, call, started, tool, reply, shown)
    await route.fulfill({ status: 200, contentType: 'text/event-stream', body: chatStream([
      ['message', user], ['start', {}], ['delta', { reasoning: 'They want a song.' }], ['delta', { tool: 'make_yue2__full' }], ['message', call],
      ['status', { text: 'Starting YuE2 songs on the RTX 4080…' }], ['message', started],
      ['message', { ...tool, job: song }], ['start', {}], ['delta', { content: 'I started a **dream pop** song:' }], ['message', reply], ['message', shown], ['done', {}],
    ]) })
  })

  await expect(page.getByRole('navigation').getByRole('group', { name: 'Text' }).getByRole('link', { name: /^Chat/ })).toBeVisible()
  await go(page, '#/hosts/local/chat')
  await expect(page.getByRole('heading', { name: 'What would you like to talk about?' })).toBeVisible()
  await expect(page.getByText('YuE2 songs', { exact: false }).first()).toBeVisible()

  // Attach an earlier clip from the picker.
  await page.getByRole('button', { name: 'Attach', exact: true }).click()
  const picker = page.getByRole('dialog', { name: 'Attach results' })
  await picker.getByRole('button', { name: /^A woman with a soft Welsh accent/ }).click()
  await picker.getByRole('button', { name: 'Attach', exact: true }).click()
  await expect(page.getByRole('button', { name: /^Remove A woman with a soft Welsh accent/ })).toBeVisible()

  await page.getByLabel('Message').fill('Write me a short song')
  await page.getByLabel('Message').press('Enter')
  await expect(page).toHaveURL(/#\/hosts\/local\/chat\/conv-1$/)
  expect(sent).toEqual({ text: 'Write me a short song', attachments: [{ job_id: 'job-00000099', name: 'video-1.mp4' }], thinking: true })
  await expect(page.getByLabel('Thinking')).toHaveCount(0) // a model without known levels offers none
  const thread = page.locator('.chat-thread')
  await expect(thread.getByText('Write me a short song')).toBeVisible()
  await expect(thread.getByRole('button', { name: /Video · job-0000/ })).toBeVisible()
  await expect(thread.locator('strong', { hasText: 'dream pop' })).toBeVisible()
  await expect(thread.getByRole('listitem').filter({ hasText: 'chorus' })).toBeVisible()
  await expect(thread.getByText('Thinking', { exact: true })).toBeVisible()
  await expect(thread.getByText('Started YuE2 songs on the RTX 4080')).toBeVisible()
  await expect(thread.getByText(/ready in 12 s/)).toHaveCount(0)
  // The song the model started shows its progress and then plays in the chat.
  const card = thread.locator('.chat-job')
  await expect(card.getByText('YuE2 songs')).toBeVisible()
  await expect(card.getByLabel('Play dream pop')).toBeVisible({ timeout: 20_000 })
  // A result the model shows from earlier is a card too, playable in place.
  const shownCards = thread.getByLabel('Showing 1 result').locator('.chat-job')
  await expect(shownCards).toHaveCount(1)
  await expect(shownCards.locator('video')).toBeVisible()
  await expect(page.getByRole('complementary', { name: 'Conversations' }).getByRole('link', { name: /Write me a short song/ })).toHaveAttribute('aria-current', 'page')
  await page.screenshot({ path: 'test-results/screenshots/chat.png', fullPage: true })

  // Rename, then delete.
  await page.getByRole('button', { name: 'Rename' }).click()
  await page.getByLabel('Conversation name').fill('Song ideas')
  await page.getByLabel('Conversation name').press('Enter')
  await expect(page.getByRole('heading', { name: 'Song ideas' })).toBeVisible()
  await page.getByRole('button', { name: 'Delete Song ideas' }).click()
  await page.getByRole('button', { name: 'Delete', exact: true }).click()
  await expect(page).toHaveURL(/#\/hosts\/local\/chat$/)
  await expect(page.getByText('No conversations yet.')).toBeVisible()

  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: 'test-results/screenshots/chat-phone.png', fullPage: true })
})

test('offers only the thinking levels the running model takes, sends the chosen one and remembers it', async ({ page }) => {
  await connectFixtures(page, 'Fixture desktop', false, { runtime: true, chatReady: true, thinking: { levels: ['low', 'high', 'max'], default: 'high', off: true } })
  const conversation = { id: 'conv-1', title: 'New conversation', model_id: 'basalt', created_at: '2026-11-22T10:00:00Z', updated_at: '2026-11-22T10:00:00Z', busy: false }
  let sent: Record<string, unknown> | null = null
  await page.route('**/api/conversations', (route) => route.request().method() === 'POST' ? route.fulfill({ status: 201, json: conversation }) : route.fulfill({ json: { conversations: [conversation] } }))
  await page.route('**/api/conversations/conv-1', (route) => route.fulfill({ json: { conversation, messages: [] } }))
  await page.route('**/api/conversations/conv-1/messages', async (route) => {
    sent = route.request().postDataJSON() as Record<string, unknown>
    await route.fulfill({ status: 200, contentType: 'text/event-stream', body: chatStream([['done', {}]]) })
  })
  await go(page, '#/hosts/local/chat')
  const picker = page.getByLabel('Thinking')
  await expect(picker).toHaveValue('high')
  expect(await picker.locator('option').allTextContents()).toEqual(['Off', 'Low', 'High (default)', 'Max'])
  await expect(page.getByRole('button', { name: 'Think first' })).toHaveCount(0)
  await picker.selectOption('max')
  await page.getByLabel('Message').fill('Hard question')
  await page.getByLabel('Message').press('Enter')
  await expect.poll(() => sent).toEqual({ text: 'Hard question', attachments: [], thinking: 'max' })
  await go(page, '#/hosts/local/models')
  await go(page, '#/hosts/local/chat')
  await expect(page.getByLabel('Thinking')).toHaveValue('max')
})

test('a meeting\'s notes show on the page, the transcript folds out, and every file downloads', async ({ page }) => {
  await connectFixtures(page, 'Fixture desktop', false, { meeting: true })
  await go(page, '#/hosts/local/services/meeting_notes')
  await expect(page.getByRole('navigation').getByRole('group', { name: 'Text' }).getByRole('link', { name: /Meeting notes/ })).toBeVisible()
  await page.getByRole('button', { name: /call\.webm|meeting|job-0000/i }).first().click()
  const notes = page.getByRole('region', { name: 'Notes' })
  await expect(notes.getByRole('heading', { name: 'Action items' })).toBeVisible()
  await expect(notes.getByText('Send the plan — Ben (00:20)')).toBeVisible()
  await expect(page.getByText('Hello, everyone.')).toBeHidden()
  await page.getByText('Transcript', { exact: true }).click()
  await expect(page.getByText('Hello, everyone.')).toBeVisible()
  // Eight files are two menus; the recording is the link under References, not a button of its own.
  await expect(page.getByRole('link', { name: 'transcript.md' })).toHaveCount(0)
  const files: Record<string, [string, string]> = {
    'Download transcript': ['transcript.md', 'Readable text (.md)'], 'Download notes': ['actions.csv', 'Action items, for a spreadsheet (.csv)'],
  }
  for (const [menu, [name, label]] of Object.entries(files)) {
    await page.getByRole('button', { name: menu }).click()
    await expect(page.getByRole('link', { name: label })).toHaveAttribute('download', name)
    await page.keyboard.press('Escape')
    await expect(page.getByRole('link', { name: label })).toHaveCount(0)
  }
  await page.getByRole('button', { name: 'Download transcript' }).click()
  await expect(page.getByRole('list', { name: 'Download transcript' }).getByRole('link')).toHaveCount(2) // this job has the text and the captions, no raw file
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: 'Download notes' }).click()
  await expect(page.getByRole('list', { name: 'Download notes' }).getByRole('link')).toHaveCount(4)
  await expect(page.getByRole('button', { name: /^Recording/ })).toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'References' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'call.webm' })).toHaveAttribute('download', 'call.webm')
  // Delete sits in the header, beside the status.
  const head = page.locator('.job-head')
  await expect(head.getByRole('button', { name: 'Delete' })).toBeVisible()
})

test('a recording that opens on black gets a thumbnail from a later frame', async ({ page }) => {
  await connectFixtures(page, 'Fixture desktop', false, { meeting: true })
  await go(page, '#/hosts/local/services/meeting_notes')
  await page.getByRole('button', { name: /call\.webm|meeting|job-0000/i }).first().click()
  const thumb = page.getByRole('link', { name: 'call.webm' }).getByRole('img')
  await expect(thumb).toBeVisible()
  const brightness = await thumb.evaluate(async (image: HTMLImageElement) => {
    await image.decode()
    const canvas = document.createElement('canvas')
    canvas.width = image.naturalWidth; canvas.height = image.naturalHeight
    const context = canvas.getContext('2d')!
    context.drawImage(image, 0, 0)
    const { data } = context.getImageData(0, 0, canvas.width, canvas.height)
    let sum = 0
    for (let i = 0; i < data.length; i += 4) sum += 0.2126 * data[i] + 0.7152 * data[i + 1] + 0.0722 * data[i + 2]
    return sum / (data.length / 4)
  })
  expect(brightness).toBeGreaterThan(25) // the first three seconds of this clip are black
})

test('a meeting transcript can be edited: rename a speaker everywhere, or fix one segment, and save', async ({ page }) => {
  await connectFixtures(page, 'Fixture desktop', false, { meeting: true })
  const saved: unknown[] = []
  await page.route('**/api/jobs/*/transcript', async (route) => { saved.push(route.request().postDataJSON()); await route.fulfill({ status: 200, json: { revision: 2, segments: 3 } }) })
  await go(page, '#/hosts/local/services/meeting_notes')
  await page.getByRole('button', { name: /call\.webm|meeting|job-0000/i }).first().click()
  await page.getByRole('button', { name: 'Edit transcript' }).click()
  const editor = page.getByRole('region', { name: 'Edit transcript' })
  await expect(editor.getByRole('button', { name: 'Save changes' })).toBeDisabled()
  await editor.getByRole('textbox', { name: 'Name for Speaker 1' }).fill('Ivan Cole')
  await expect(editor.getByRole('combobox', { name: 'Speaker of segment 1' })).toHaveValue('Ivan Cole')
  await expect(editor.getByRole('combobox', { name: 'Speaker of segment 3' })).toHaveValue('Ivan Cole')
  await expect(editor.getByRole('combobox', { name: 'Speaker of segment 2' })).toHaveValue('Ben')
  await editor.getByRole('textbox', { name: 'Words of segment 2' }).fill('Send the plan by Friday.')
  await expect(editor.getByText('3 segments changed')).toBeVisible()
  await editor.getByRole('button', { name: 'Save changes' }).click()
  await expect(editor).toHaveCount(0)
  expect(saved).toEqual([{ revision: 1, rename: { 'Speaker 1': 'Ivan Cole' }, segments: [{ index: 1, text: 'Send the plan by Friday.' }] }])
  // One segment moved to another speaker is a per-segment edit, not a rename.
  await page.getByRole('button', { name: 'Edit transcript' }).click()
  await editor.getByRole('combobox', { name: 'Speaker of segment 3' }).fill('Ben')
  await editor.getByRole('button', { name: 'Save changes' }).click()
  await expect(editor).toHaveCount(0)
  expect(saved[1]).toEqual({ revision: 1, rename: {}, segments: [{ index: 2, speaker: 'Ben' }] })
})

test('meeting notes can be edited, and what changed shows in a history', async ({ page }) => {
  await connectFixtures(page, 'Fixture desktop', false, { meeting: true })
  const record = { revision: 1, speakers: {}, segments: [{ speaker: 'Ben', start: 0, end: 4, text: 'Send the plan.' }], summary: ['Launch is Friday.', 'Budget is fine.'],
    actions: [{ task: 'Send the plan', owner: 'Ben', time: '00:20' }], decisions: [{ decision: 'Ship Friday', by: 'Sam' }], history: [] as unknown[] }
  await page.route('**/api/jobs/*/files/meeting.json', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(record) }))
  const saved: unknown[] = []
  await page.route('**/api/jobs/*/notes', async (route) => {
    saved.push(route.request().postDataJSON())
    record.revision = 2
    record.history = [{ revision: 2, at: '2026-11-26T15:04:00+00:00', changes: [
      { section: 'summary', kind: 'changed', before: 'Launch is Friday.', after: 'Launch is Monday.' },
      { section: 'actions', kind: 'added', before: null, after: 'Book the room — Dana' }] }]
    await route.fulfill({ status: 200, json: { revision: 2, changes: 2 } })
  })
  await go(page, '#/hosts/local/services/meeting_notes')
  await page.getByRole('button', { name: /call\.webm|meeting|job-0000/i }).first().click()
  // Nobody has edited it yet, so there is no history.
  await expect(page.getByText('Change history')).toHaveCount(0)
  await page.getByRole('button', { name: 'Edit notes' }).click()
  const editor = page.getByRole('region', { name: 'Edit notes' })
  await expect(editor.getByRole('button', { name: 'Save changes' })).toBeDisabled()
  await editor.getByRole('textbox', { name: 'Summary point 1' }).fill('Launch is Monday.')
  await editor.getByRole('button', { name: 'Add an action item' }).click()
  await editor.getByRole('textbox', { name: 'Task of action item 2' }).fill('Book the room')
  await editor.getByRole('textbox', { name: 'Owner of action item 2' }).fill('Dana')
  await editor.getByRole('button', { name: 'Remove decision 1' }).click()
  await expect(editor.getByText('3 sections changed')).toBeVisible()
  await editor.getByRole('button', { name: 'Save changes' }).click()
  await expect(editor).toHaveCount(0)
  expect(saved).toEqual([{ revision: 1, summary: ['Launch is Monday.', 'Budget is fine.'],
    actions: [{ task: 'Send the plan', owner: 'Ben', time: '00:20' }, { task: 'Book the room', owner: 'Dana' }], decisions: [] }])
  // The history lists the change, newest first, with what it was before.
  await page.getByText('Change history').click()
  const entry = page.locator('.history-entry').first()
  await expect(entry).toContainText('Edit 1')
  await expect(entry.locator('del')).toHaveText('Launch is Friday.')
  await expect(entry.locator('ins').first()).toHaveText('Launch is Monday.')
  await expect(entry).toContainText('Added · Action items')
})

test('a transcript edit the host refuses stays open with the reason', async ({ page }) => {
  await connectFixtures(page, 'Fixture desktop', false, { meeting: true })
  await page.route('**/api/jobs/*/transcript', (route) => route.fulfill({ status: 409, json: { detail: { code: 'TRANSCRIPT_CHANGED', message: 'The transcript changed since you opened it. Reload it and edit again.' } } }))
  await go(page, '#/hosts/local/services/meeting_notes')
  await page.getByRole('button', { name: /call\.webm|meeting|job-0000/i }).first().click()
  await page.getByRole('button', { name: 'Edit transcript' }).click()
  const editor = page.getByRole('region', { name: 'Edit transcript' })
  await editor.getByRole('textbox', { name: 'Words of segment 1' }).fill('Hi all.')
  await editor.getByRole('button', { name: 'Save changes' }).click()
  await expect(editor.getByRole('alert')).toContainText('The transcript changed since you opened it')
  await editor.getByRole('button', { name: 'Cancel' }).click()
  await expect(editor).toHaveCount(0)
})

test('meeting notes keep their own sidebar entry when a chat model is configured, and take a transcript file', async ({ page }) => {
  await connectFixtures(page, 'Fixture desktop', false, { meeting: true, llm: true })
  await go(page, '#/hosts/local/services/meeting_notes')
  await expect(page.getByRole('navigation').getByRole('link', { name: /Meeting notes/ })).toBeVisible()
  await expect(page.getByRole('navigation').getByRole('link', { name: /Meeting notes/ })).toHaveCount(1)
  await expect(page.locator('input[type=file]').first()).toHaveAttribute('accept', /\.vtt/)
})

test('a Mac with shared memory shows one memory pool and never a separate VRAM figure', async ({ page }) => {
  await connectFixtures(page, 'Fixture Mac', false, { runtime: true })
  const gib = 1024 ** 3
  const mac = { ...fixtureHost('Fixture Mac'), ram: { total_bytes: 64 * gib, available_bytes: 30 * gib, used_bytes: 34 * gib },
    gpus: [{ id: 'apple-unified-memory', index: 0, name: 'Apple M5 Max (unified memory)', memory: { total_bytes: 64 * gib, available_bytes: 30 * gib, used_bytes: 34 * gib }, error: null, unified_memory: true }] }
  await expect.poll(() => pushFrame(page, mac)).toBe(true)
  await page.getByRole('link', { name: 'Overview' }).click()
  await expect(page.getByRole('heading', { name: 'System memory' })).toBeVisible()
  await expect(page.getByText('Unified memory · shared with the GPU')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Graphics memory' })).toHaveCount(0)
  await go(page, '#/hosts/local/models')
  await expect(page.getByRole('heading', { name: 'Models', level: 1 })).toBeVisible()
  await expect(page.getByText(/\d (B|KiB|MiB|GiB) VRAM/)).toHaveCount(0) // no "0 B VRAM" beside a model's RAM
})

test('a service restart that adds a model shows it after the stream reconnects, without reloading the page', async ({ page }) => {
  await connectFixtures(page, 'Fixture desktop', false, { songs: true })
  await go(page, '#/hosts/local/models')
  await expect(page.getByRole('region', { name: 'YuE2 songs' })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Basalt' })).toHaveCount(0)
  // The restarted service (same instance ID, kept in its database) now lists Basalt as well.
  await page.route('**/api/runtimes', (route) => route.fulfill({ json: { runtimes: [songRuntimeFixture(), runtimeFixture()] } }))
  await page.evaluate(() => window.dispatchEvent(new Event('gs:close-stream')))
  await expect.poll(() => streamCount(page), { timeout: 10_000 }).toBe(2)
  await expect.poll(() => pushFrame(page, fixtureHost())).toBe(true)
  await expect(page.getByRole('region', { name: 'Basalt' })).toBeVisible()
})

test('a text model shows its card choice and plain settings, with tuning folded away and no engine named', async ({ page }) => {
  await connectFixtures(page, 'Fixture desktop', false, { llm: true })
  await go(page, '#/hosts/local/models')
  const card = page.getByRole('region', { name: 'Inkling 2 Mini' })
  await expect(card).toBeVisible()
  // Folded: the row has Start, the cards to choose from and a fit verdict; the note and settings are inside.
  await expect(card.getByRole('button', { name: 'Start', exact: true })).toBeVisible()
  const gpus = card.getByRole('group', { name: 'GPUs' })
  await expect(gpus.getByRole('radio', { name: 'Second GPU' })).toBeChecked()
  await expect(card.getByText('The standard model on the second card.')).toHaveCount(0)
  await openCard(page, 'Inkling 2 Mini')
  await expect(card.getByText('Good quality. 60-90 tok/s. About 24 GiB of memory.')).toBeVisible() // one preset: no buttons, still the quality, speed and memory line
  await expect(card.getByRole('group', { name: 'Model' })).toHaveCount(0)
  await expect(card.getByText('The standard model on the second card.')).toBeVisible()
  await gpus.getByRole('radio', { name: 'Fixture GPU' }).check()
  await expect(card.getByText('An uncensored version on the first card.')).toBeVisible()
  await expect(card.getByText('The standard model on the second card.')).toHaveCount(0)
  await expect(card.getByLabel(/^Read pictures/)).toHaveValue('card')
  await expect(card.getByLabel(/^Memory precision/)).toHaveCount(0)
  await expect(card.getByLabel(/^Context length/)).toHaveCount(0)
  await card.getByRole('button', { name: 'Advanced settings' }).click()
  await expect(card.getByLabel(/^Memory precision/)).toBeVisible()
  await expect(card.getByLabel(/^Context length/)).toHaveValue('131072')
  await expect(card).not.toContainText(/basalt|strata/i)
  await page.screenshot({ path: 'test-results/screenshots/text-model-card.png', fullPage: true })
})

test('lists models in the sidebar order: text models first, then speech, pictures, video and music', async ({ page }) => {
  await connectFixtures(page, 'Fixture desktop', false, { llm: true, songs: true, speech: true, videos: true })
  await go(page, '#/hosts/local/models')
  await expect(page.getByRole('region', { name: 'Inkling 2 Mini' })).toBeVisible()
  const names = await page.locator('section.model-server').evaluateAll((nodes) => nodes.map((node) => node.getAttribute('aria-label')))
  const workloads = names.map((name) => /Inkling/.test(name ?? '') ? 'text' : /speech|OmniVoice/i.test(name ?? '') ? 'speech' : /H3|video/i.test(name ?? '') ? 'video' : /song|YuE/i.test(name ?? '') ? 'music' : 'other')
  expect(workloads).toEqual([...workloads].sort((a, b) => ['text', 'speech', 'image', 'video', 'music', 'other'].indexOf(a) - ['text', 'speech', 'image', 'video', 'music', 'other'].indexOf(b)))
  expect(workloads[0]).toBe('text')
  expect(new Set(workloads)).toEqual(new Set(['text', 'speech', 'video', 'music']))
})

test("keeps logs behind the gear: each start's outcome, its error, and the log's last lines", async ({ page }) => {
  await connectFixtures(page, 'Fixture desktop', false, { songs: true })
  const ok = 'yue2-11111111-1111-1111-1111-111111111111.log'
  const bad = 'yue2-22222222-2222-2222-2222-222222222222.log'
  const entry = (name: string, status: string, extra: Record<string, unknown> = {}) => ({ name, bytes: 2048, kind: 'yue2', modified_at: '2026-11-22T10:00:00Z',
    operation_id: name.slice(5, 41), model_id: 'yue2', action: 'load', status, error_code: null, error_message: null, started_at: '2026-11-22T10:00:00Z', ...extra })
  await page.route('**/api/logs', (route) => route.fulfill({ json: { logs: [
    entry(bad, 'failed', { error_code: 'WORKER_EXITED', error_message: 'The worker exited during the load.' }), entry(ok, 'ready')] } }))
  let asked = 0
  await page.route('**/api/logs/yue2-*', (route) => {
    asked = Number(new URL(route.request().url()).searchParams.get('lines'))
    return route.fulfill({ json: { name: bad, bytes: 2048, lines: ['loading YuE2', 'CUDA error: out of memory'], truncated: false } })
  })
  await go(page, '#/overview')
  const tools = page.getByRole('navigation', { name: 'Settings' })
  const gear = page.getByRole('button', { name: 'Settings' })
  if (await gear.getAttribute('aria-expanded') === 'true') await gear.click()
  await expect(tools).toHaveCount(0)
  await gear.click()
  await tools.getByRole('link', { name: 'Logs' }).click()
  await expect(page).toHaveURL(/#\/hosts\/local\/logs$/)
  const list = page.getByRole('complementary', { name: 'Logs' })
  await expect(list.getByRole('link')).toHaveCount(2)
  await expect(list.getByRole('link').first()).toContainText('YuE2 songs')
  await expect(list.getByRole('link').first()).toContainText('Failed to start')
  await expect(list.getByRole('link').first()).toContainText('The worker exited during the load.')
  await page.getByLabel('Only problems').check()
  await expect(list.getByRole('link')).toHaveCount(1)
  await list.getByRole('link').first().click()
  await expect(page).toHaveURL(new RegExp(`#/hosts/local/logs/${bad}$`))
  const view = page.getByRole('region', { name: 'YuE2 songs log' })
  await expect(view.getByText('WORKER_EXITED: The worker exited during the load.')).toBeVisible()
  await expect(view.locator('pre')).toHaveText('loading YuE2\nCUDA error: out of memory')
  expect(asked).toBe(500)
  await view.getByRole('combobox').selectOption('2000')
  await expect.poll(() => asked).toBe(2000)
  await page.screenshot({ path: 'test-results/screenshots/logs.png', fullPage: true })
})

test('keeps the search address in host settings: test it, then save it', async ({ page }) => {
  await connectFixtures(page, 'Fixture desktop', false, { songs: true })
  let stored = { searxng_url: 'http://env-searx:8080', searxng_source: 'environment' }
  const tested: string[] = []
  await page.route('**/api/settings', (route) => {
    if (route.request().method() === 'PUT') {
      stored = { searxng_url: (route.request().postDataJSON() as { searxng_url: string }).searxng_url.replace(/\/+$/, ''), searxng_source: 'settings' }
    }
    return route.fulfill({ json: stored })
  })
  await page.route('**/api/settings/test-search', (route) => {
    tested.push((route.request().postDataJSON() as { searxng_url: string }).searxng_url)
    return route.fulfill({ json: { ok: true, message: 'Works: 5 results for a test search, e.g. “Lighthouse - Wikipedia”.' } })
  })
  await go(page, '#/overview')
  const gear = page.getByRole('button', { name: 'Settings' })
  if (await gear.getAttribute('aria-expanded') !== 'true') await gear.click()
  await page.getByRole('navigation', { name: 'Settings' }).getByRole('link', { name: 'Host settings' }).click()
  await expect(page).toHaveURL(/#\/hosts\/local\/settings$/)
  const address = page.getByLabel('Search service address')
  await expect(address).toHaveValue('http://env-searx:8080')
  await expect(page.getByText("Set in this host's .env file")).toBeVisible()
  await expect(page.getByRole('button', { name: 'Save' })).toBeDisabled()
  await address.fill('http://searxng.example.lan/')
  await page.getByRole('button', { name: 'Test' }).click()
  await expect(page.getByRole('status')).toContainText('Works: 5 results')
  expect(tested).toEqual(['http://searxng.example.lan/'])
  await page.getByRole('button', { name: 'Save' }).click()
  await expect(page.getByRole('status')).toContainText('Saved. The chat uses it from its next answer.')
  await expect(address).toHaveValue('http://searxng.example.lan')
  await expect(page.getByText("Set in this host's .env file")).toHaveCount(0)
  await page.screenshot({ path: 'test-results/screenshots/host-settings.png', fullPage: true })
})

test('a model that also paints pictures labels each tab and result by what it makes', async ({ page }) => {
  await connectFixtures(page, 'Fixture desktop', false, { videos: true })
  await go(page, '#/hosts/local/services/minimax_h3')
  const tabs = page.getByRole('tablist', { name: 'How to make it' })
  await expect(page.getByRole('tabpanel', { name: 'From a description' }).getByRole('button', { name: /^Make a video/ })).toBeVisible()
  await tabs.getByRole('tab', { name: 'A picture' }).click()
  const panel = page.getByRole('tabpanel', { name: 'A picture' })
  await expect(panel.getByRole('button', { name: /^Make a picture/ })).toBeVisible()
  await expect(panel.getByLabel(/^size/i)).toHaveValue('4 MP')
  await expect(page.getByRole('heading', { name: 'Your results' })).toBeVisible()
})

test('the assistant bubble opens on every page but Chat, points to the Models page when no text model runs, and keeps one thread', async ({ page }) => {
  // Nothing running: the bubble names no model and links to the Models page to start one.
  await connectFixtures(page, 'Fixture desktop', false, { runtime: true, llm: true, songs: true })
  const thread = (id: string) => ({ conversation: { id, title: 'Assistant', kind: 'assistant', model_id: 'inkling2', created_at: '2026-11-23T10:00:00Z', updated_at: '2026-11-23T10:00:00Z', busy: false }, messages: [] })
  await page.route('**/api/assistant', (route) => route.fulfill({ json: thread('help-1') }))
  await go(page, '#/overview')
  await page.getByRole('button', { name: 'Open the assistant' }).click()
  const panel = page.getByRole('region', { name: 'Assistant' })
  await expect(panel.getByText('No text model is running.')).toBeVisible()
  await expect(panel.getByText(/Inkling|Basalt/)).toHaveCount(0)
  await expect(panel.getByLabel('Ask the assistant')).toBeDisabled()
  await panel.getByRole('link', { name: /Start one on the Models page/ }).click()
  await expect(page).toHaveURL(/#\/hosts\/local\/models/)
  await expect(panel).toHaveCount(0)
  await page.getByRole('button', { name: 'Open the assistant' }).click()
  await panel.getByRole('button', { name: 'Close the assistant' }).click()
  await expect(panel).toHaveCount(0)
  await go(page, '#/hosts/local/chat')
  await expect(page.getByRole('button', { name: 'Open the assistant' })).toHaveCount(0)
})

test('the assistant answers with the page in mind and can start over', async ({ page }) => {
  await connectFixtures(page, 'Fixture desktop', false, { runtime: true, chatReady: true, songs: true })
  await keepFresh(page)
  const conversation = (id: string) => ({ id, title: 'Assistant', kind: 'assistant', model_id: 'basalt', created_at: '2026-11-23T10:00:00Z', updated_at: '2026-11-23T10:00:00Z', busy: false })
  const messages: Array<Record<string, unknown>> = []
  let sent: Record<string, unknown> | null = null
  await page.route('**/api/assistant', (route) => route.fulfill({ json: { conversation: conversation('help-1'), messages } }))
  await page.route('**/api/assistant/new', (route) => route.fulfill({ json: { conversation: conversation('help-2'), messages: [] } }))
  await page.route('**/api/conversations/help-1', (route) => route.fulfill({ json: { conversation: conversation('help-1'), messages } }))
  await page.route('**/api/conversations/help-1/messages', async (route) => {
    sent = route.request().postDataJSON() as Record<string, unknown>
    const user = chatMessage('a1', 1, 'user', { content: 'How do I make a song?' })
    const reply = chatMessage('a2', 2, 'assistant', { content: 'On this page:\n\n1. Write the lyrics.\n2. Press **Make a song**.' })
    messages.push(user, reply)
    await route.fulfill({ status: 200, contentType: 'text/event-stream', body: chatStream([['message', user], ['start', {}], ['delta', { content: 'On this page:' }], ['message', reply], ['done', {}]]) })
  })
  await go(page, '#/hosts/local/services/yue2')
  await page.getByRole('button', { name: 'Open the assistant' }).click()
  const panel = page.getByRole('region', { name: 'Assistant' })
  await expect(panel.getByText('Hi! I can explain how Generation Station works')).toBeVisible()
  await panel.getByRole('button', { name: 'How do I make a song?' }).click()
  await expect(panel.getByRole('listitem').filter({ hasText: 'Make a song' })).toBeVisible()
  expect(sent).toEqual({ text: 'How do I make a song?', attachments: [], thinking: false, where: 'the YuE2 songs page' })
  await expect(panel.getByRole('link', { name: 'Open in Chat' })).toHaveAttribute('href', '#/hosts/local/chat/help-1')
  await page.screenshot({ path: 'test-results/screenshots/assistant.png' })
  await panel.getByRole('button', { name: 'Start over' }).click()
  await expect(panel.getByText('Hi! I can explain how Generation Station works')).toBeVisible()
  await expect(panel.getByRole('link', { name: 'Open in Chat' })).toHaveAttribute('href', '#/hosts/local/chat/help-2')
  // The panel stays open across pages and reloads on this device.
  await page.reload()
  await expect(page.getByRole('region', { name: 'Assistant' })).toBeVisible()
})

test('the Models page labels each model by licence, shows the terms, and filters work use from personal use', async ({ page }) => {
  await connectFixtures(page, 'Fixture desktop', false, { llm: true, songs: true })
  await go(page, '#/hosts/local/models')
  const inkling = page.getByRole('region', { name: 'Inkling 2 Mini' })
  const songs = page.getByRole('region', { name: 'YuE2 songs' })
  await expect(inkling.getByText('Work use')).toBeVisible()
  await expect(songs.getByText('Personal use only')).toBeVisible()
  await openCard(page, 'YuE2 songs')
  const licence = songs.getByRole('region', { name: 'Licence' })
  await expect(licence.getByText('CC BY-NC 4.0 (non-commercial)')).toBeVisible()
  await expect(licence.getByText('Non-commercial use only.')).toBeVisible()
  await expect(licence.getByText('not legal advice')).toBeVisible()
  const filter = page.getByRole('group', { name: 'Show models by licence' })
  await filter.getByRole('button', { name: 'Work use' }).click()
  await expect(inkling).toBeVisible()
  await expect(songs).toHaveCount(0)
  await filter.getByRole('button', { name: 'Personal use only' }).click()
  await expect(songs).toBeVisible()
  await expect(inkling).toHaveCount(0)
  await filter.getByRole('button', { name: 'All' }).click()
  await expect(inkling).toBeVisible()
  await expect(songs).toBeVisible()
})

test('the Models page groups models by kind and charts their published quality scores', async ({ page }) => {
  await connectFixtures(page, 'Fixture desktop', false, { llm: true, songs: true, rated: true })
  await go(page, '#/hosts/local/models')
  // One section per kind, in the sidebar's order.
  await expect(page.getByRole('heading', { level: 2 }).filter({ hasText: /^(Text|Speech|Music)/ })).toHaveText(['Text1', 'Speech3', 'Music1'])
  const speech = page.getByRole('region', { name: 'Speech' })
  // Folded until asked for.
  const chart = speech.getByRole('figure', { name: 'Speech arena Elo' })
  await expect(speech.getByText('Quality ranking')).toBeVisible()
  await expect(chart).toBeHidden()
  await speech.getByText('Quality ranking').click()
  await expect(chart).toBeVisible()
  // Ranked high to low, with an estimate marked, and the unscored model named.
  await expect(chart.getByRole('listitem')).toHaveText([/Hosted Voice.*reference.*1310/, /Voice A.*1278/, /Voice B.*1104.*est\./])
  await expect(speech.getByText('Not on this ranking: Voice C.')).toBeVisible()
  await chart.getByRole('listitem').filter({ hasText: 'Voice B' }).hover()
  await expect(chart.locator('.quality-detail')).toContainText('Voice B: 1104 (estimated). Estimated from a sibling.')
  // A reference model that is not run here is drawn as an outlined bar in the ranking it has a score on, never as a card.
  const hosted = chart.getByRole('listitem').filter({ hasText: 'Hosted Voice' })
  await expect(hosted).toContainText('reference')
  await expect(hosted.locator('.quality-bar-reference')).toHaveCount(1)
  await expect(speech.locator('section.model-server')).toHaveCount(3)
  await hosted.hover()
  await expect(chart.locator('.quality-detail')).toContainText('Hosted Voice (not run here): 1310')
  await chart.getByText('Table').click()
  await expect(chart.getByRole('cell', { name: 'Estimate: Estimated from a sibling.' })).toBeVisible()
  // A button switches to the other ranking, which has its own models and its own gap.
  await speech.getByRole('button', { name: /Naturalness MOS/ }).click()
  const mos = speech.getByRole('figure', { name: 'Naturalness MOS' })
  await expect(mos.getByRole('listitem')).toHaveText([/Voice A.*4\.4/, /Voice C.*4\.1/]) // the reference has no score on this ranking
  await expect(speech.getByText('Not on this ranking: Voice B.')).toBeVisible()
  await expect(chart).toHaveCount(0)
  // A kind with one scored model has no chart.
  await expect(page.getByRole('region', { name: 'Music' }).getByText('Quality ranking')).toHaveCount(0)
})

test('models within a section sort by name or by the chosen ranking, either way', async ({ page }) => {
  await connectFixtures(page, 'Fixture desktop', false, { rated: true })
  await go(page, '#/hosts/local/models')
  const speech = page.getByRole('region', { name: 'Speech' })
  const names = () => speech.locator('section.model-server').evaluateAll((nodes) => nodes.map((node) => node.getAttribute('aria-label')))
  // Alphabetical by default (the fixture lists Voice B first), and in the sidenav too.
  expect(await names()).toEqual(['Voice A', 'Voice B', 'Voice C'])
  await expect(page.getByRole('navigation').getByRole('group', { name: 'Speech' }).getByRole('link')).toHaveText([/Voice A/, /Voice B/, /Voice C/])
  await speech.getByLabel('Sort').selectOption('name')
  await speech.getByRole('button', { name: /Z to A|A to Z/ }).click()
  expect(await names()).toEqual(['Voice C', 'Voice B', 'Voice A'])
  // Quality starts highest first, with the unscored model last; reversing keeps it last.
  await speech.getByLabel('Sort').selectOption('quality')
  expect(await names()).toEqual(['Voice A', 'Voice B', 'Voice C'])
  await speech.getByRole('button', { name: /highest first/ }).click()
  expect(await names()).toEqual(['Voice B', 'Voice A', 'Voice C'])
  // Quality follows the ranking chosen in the chart.
  await speech.getByText('Quality ranking').click()
  await speech.getByRole('button', { name: /Naturalness MOS/ }).click()
  await expect(speech.getByLabel('Sort')).toContainText('Quality (Naturalness MOS)')
  expect(await names()).toEqual(['Voice C', 'Voice A', 'Voice B'])
})

test('chat names no model that is not running, and offers a choice between those that are', async ({ page }) => {
  // Nothing running: the page says so without naming a model.
  await connectFixtures(page, 'Fixture desktop', false, { runtime: true, llm: true })
  await go(page, '#/hosts/local/chat')
  await expect(page.getByText('No text model is running.')).toBeVisible()
  await expect(page.locator('.chat-main').getByText(/Basalt|Inkling/)).toHaveCount(0)
})

test('with two chat models running, a dropdown picks which one answers and the choice is sent', async ({ page }) => {
  await connectFixtures(page, 'Fixture desktop', false, { runtime: true, llm: true, chatReady: true })
  await keepFresh(page)
  const conversation = { id: 'conv-2', title: 'New conversation', model_id: 'basalt', created_at: '2026-11-22T10:00:00Z', updated_at: '2026-11-22T10:00:00Z', busy: false }
  const sent: Record<string, unknown>[] = []
  await page.route('**/api/conversations', async (route) => {
    if (route.request().method() === 'POST') { sent.push({ created: route.request().postDataJSON() }); await route.fulfill({ status: 201, json: { ...conversation, model_id: (route.request().postDataJSON() as { model_id: string }).model_id } }); return }
    await route.fulfill({ json: { conversations: [] } })
  })
  await go(page, '#/hosts/local/chat')
  const pick = page.getByRole('combobox', { name: 'Model answering' })
  await expect(pick.locator('option')).toHaveText(['Basalt', 'Inkling 2 Mini'])
  await expect(pick).toHaveValue('basalt')
  await pick.selectOption('inkling2')
  await page.getByLabel('Message').fill('Hello')
  await page.getByLabel('Message').press('Enter')
  await expect.poll(() => sent.length).toBe(1)
  expect(sent[0]).toEqual({ created: { model_id: 'inkling2' } })
})

test('every decision model is used from one Decide page, with a dropdown over those running', async ({ page }) => {
  await connectFixtures(page, 'Fixture desktop', false, { decide: true })
  await go(page, '#/hosts/local/decide')
  // One entry in the sidenav, under Text, not one per model.
  await expect(page.getByRole('group', { name: 'Text' }).getByRole('link', { name: /^Decide/ })).toHaveCount(1)
  await expect(page.getByRole('link', { name: /Karpo|Small decider/ })).toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'Decide', level: 1 })).toBeVisible()
  const picker = page.getByRole('combobox', { name: 'Model answering' })
  await expect(picker.locator('option')).toHaveText(['Karpo 31B', 'Small decider'])
  // Results from every decision model are listed together, and an old model link opens the same page.
  await go(page, '#/hosts/local/services/decide_small')
  await expect(page.getByRole('heading', { name: 'Decide', level: 1 })).toBeVisible()
  await page.getByRole('button', { name: /Which team|charged twice|job-0000/i }).first().click()
  const decision = page.getByRole('region', { name: 'Decision' })
  await expect(decision.getByText('Answer: billing')).toBeVisible()
  await expect(decision.getByRole('cell', { name: '94.1%' })).toBeVisible()
  await expect(decision.getByText('Confidence: 88.2%')).toBeVisible()
})

test('the Text group in the sidenav is alphabetical, with Decide as one entry', async ({ page }) => {
  await connectFixtures(page, 'Fixture desktop', false, { llm: true, meeting: true, decide: true })
  await go(page, '#/overview')
  const links = page.getByRole('group', { name: 'Text' }).getByRole('link')
  const names = (await links.allInnerTexts()).map((text) => text.split('\n')[0].trim())
  expect(names).toEqual(['Chat', 'Decide', 'Meeting notes'])
})

test('Decide shows the model own address and a snippet for the tool picked', async ({ page }) => {
  await connectFixtures(page, 'Fixture desktop', false, { decide: true })
  await go(page, '#/hosts/local/decide')
  await page.getByText('Connect a tool to Karpo 31B').click()
  await expect(page.getByText('http://127.0.0.1:8400/v1/systemone', { exact: true })).toBeVisible()
  await expect(page.getByText('listens on this computer only')).toBeVisible()
  await expect(page.locator('.connect-code code')).toContainText("curl http://127.0.0.1:8400/v1/systemone")
  await page.getByRole('combobox', { name: 'Tool' }).selectOption('Python (requests)')
  await expect(page.locator('.connect-code code')).toContainText('requests.post("http://127.0.0.1:8400/v1/systemone"')
  // The choice is kept for next time.
  await page.reload()
  await page.getByText('Connect a tool to Karpo 31B').click()
  await expect(page.getByRole('combobox', { name: 'Tool' })).toHaveValue('Python (requests)')
})

test('Chat names the running model for the tool picked', async ({ page }) => {
  await page.route('**/api/conversations', (route) => route.fulfill({ json: { conversations: [] } }))
  await connectFixtures(page, 'Fixture desktop', false, { runtime: true, llm: true, chatReady: true })
  await go(page, '#/hosts/local/chat')
  await page.getByRole('combobox', { name: 'Model answering' }).selectOption({ label: 'Inkling 2 Mini' })
  await page.getByText('Connect a tool to Inkling 2 Mini').click()
  await page.getByRole('combobox', { name: 'Tool' }).selectOption('Aider')
  await expect(page.locator('.connect-code code')).toContainText('aider --model openai/inkling-2-mini')
  await expect(page.locator('.connect-code code')).toContainText('OPENAI_API_BASE=http://127.0.0.1:')
})
