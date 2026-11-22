import type { FormStart } from './components/Runtime'
import type { Generation, Model, Runtime } from './types'

/** A speech model that can clone a voice: its tab with a single audio sample, and the transcript field if any. */
export type VoiceTarget = { runtime: Runtime; ready: boolean; mode: string; sampleKey: string; textKey?: string }

export function voiceTargets(runtimes: Runtime[] | null | undefined, models: Model[] | null | undefined): VoiceTarget[] {
  const targets: VoiceTarget[] = []
  for (const runtime of runtimes ?? []) {
    if (runtime.workload !== 'speech' || !runtime.generation) continue
    const found = cloneTab(runtime.generation)
    if (found) targets.push({ runtime, ready: models?.find((model) => model.id === runtime.id)?.state === 'ready', ...found })
  }
  return targets
}

function cloneTab(generation: Generation) {
  for (const mode of generation.modes ?? []) {
    const sample = mode.inputs.find((field) => field.kind === 'files' && (field.accept ?? []).includes('audio'))
    if (!sample) continue
    const text = mode.inputs.find((field) => field.key === 'sample_text')
    return { mode: mode.key, sampleKey: sample.key, textKey: text?.key }
  }
  return undefined
}

/** The words spoken in a clip, from the quoted lines of its description ('She says: "Come in."'). */
export function spokenLine(prompt: unknown, max = 1000): string {
  if (typeof prompt !== 'string') return ''
  const quotes = [...prompt.matchAll(/["“]([^"”]{2,})["”]/g)].map((match) => match[1].trim())
  return quotes.join(' ').slice(0, max)
}

const RATE = 24000

/** The soundtrack of a video (or any audio the browser can decode) as a mono 16-bit WAV at 24 kHz. */
export async function soundtrackToWav(media: Blob): Promise<Blob> {
  let decoded: AudioBuffer
  try {
    decoded = await new OfflineAudioContext(1, 1, RATE).decodeAudioData(await media.arrayBuffer())
  } catch {
    throw new Error('This clip has no sound the browser can read.')
  }
  const length = Math.max(1, Math.ceil(decoded.duration * RATE))
  const context = new OfflineAudioContext(1, length, RATE)  // one channel: the browser mixes stereo down
  const source = context.createBufferSource()
  source.buffer = decoded
  source.connect(context.destination)
  source.start()
  const samples = (await context.startRendering()).getChannelData(0)
  // Mixing stereo down can go past full scale; turn a loud clip down rather than clip it.
  let peak = 0
  for (const sample of samples) peak = Math.max(peak, Math.abs(sample))
  if (peak > 0.99) samples.forEach((sample, index) => { samples[index] = sample * 0.99 / peak })
  const view = new DataView(new ArrayBuffer(44 + samples.length * 2))
  const text = (offset: number, value: string) => [...value].forEach((char, index) => view.setUint8(offset + index, char.charCodeAt(0)))
  text(0, 'RIFF'); view.setUint32(4, 36 + samples.length * 2, true); text(8, 'WAVE')
  text(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true)
  view.setUint32(24, RATE, true); view.setUint32(28, RATE * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true)
  text(36, 'data'); view.setUint32(40, samples.length * 2, true)
  samples.forEach((sample, index) => view.setInt16(44 + index * 2, Math.max(-1, Math.min(1, sample)) * 0x7fff, true))
  return new Blob([view], { type: 'audio/wav' })
}

// A form start waiting for another model's page (pages remount per model, so it is handed over here).
let pending: { hostId: string; modelId: string; start: FormStart } | null = null

export function handOff(hostId: string, modelId: string, start: FormStart) {
  pending = { hostId, modelId, start }
}

export function takeHandOff(hostId: string, modelId: string): FormStart | undefined {
  if (!pending || pending.hostId !== hostId || pending.modelId !== modelId) return undefined
  const { start } = pending
  pending = null
  return start
}
