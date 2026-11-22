export type Memory = { total_bytes: number; available_bytes: number; used_bytes: number }
export type Gpu = { id: string; index?: number; name: string; memory: Memory | null; error: string | null }
export type Host = {
  instance_id: string
  host: { hostname: string; os: string; label: string; role: string; scope: string }
  ram: Memory | null; ram_error: string | null; gpus: Gpu[]; gpu_error: string | null
  observed_at: string | null; sequence: number; age_seconds: number | null
  stale: boolean; stale_after_seconds: number; status: string; loading_enabled: boolean
  loading_reason: string
  /** Display only: RAM and per-GPU VRAM held by each running model's processes, keyed by model ID, then GPU ID. */
  model_memory?: Record<string, ModelMemory>
}
export type ModelMemory = { ram_bytes: number | null; gpus: Record<string, number>; error: string | null }
export type Snapshot = { data: Host; arrivedAt: number }
export type Model = { id: string; name: string; workload: string; state: string; loading_enabled: boolean; loading_reason?: string | null }
export type ModelProfile = { id: string; model_id: string; name: string; workload: string; ram_peak_bytes: number; gpu_vram_bytes_by_id: Record<string, number>; mode: 'simulation' }
export type NewProfile = { id: string; name: string; workload: string; ram_peak_bytes: number; gpu_vram_bytes_by_id: Record<string, number>; mode: 'simulation' }
export type RefusalResource = { resource: string; required_bytes: number; available_bytes: number; headroom_bytes?: number }
export type Refusal = { code: string; message: string; resources?: RefusalResource[] }
export type SettingValue = string | number | boolean | null
export type Launch = { preset: string; settings: Record<string, SettingValue>; gpus: number[] }
export type Operation = { id: string; model_id: string; action: string; status: string; simulation: boolean; worker_type: string; created_at?: string; updated_at?: string; error_code?: string | null; error_message?: string | null; refusal?: Refusal | null; launch?: Launch | null }
export type RuntimeSetting = { key: string; label: string; kind: 'int' | 'bool' | 'choice' | 'optional_int'; minimum: number | null; maximum: number | null; unit: string | null; help: string; default: SettingValue; options: string[] | null; option_labels?: Record<string, string> }
export type RuntimePreset = { name: string; description?: string | null; gpus: number[]; allowed_gpus: { index: number; name: string }[]; settings: RuntimeSetting[]; estimate: { ram_gib: number; gpu_min_free_gib: Record<string, number> } }
export type InputField = { key: string; label: string; kind: 'text' | 'textarea' | 'int' | 'choice' | 'seed' | 'files' | 'crop'; required: boolean; default: string | number | null; minimum: number | null; maximum: number | null; max_length: number | null; options: string[]; placeholder: string | null; help: string; advanced: boolean; accept?: ('image' | 'video' | 'audio')[]; max_count?: number | null; target?: string | null; shape_field?: string | null; show_when?: Record<string, string>; option_labels?: Record<string, string>; ratio_partner?: string | null; ratio_role?: 'width' | 'height' | null }
/** A way of making something, shown as a tab with its own form. */
export type GenerationMode = { key: string; label: string; help: string; inputs: InputField[] }
/** A file uploaded for a request, before a job uses it. */
export type UploadRecord = { id: string; name: string; kind: 'image' | 'video' | 'audio'; mime: string; bytes: number }
/** A job's own copy of a file it was given (a reference picture, video or audio). */
export type JobFile = { name: string; kind: string; mime: string; original: string }
/** A measured time for one result; the first whose conditions all match applies. */
export type Timing = { seconds: number; first_seconds: number | null; when: Record<string, string>; preset: string | null; gpu: number | null; note: string | null }
export type Generation = { output_kind: 'audio' | 'image' | 'video'; inputs: InputField[]; modes?: GenerationMode[]; timings?: Timing[] }
export type Runtime = { id: string; kind: string; name: string; description?: string | null; workload: string; port: number; default_preset: string; presets: Record<string, RuntimePreset>; last_launch: Launch | null; max_gpus?: number | null; generation?: Generation | null }
export type JobOutput = { name: string; mime: string; bytes: number }
/** `details` is what the worker actually used (seed, steps, size, full prompt) and `seconds` taken; `launch` the model settings it ran with. */
export type Job = { id: string; model_id: string; inputs: Record<string, string | number | JobFile[]>; status: 'queued' | 'running' | 'done' | 'failed' | 'cancelled'; progress: string | null; outputs: JobOutput[]; error_message: string | null; created_at: string; finished_at: string | null; details?: Record<string, unknown> | null; launch?: Launch | null }
export type Connection = 'idle' | 'connecting' | 'connected' | 'reconnecting' | 'error'
export type ApiErrorBody = { detail?: string | Refusal; [key: string]: unknown }

export class ApiError extends Error {
  constructor(readonly status: number, readonly body: ApiErrorBody) {
    super(typeof body.detail === 'string' ? body.detail : body.detail?.message ?? `Host request failed (${status}).`)
  }
}
/** What a start with the chosen preset, GPUs and settings would ask admission for (display only). */
export type RuntimeEstimate = {
  ram_bytes: number; gpu_vram_bytes_by_id: Record<string, number>
  ram_headroom_bytes: number; gpu_headroom_bytes: number
  reserved_ram_bytes: number; reserved_gpu_vram_bytes_by_id: Record<string, number>
}
